import os
import math
import base64
import asyncio
from binascii import hexlify
#from weakref import WeakSet
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

#from aiohttp.web import Application, AppRunner, WebSocketResponse, TCPSite
#from aiohttp.http_websocket import WSMsgType, WSCloseCode

from torba.rpc.jsonrpc import RPCError
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
        print('started websocket')

    async def stop(self):
        await self.runner.cleanup()
        print('stopped websocket')

    async def on_connect(self, request):
        web_socket = WebSocketResponse()
        await web_socket.prepare(request)
        self.app['websockets'].add(web_socket)
        try:
            async for msg in web_socket:
                if msg.type == WSMsgType.TEXT:
                    print(msg.data)
                    await self.on_status(None)
                elif msg.type == WSMsgType.ERROR:
                    print('web socket connection closed with exception %s' %
                          web_socket.exception())
        finally:
            self.app['websockets'].discard(web_socket)
        return web_socket

    @staticmethod
    async def on_shutdown(app):
        print('disconnecting websockets')
        for web_socket in app['websockets']:
            await web_socket.close(code=WSCloseCode.GOING_AWAY, message='Server shutdown')


class LBRYSessionManager(SessionManager):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.query_executor = None
        if self.can_start_websocket:
            self.websocket = AdminWebSocket(self)
            self.metric_sender = None
            self.metrics = {
                'search': 0,
                'search_time': 0,
                'resolve': 0,
                'resolve_time': 0
            }

    @property
    def can_start_websocket(self):
        return self.env.websocket_host is not None and self.env.websocket_port is not None

    def add_metric(self, command, metric):
        if self.can_start_websocket:
            self.metrics[command] += 1
            self.metrics[f'{command}_time'] += int(metric['total']*1000)

    async def send_metrics(self):
        while self.running:
            metrics = self.metrics
            self.metrics = {
                'search': 0,
                'search_time': 0,
                'resolve': 0,
                'resolve_time': 0
            }
            self.websocket.send_message(metrics)
            await asyncio.sleep(1)

    async def start_other(self):
        args = dict(initializer=reader.initializer, initargs=('claims.db', self.env.coin.NET))
        if self.env.max_query_workers is not None and self.env.max_query_workers == 0:
            self.query_executor = ThreadPoolExecutor(max_workers=1, **args)
        else:
            self.query_executor = ProcessPoolExecutor(
                max_workers=self.env.max_query_workers or max(os.cpu_count(), 4), **args
            )
        if self.can_start_websocket:
            self.running = True
            await self.websocket.start()
            self.metric_sender = asyncio.create_task(self.send_metrics())

    async def stop_other(self):
        if self.can_start_websocket:
            self.running = False
            self.metric_sender.cancel()
            await self.websocket.stop()
        self.query_executor.shutdown()


class LBRYElectrumX(ElectrumX):
    PROTOCOL_MIN = (0, 0)  # temporary, for supporting 0.10 protocol
    max_errors = math.inf  # don't disconnect people for errors! let them happen...

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

    async def claimtrie_search(self, **kwargs):
        if 'claim_id' in kwargs:
            self.assert_claim_id(kwargs['claim_id'])
        data, metrics = await asyncio.get_running_loop().run_in_executor(
            self.session_mgr.query_executor, reader.search_to_bytes, kwargs
        )
        self.session_mgr.add_metric('search', metrics)
        return base64.b64encode(data).decode()

    async def claimtrie_resolve(self, *urls):
        data, metrics = await asyncio.get_running_loop().run_in_executor(
            self.session_mgr.query_executor, reader.resolve_to_bytes, urls
        )
        self.session_mgr.add_metric('resolve', metrics)
        return base64.b64encode(data).decode()

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
