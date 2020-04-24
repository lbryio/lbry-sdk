import asyncio
import itertools
import json
import time
from functools import wraps
from pylru import lrucache

import aiohttp

from lbry.wallet.rpc.jsonrpc import RPCError
from lbry.wallet.server.util import hex_to_bytes, class_logger
from lbry.wallet.rpc import JSONRPC
from lbry.wallet.server import prometheus


class DaemonError(Exception):
    """Raised when the daemon returns an error in its results."""


class WarmingUpError(Exception):
    """Internal - when the daemon is warming up."""


class WorkQueueFullError(Exception):
    """Internal - when the daemon's work queue is full."""


class Daemon:
    """Handles connections to a daemon at the given URL."""

    WARMING_UP = -28
    id_counter = itertools.count()

    def __init__(self, coin, url, max_workqueue=10, init_retry=0.25,
                 max_retry=4.0):
        self.coin = coin
        self.logger = class_logger(__name__, self.__class__.__name__)
        self.set_url(url)
        # Limit concurrent RPC calls to this number.
        # See DEFAULT_HTTP_WORKQUEUE in bitcoind, which is typically 16
        self.workqueue_semaphore = asyncio.Semaphore(value=max_workqueue)
        self.init_retry = init_retry
        self.max_retry = max_retry
        self._height = None
        self.available_rpcs = {}
        self.connector = aiohttp.TCPConnector()
        self._block_hash_cache = lrucache(100000)
        self._block_cache = lrucache(10000)

    async def close(self):
        if self.connector:
            await self.connector.close()
            self.connector = None

    def set_url(self, url):
        """Set the URLS to the given list, and switch to the first one."""
        urls = url.split(',')
        urls = [self.coin.sanitize_url(url) for url in urls]
        for n, url in enumerate(urls):
            status = '' if n else ' (current)'
            logged_url = self.logged_url(url)
            self.logger.info(f'daemon #{n + 1} at {logged_url}{status}')
        self.url_index = 0
        self.urls = urls

    def current_url(self):
        """Returns the current daemon URL."""
        return self.urls[self.url_index]

    def logged_url(self, url=None):
        """The host and port part, for logging."""
        url = url or self.current_url()
        return url[url.rindex('@') + 1:]

    def failover(self):
        """Call to fail-over to the next daemon URL.

        Returns False if there is only one, otherwise True.
        """
        if len(self.urls) > 1:
            self.url_index = (self.url_index + 1) % len(self.urls)
            self.logger.info(f'failing over to {self.logged_url()}')
            return True
        return False

    def client_session(self):
        """An aiohttp client session."""
        return aiohttp.ClientSession(connector=self.connector, connector_owner=False)

    async def _send_data(self, data):
        if not self.connector:
            raise asyncio.CancelledError('Tried to send request during shutdown.')
        async with self.workqueue_semaphore:
            async with self.client_session() as session:
                async with session.post(self.current_url(), data=data) as resp:
                    kind = resp.headers.get('Content-Type', None)
                    if kind == 'application/json':
                        return await resp.json()
                    # bitcoind's HTTP protocol "handling" is a bad joke
                    text = await resp.text()
                    if 'Work queue depth exceeded' in text:
                        raise WorkQueueFullError
                    text = text.strip() or resp.reason
                    self.logger.error(text)
                    raise DaemonError(text)

    async def _send(self, payload, processor):
        """Send a payload to be converted to JSON.

        Handles temporary connection issues.  Daemon response errors
        are raise through DaemonError.
        """

        def log_error(error):
            nonlocal last_error_log, retry
            now = time.time()
            if now - last_error_log > 60:
                last_error_log = now
                self.logger.error(f'{error}  Retrying occasionally...')
            if retry == self.max_retry and self.failover():
                retry = 0

        on_good_message = None
        last_error_log = 0
        data = json.dumps(payload)
        retry = self.init_retry
        methods = tuple(
            [payload['method']] if isinstance(payload, dict) else [request['method'] for request in payload]
        )
        while True:
            try:
                for method in methods:
                    prometheus.METRICS.LBRYCRD_PENDING_COUNT.labels(method=method).inc()
                result = await self._send_data(data)
                result = processor(result)
                if on_good_message:
                    self.logger.info(on_good_message)
                return result
            except asyncio.TimeoutError:
                log_error('timeout error.')
            except aiohttp.ServerDisconnectedError:
                log_error('disconnected.')
                on_good_message = 'connection restored'
            except aiohttp.ClientConnectionError:
                log_error('connection problem - is your daemon running?')
                on_good_message = 'connection restored'
            except aiohttp.ClientError as e:
                log_error(f'daemon error: {e}')
                on_good_message = 'running normally'
            except WarmingUpError:
                log_error('starting up checking blocks.')
                on_good_message = 'running normally'
            except WorkQueueFullError:
                log_error('work queue full.')
                on_good_message = 'running normally'
            finally:
                for method in methods:
                    prometheus.METRICS.LBRYCRD_PENDING_COUNT.labels(method=method).dec()
            await asyncio.sleep(retry)
            retry = max(min(self.max_retry, retry * 2), self.init_retry)

    async def _send_single(self, method, params=None):
        """Send a single request to the daemon."""

        start = time.perf_counter()

        def processor(result):
            err = result['error']
            if not err:
                return result['result']
            if err.get('code') == self.WARMING_UP:
                raise WarmingUpError
            raise DaemonError(err)

        payload = {'method': method, 'id': next(self.id_counter)}
        if params:
            payload['params'] = params
        result = await self._send(payload, processor)
        prometheus.METRICS.LBRYCRD_REQUEST_TIMES.labels(method=method).observe(time.perf_counter() - start)
        return result

    async def _send_vector(self, method, params_iterable, replace_errs=False):
        """Send several requests of the same method.

        The result will be an array of the same length as params_iterable.
        If replace_errs is true, any item with an error is returned as None,
        otherwise an exception is raised."""

        start = time.perf_counter()

        def processor(result):
            errs = [item['error'] for item in result if item['error']]
            if any(err.get('code') == self.WARMING_UP for err in errs):
                raise WarmingUpError
            if not errs or replace_errs:
                return [item['result'] for item in result]
            raise DaemonError(errs)

        payload = [{'method': method, 'params': p, 'id': next(self.id_counter)}
                   for p in params_iterable]
        result = []
        if payload:
            result = await self._send(payload, processor)
        prometheus.METRICS.LBRYCRD_REQUEST_TIMES.labels(method=method).observe(time.perf_counter()-start)
        return result

    async def _is_rpc_available(self, method):
        """Return whether given RPC method is available in the daemon.

        Results are cached and the daemon will generally not be queried with
        the same method more than once."""
        available = self.available_rpcs.get(method)
        if available is None:
            available = True
            try:
                await self._send_single(method)
            except DaemonError as e:
                err = e.args[0]
                error_code = err.get("code")
                available = error_code != JSONRPC.METHOD_NOT_FOUND
            self.available_rpcs[method] = available
        return available

    async def block_hex_hashes(self, first, count):
        """Return the hex hashes of count block starting at height first."""
        if first + count < (self.cached_height() or 0) - 200:
            return await self._cached_block_hex_hashes(first, count)
        params_iterable = ((h, ) for h in range(first, first + count))
        return await self._send_vector('getblockhash', params_iterable)

    async def _cached_block_hex_hashes(self, first, count):
        """Return the hex hashes of count block starting at height first."""
        cached = self._block_hash_cache.get((first, count))
        if cached:
            return cached
        params_iterable = ((h, ) for h in range(first, first + count))
        self._block_hash_cache[(first, count)] = await self._send_vector('getblockhash', params_iterable)
        return self._block_hash_cache[(first, count)]

    async def deserialised_block(self, hex_hash):
        """Return the deserialised block with the given hex hash."""
        if not self._block_cache.get(hex_hash):
            self._block_cache[hex_hash] = await self._send_single('getblock', (hex_hash, True))
        return self._block_cache[hex_hash]

    async def raw_blocks(self, hex_hashes):
        """Return the raw binary blocks with the given hex hashes."""
        params_iterable = ((h, False) for h in hex_hashes)
        blocks = await self._send_vector('getblock', params_iterable)
        # Convert hex string to bytes
        return [hex_to_bytes(block) for block in blocks]

    async def mempool_hashes(self):
        """Update our record of the daemon's mempool hashes."""
        return await self._send_single('getrawmempool')

    async def estimatefee(self, block_count):
        """Return the fee estimate for the block count.  Units are whole
        currency units per KB, e.g. 0.00000995, or -1 if no estimate
        is available.
        """
        args = (block_count, )
        if await self._is_rpc_available('estimatesmartfee'):
            estimate = await self._send_single('estimatesmartfee', args)
            return estimate.get('feerate', -1)
        return await self._send_single('estimatefee', args)

    async def getnetworkinfo(self):
        """Return the result of the 'getnetworkinfo' RPC call."""
        return await self._send_single('getnetworkinfo')

    async def relayfee(self):
        """The minimum fee a low-priority tx must pay in order to be accepted
        to the daemon's memory pool."""
        network_info = await self.getnetworkinfo()
        return network_info['relayfee']

    async def getrawtransaction(self, hex_hash, verbose=False):
        """Return the serialized raw transaction with the given hash."""
        # Cast to int because some coin daemons are old and require it
        return await self._send_single('getrawtransaction',
                                       (hex_hash, int(verbose)))

    async def getrawtransactions(self, hex_hashes, replace_errs=True):
        """Return the serialized raw transactions with the given hashes.

        Replaces errors with None by default."""
        params_iterable = ((hex_hash, 0) for hex_hash in hex_hashes)
        txs = await self._send_vector('getrawtransaction', params_iterable,
                                      replace_errs=replace_errs)
        # Convert hex strings to bytes
        return [hex_to_bytes(tx) if tx else None for tx in txs]

    async def broadcast_transaction(self, raw_tx):
        """Broadcast a transaction to the network."""
        return await self._send_single('sendrawtransaction', (raw_tx, ))

    async def height(self):
        """Query the daemon for its current height."""
        self._height = await self._send_single('getblockcount')
        return self._height

    def cached_height(self):
        """Return the cached daemon height.

        If the daemon has not been queried yet this returns None."""
        return self._height


def handles_errors(decorated_function):
    @wraps(decorated_function)
    async def wrapper(*args, **kwargs):
        try:
            return await decorated_function(*args, **kwargs)
        except DaemonError as daemon_error:
            raise RPCError(1, daemon_error.args[0])
    return wrapper


class LBCDaemon(Daemon):
    @handles_errors
    async def getrawtransaction(self, hex_hash, verbose=False):
        return await super().getrawtransaction(hex_hash=hex_hash, verbose=verbose)

    @handles_errors
    async def getclaimbyid(self, claim_id):
        '''Given a claim id, retrieves claim information.'''
        return await self._send_single('getclaimbyid', (claim_id,))

    @handles_errors
    async def getclaimsbyids(self, claim_ids):
        '''Given a list of claim ids, batches calls to retrieve claim information.'''
        return await self._send_vector('getclaimbyid', ((claim_id,) for claim_id in claim_ids))

    @handles_errors
    async def getclaimsforname(self, name):
        '''Given a name, retrieves all claims matching that name.'''
        return await self._send_single('getclaimsforname', (name,))

    @handles_errors
    async def getclaimsfortx(self, txid):
        '''Given a txid, returns the claims it make.'''
        return await self._send_single('getclaimsfortx', (txid,)) or []

    @handles_errors
    async def getnameproof(self, name, block_hash=None):
        '''Given a name and optional block_hash, returns a name proof and winner, if any.'''
        return await self._send_single('getnameproof', (name, block_hash,) if block_hash else (name,))

    @handles_errors
    async def getvalueforname(self, name):
        '''Given a name, returns the winning claim value.'''
        return await self._send_single('getvalueforname', (name,))

    @handles_errors
    async def claimname(self, name, hexvalue, amount):
        '''Claim a name, used for functional tests only.'''
        return await self._send_single('claimname', (name, hexvalue, float(amount)))
