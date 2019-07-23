import os
import math
import time
import base64
import asyncio
from binascii import hexlify
from pylru import lrucache
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

from torba.rpc.jsonrpc import RPCError, JSONRPC
from torba.server.session import ElectrumX, SessionManager
from torba.server import util

from lbry.wallet.server.block_processor import LBRYBlockProcessor
from lbry.wallet.server.db.writer import LBRYDB
from lbry.wallet.server.db import reader
from lbry.wallet.server.websocket import AdminWebSocket
from lbry.wallet.server.metrics import ServerLoadData, APICallMetrics


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
        self.metrics = ServerLoadData()
        self.metrics_loop = None
        self.running = False
        if self.env.websocket_host is not None and self.env.websocket_port is not None:
            self.websocket = AdminWebSocket(self)
        self.search_cache = self.bp.search_cache
        self.search_cache['search'] = lrucache(10000)
        self.search_cache['resolve'] = lrucache(10000)

    async def process_metrics(self):
        while self.running:
            data = self.metrics.to_json_and_reset({'sessions': self.session_count()})
            if self.websocket is not None:
                self.websocket.send_message(data)
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
            self.metrics_loop = asyncio.create_task(self.process_metrics())

    async def stop_other(self):
        self.running = False
        if self.env.track_metrics:
            self.metrics_loop.cancel()
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
            'blockchain.claimtrie.getnameproofs': self.claimtrie_getnameproofs,
            'blockchain.claimtrie.getclaimsbyids': self.claimtrie_getclaimsbyids,
            'blockchain.block.get_server_height': self.get_server_height,
        }
        self.request_handlers.update(handlers)

    async def run_in_executor(self, metrics: APICallMetrics, func, kwargs):
        start = time.perf_counter()
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                self.session_mgr.query_executor, func, kwargs
            )
        except reader.SQLiteInterruptedError as error:
            metrics.query_interrupt(start, error.metrics)
            raise RPCError(JSONRPC.QUERY_TIMEOUT, 'sqlite query timed out')
        except reader.SQLiteOperationalError as error:
            metrics.query_error(start, error.metrics)
            raise RPCError(JSONRPC.INTERNAL_ERROR, 'query failed to execute')
        except:
            metrics.query_error(start, {})
            raise RPCError(JSONRPC.INTERNAL_ERROR, 'unknown server error')

        if self.env.track_metrics:
            (result, metrics_data) = result
            metrics.query_response(start, metrics_data)

        return base64.b64encode(result).decode()

    async def run_and_cache_query(self, query_name, function, kwargs):
        if self.env.track_metrics:
            metrics = self.session_mgr.metrics.for_api(query_name)
        else:
            metrics = APICallMetrics(query_name)
        metrics.start()
        cache = self.session_mgr.search_cache[query_name]
        cache_key = str(kwargs)
        cache_item = cache.get(cache_key)
        if cache_item is None:
            cache_item = cache[cache_key] = ResultCacheItem()
        elif cache_item.result is not None:
            metrics.cache_response()
            return cache_item.result
        async with cache_item.lock:
            if cache_item.result is None:
                cache_item.result = await self.run_in_executor(
                    metrics, function, kwargs
                )
            else:
                metrics.cache_response()
            return cache_item.result

    async def claimtrie_search(self, **kwargs):
        if kwargs:
            return await self.run_and_cache_query('search', reader.search_to_bytes, kwargs)

    async def claimtrie_resolve(self, *urls):
        if urls:
            return await self.run_and_cache_query('resolve', reader.resolve_to_bytes, urls)

    async def get_server_height(self):
        return self.bp.height

    def claimtrie_getnameproofs(self, block_hash, *names):
        return self.daemon._send_vector('getnameproof', iter((name, block_hash) for name in names))

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
