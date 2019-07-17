import os
import math
import time
import base64
import asyncio
from binascii import hexlify
from weakref import WeakSet
from pylru import lrucache
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

from aiohttp.web import Application, AppRunner, WebSocketResponse, TCPSite
from aiohttp.http_websocket import WSMsgType, WSCloseCode

from torba.rpc.jsonrpc import RPCError, JSONRPC
from torba.server.session import ElectrumX, SessionManager
from torba.server import util

from lbry.wallet.server.block_processor import LBRYBlockProcessor
from lbry.wallet.server.db.writer import LBRYDB
from lbry.wallet.server.db import reader


class AdminWebSocket:

    def __init__(self, manager):
        self.manager = manager
        self.app = Application()
        self.app['websockets'] = WeakSet()
        self.app.router.add_get('/', self.on_connect)
        self.app.on_shutdown.append(self.on_shutdown)
        self.runner = AppRunner(self.app)

    async def on_status(self, _):
        if not self.app['websockets']:
            return
        self.send_message({
            'type': 'status',
            'height': self.manager.daemon.cached_height(),
        })

    def send_message(self, msg):
        for web_socket in self.app['websockets']:
            asyncio.create_task(web_socket.send_json(msg))

    async def start(self):
        await self.runner.setup()
        await TCPSite(self.runner, self.manager.env.websocket_host, self.manager.env.websocket_port).start()

    async def stop(self):
        await self.runner.cleanup()

    async def on_connect(self, request):
        web_socket = WebSocketResponse()
        await web_socket.prepare(request)
        self.app['websockets'].add(web_socket)
        try:
            async for msg in web_socket:
                if msg.type == WSMsgType.TEXT:
                    await self.on_status(None)
                elif msg.type == WSMsgType.ERROR:
                    print('web socket connection closed with exception %s' %
                          web_socket.exception())
        finally:
            self.app['websockets'].discard(web_socket)
        return web_socket

    @staticmethod
    async def on_shutdown(app):
        for web_socket in set(app['websockets']):
            await web_socket.close(code=WSCloseCode.GOING_AWAY, message='Server shutdown')


class ResultCacheItem:
    __slots__ = '_result', 'lock', 'has_result'

    def __init__(self):
        self.has_result = asyncio.Event()
        self.lock = asyncio.Lock()
        self._result = None

    @property
    def result(self) -> str:
        return self._result

    @result.setter
    def result(self, result: str):
        self._result = result
        if result is not None:
            self.has_result.set()


class LBRYSessionManager(SessionManager):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.query_executor = None
        self.websocket = None
        self.metrics_processor = None
        self.command_metrics = {}
        self.reader_metrics = {}
        self.running = False
        if self.env.websocket_host is not None and self.env.websocket_port is not None:
            self.websocket = AdminWebSocket(self)
        self.search_cache = self.bp.search_cache
        self.search_cache['search'] = lrucache(10000)
        self.search_cache['resolve'] = lrucache(10000)

    def get_command_tracking_info(self, command):
        if command not in self.command_metrics:
            self.command_metrics[command] = {
                'cache_hit': 0,
                'started': 0,
                'finished': 0,
                'total_time': 0,
                'execution_time': 0,
                'query_time': 0,
                'query_count': 0,
                'interrupted': 0,
                'interrupted_query_values': [],
            }
        return self.command_metrics[command]

    def cache_hit(self, command_name):
        if self.env.track_metrics:
            command = self.get_command_tracking_info(command_name)
            command['cache_hit'] += 1

    def start_command_tracking(self, command_name):
        if self.env.track_metrics:
            command = self.get_command_tracking_info(command_name)
            command['started'] += 1

    def finish_command_tracking(self, command_name, elapsed, metrics):
        if self.env.track_metrics:
            command = self.get_command_tracking_info(command_name)
            command['finished'] += 1
            command['total_time'] += elapsed
            if 'execute_query' in metrics:
                command['execution_time'] += (metrics[command_name]['total'] - metrics['execute_query']['total'])
                command['query_time'] += metrics['execute_query']['total']
                command['query_count'] += metrics['execute_query']['calls']
            for func_name, func_metrics in metrics.items():
                reader = self.reader_metrics.setdefault(func_name, {})
                for key in func_metrics:
                    if key not in reader:
                        reader[key] = func_metrics[key]
                    else:
                        reader[key] += func_metrics[key]

    def interrupted_command_error(self, command_name, elapsed, metrics, kwargs):
        if self.env.track_metrics:
            command = self.get_command_tracking_info(command_name)
            command['finished'] += 1
            command['interrupted'] += 1
            command['total_time'] += elapsed
            command['execution_time'] += (metrics[command_name]['total'] - metrics['execute_query']['total'])
            command['query_time'] += metrics['execute_query']['total']
            command['query_count'] += metrics['execute_query']['calls']
            if len(command['interrupted_query_values']) < 100:
                command['interrupted_query_values'].append(kwargs)

    async def process_metrics(self):
        while self.running:
            commands, self.command_metrics = self.command_metrics, {}
            reader, self.reader_metrics = self.reader_metrics, {}
            if self.websocket is not None:
                self.websocket.send_message({
                    'commands': commands,
                    'reader': reader
                })
            await asyncio.sleep(1)

    async def start_other(self):
        self.running = True
        args = dict(
            initializer=reader.initializer,
            initargs=(self.logger, 'claims.db', self.env.coin.NET, self.env.database_query_timeout,
                      self.env.track_metrics)
        )
        if self.env.max_query_workers is not None and self.env.max_query_workers == 0:
            self.query_executor = ThreadPoolExecutor(max_workers=1, **args)
        else:
            self.query_executor = ProcessPoolExecutor(
                max_workers=self.env.max_query_workers or max(os.cpu_count(), 4), **args
            )
        if self.websocket is not None:
            await self.websocket.start()
        if self.env.track_metrics:
            self.metrics_processor = asyncio.create_task(self.process_metrics())

    async def stop_other(self):
        self.running = False
        if self.env.track_metrics:
            self.metrics_processor.cancel()
        if self.websocket is not None:
            await self.websocket.stop()
        self.query_executor.shutdown()


class LBRYElectrumX(ElectrumX):
    PROTOCOL_MIN = (0, 0)  # temporary, for supporting 0.10 protocol
    max_errors = math.inf  # don't disconnect people for errors! let them happen...
    session_mgr: LBRYSessionManager

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # fixme: this is a rebase hack, we need to go through ChainState instead later
        self.daemon = self.session_mgr.daemon
        self.bp: LBRYBlockProcessor = self.session_mgr.bp
        self.db: LBRYDB = self.bp.db

    def set_request_handlers(self, ptuple):
        super().set_request_handlers(ptuple)
        handlers = {
            'blockchain.transaction.get_height': self.transaction_get_height,
            'blockchain.claimtrie.search': self.claimtrie_search,
            'blockchain.claimtrie.resolve': self.claimtrie_resolve,
            'blockchain.claimtrie.getclaimsbyids': self.claimtrie_getclaimsbyids,
            'blockchain.block.get_server_height': self.get_server_height,
        }
        self.request_handlers.update(handlers)

    async def run_in_executor(self, name, func, kwargs):
        start = None
        if self.env.track_metrics:
            self.session_mgr.start_command_tracking(name)
            start = time.perf_counter()
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                self.session_mgr.query_executor, func, kwargs
            )
        except reader.SQLiteInterruptedError as error:
            self.session_mgr.interrupted_command_error(
                name, int((time.perf_counter() - start) * 1000), error.metrics, kwargs
            )
            raise RPCError(JSONRPC.QUERY_TIMEOUT, 'sqlite query timed out')

        if self.env.track_metrics:
            elapsed = int((time.perf_counter() - start) * 1000)
            (result, metrics) = result
            self.session_mgr.finish_command_tracking(name, elapsed, metrics)
        return base64.b64encode(result).decode()

    async def run_and_cache_query(self, query_name, function, kwargs):
        cache = self.session_mgr.search_cache[query_name]
        cache_key = str(kwargs)
        cache_item = cache.get(cache_key)
        if cache_item is None:
            cache_item = cache[cache_key] = ResultCacheItem()
        elif cache_item.result is not None:
            self.session_mgr.cache_hit(query_name)
            return cache_item.result
        async with cache_item.lock:
            result = cache_item.result
            if result is None:
                result = cache_item.result = await self.run_in_executor(
                    query_name, function, kwargs
                )
            else:
                self.session_mgr.cache_hit(query_name)
            return result

    async def claimtrie_search(self, **kwargs):
        if kwargs:
            return await self.run_and_cache_query('search', reader.search_to_bytes, kwargs)

    async def claimtrie_resolve(self, *urls):
        if urls:
            return await self.run_and_cache_query('resolve', reader.resolve_to_bytes, urls)

    async def get_server_height(self):
        return self.bp.height

    async def transaction_get_height(self, tx_hash):
        self.assert_tx_hash(tx_hash)
        transaction_info = await self.daemon.getrawtransaction(tx_hash, True)
        if transaction_info and 'hex' in transaction_info and 'confirmations' in transaction_info:
            # an unconfirmed transaction from lbrycrdd will not have a 'confirmations' field
            return (self.db.db_height - transaction_info['confirmations']) + 1
        elif transaction_info and 'hex' in transaction_info:
            return -1
        return None

    async def claimtrie_getclaimsbyids(self, *claim_ids):
        claims = await self.batched_formatted_claims_from_daemon(claim_ids)
        return dict(zip(claim_ids, claims))

    async def batched_formatted_claims_from_daemon(self, claim_ids):
        claims = await self.daemon.getclaimsbyids(claim_ids)
        result = []
        for claim in claims:
            if claim and claim.get('value'):
                result.append(self.format_claim_from_daemon(claim))
        return result

    def format_claim_from_daemon(self, claim, name=None):
        """Changes the returned claim data to the format expected by lbry and adds missing fields."""

        if not claim:
            return {}

        # this ISO-8859 nonsense stems from a nasty form of encoding extended characters in lbrycrd
        # it will be fixed after the lbrycrd upstream merge to v17 is done
        # it originated as a fear of terminals not supporting unicode. alas, they all do

        if 'name' in claim:
            name = claim['name'].encode('ISO-8859-1').decode()
        info = self.db.sql.get_claims(claim_id=claim['claimId'])
        if not info:
            #  raise RPCError("Lbrycrd has {} but not lbryumx, please submit a bug report.".format(claim_id))
            return {}
        address = info.address.decode()
        # fixme: temporary
        #supports = self.format_supports_from_daemon(claim.get('supports', []))
        supports = []

        amount = get_from_possible_keys(claim, 'amount', 'nAmount')
        height = get_from_possible_keys(claim, 'height', 'nHeight')
        effective_amount = get_from_possible_keys(claim, 'effective amount', 'nEffectiveAmount')
        valid_at_height = get_from_possible_keys(claim, 'valid at height', 'nValidAtHeight')

        result = {
            "name": name,
            "claim_id": claim['claimId'],
            "txid": claim['txid'],
            "nout": claim['n'],
            "amount": amount,
            "depth": self.db.db_height - height + 1,
            "height": height,
            "value": hexlify(claim['value'].encode('ISO-8859-1')).decode(),
            "address": address,  # from index
            "supports": supports,
            "effective_amount": effective_amount,
            "valid_at_height": valid_at_height
        }
        if 'claim_sequence' in claim:
            # TODO: ensure that lbrycrd #209 fills in this value
            result['claim_sequence'] = claim['claim_sequence']
        else:
            result['claim_sequence'] = -1
        if 'normalized_name' in claim:
            result['normalized_name'] = claim['normalized_name'].encode('ISO-8859-1').decode()
        return result

    def assert_tx_hash(self, value):
        '''Raise an RPCError if the value is not a valid transaction
        hash.'''
        try:
            if len(util.hex_to_bytes(value)) == 32:
                return
        except Exception:
            pass
        raise RPCError(1, f'{value} should be a transaction hash')

    def assert_claim_id(self, value):
        '''Raise an RPCError if the value is not a valid claim id
        hash.'''
        try:
            if len(util.hex_to_bytes(value)) == 20:
                return
        except Exception:
            pass
        raise RPCError(1, f'{value} should be a claim id hash')


def get_from_possible_keys(dictionary, *keys):
    for key in keys:
        if key in dictionary:
            return dictionary[key]
