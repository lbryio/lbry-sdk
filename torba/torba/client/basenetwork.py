import logging
import asyncio
from operator import itemgetter
from typing import Dict, Optional
from time import time

from torba.rpc import RPCSession as BaseClientSession, Connector, RPCError

from torba import __version__
from torba.stream import StreamController

log = logging.getLogger(__name__)


class ClientSession(BaseClientSession):

    def __init__(self, *args, network, server, timeout=30, **kwargs):
        self.network = network
        self.server = server
        super().__init__(*args, **kwargs)
        self._on_disconnect_controller = StreamController()
        self.on_disconnected = self._on_disconnect_controller.stream
        self.bw_limit = self.framer.max_size = self.max_errors = 1 << 32
        self.timeout = timeout
        self.max_seconds_idle = timeout * 2
        self.latency = 1 << 32

    @property
    def available(self):
        return not self.is_closing() and self._can_send.is_set() and self.latency < 1 << 32

    async def send_request(self, method, args=()):
        try:
            start = time()
            result = await asyncio.wait_for(
                super().send_request(method, args), timeout=self.timeout
            )
            self.latency = time() - start
            return result
        except RPCError as e:
            log.warning("Wallet server returned an error. Code: %s Message: %s", *e.args)
            raise e
        except TimeoutError:
            self.latency = 1 << 32
            raise

    async def ensure_session(self):
        # Handles reconnecting and maintaining a session alive
        # TODO: change to 'ping' on newer protocol (above 1.2)
        retry_delay = default_delay = 0.1
        while True:
            try:
                if self.is_closing():
                    await self.create_connection(self.timeout)
                    await self.ensure_server_version()
                if (time() - self.last_send) > self.max_seconds_idle or self.latency == 1 << 32:
                    await self.send_request('server.banner')
                retry_delay = default_delay
            except (asyncio.TimeoutError, OSError):
                await self.close()
                retry_delay = min(60, retry_delay * 2)
                log.warning("Wallet server timeout (retry in %s seconds): %s:%d", retry_delay, *self.server)
            await asyncio.sleep(retry_delay)

    def ensure_server_version(self, required='1.2'):
        return self.send_request('server.version', [__version__, required])

    async def create_connection(self, timeout=6):
        connector = Connector(lambda: self, *self.server)
        await asyncio.wait_for(connector.create_connection(), timeout=timeout)

    async def handle_request(self, request):
        controller = self.network.subscription_controllers[request.method]
        controller.add(request.args)

    def connection_lost(self, exc):
        super().connection_lost(exc)
        self.latency = 1 << 32
        self._on_disconnect_controller.add(True)


class BaseNetwork:

    def __init__(self, ledger):
        self.switch_event = asyncio.Event()
        self.config = ledger.config
        self.session_pool = SessionPool(network=self, timeout=self.config.get('connect_timeout', 6))
        self.client: Optional[ClientSession] = None
        self.running = False
        self.remote_height: int = 0

        self._on_connected_controller = StreamController()
        self.on_connected = self._on_connected_controller.stream

        self._on_header_controller = StreamController(merge_repeated_events=True)
        self.on_header = self._on_header_controller.stream

        self._on_status_controller = StreamController(merge_repeated_events=True)
        self.on_status = self._on_status_controller.stream

        self.subscription_controllers = {
            'blockchain.headers.subscribe': self._on_header_controller,
            'blockchain.address.subscribe': self._on_status_controller,
        }

    async def start(self):
        self.running = True
        self.session_pool.start(self.config['default_servers'])
        self.on_header.listen(self._update_remote_height)
        while self.running:
            try:
                self.client = await self.session_pool.wait_for_fastest_session()
                self._update_remote_height((await self.subscribe_headers(),))
                log.info("Switching to SPV wallet server: %s:%d", *self.client.server)
                self._on_connected_controller.add(True)
                self.client.on_disconnected.listen(lambda _: self.switch_event.set())
                await self.switch_event.wait()
                self.switch_event.clear()
            except asyncio.CancelledError:
                await self.stop()
                raise
            except asyncio.TimeoutError:
                pass

    async def stop(self):
        self.running = False
        if self.session_pool:
            self.session_pool.stop()
        if self.is_connected:
            disconnected = self.client.on_disconnected.first
            await self.client.close()
            await disconnected

    @property
    def is_connected(self):
        return self.client and not self.client.is_closing()

    def rpc(self, list_or_method, args):
        if self.is_connected:
            fastest = self.session_pool.fastest_session
            if self.client != fastest:
                self.switch_event.set()
            return self.client.send_request(list_or_method, args)
        else:
            raise ConnectionError("Attempting to send rpc request when connection is not available.")

    def _update_remote_height(self, header_args):
        self.remote_height = header_args[0]["height"]

    def broadcast(self, raw_transaction):
        return self.rpc('blockchain.transaction.broadcast', [raw_transaction])

    def get_history(self, address):
        return self.rpc('blockchain.address.get_history', [address])

    def get_transaction(self, tx_hash):
        return self.rpc('blockchain.transaction.get', [tx_hash])

    def get_transaction_height(self, tx_hash):
        return self.rpc('blockchain.transaction.get_height', [tx_hash])

    def get_merkle(self, tx_hash, height):
        return self.rpc('blockchain.transaction.get_merkle', [tx_hash, height])

    def get_headers(self, height, count=10000):
        return self.rpc('blockchain.block.headers', [height, count])

    def subscribe_headers(self):
        return self.rpc('blockchain.headers.subscribe', [True])

    def subscribe_address(self, address):
        return self.rpc('blockchain.address.subscribe', [address])


class SessionPool:

    def __init__(self, network: BaseNetwork, timeout: float):
        self.network = network
        self.sessions: Dict[ClientSession, asyncio.Task] = dict()
        self.timeout = timeout

    @property
    def online(self):
        return any(not session.is_closing() for session in self.sessions)

    @property
    def available_sessions(self):
        return [session for session in self.sessions if session.available]

    @property
    def fastest_session(self):
        if not self.available_sessions:
            return None
        return min([(session.latency, session) for session in self.available_sessions], key=itemgetter(0))[1]

    def start(self, default_servers):
        self.sessions = {
            ClientSession(network=self.network, server=server): None for server in default_servers
        }
        self.ensure_connections()

    def stop(self):
        for session, task in self.sessions.items():
            task.cancel()
            session.abort()
        self.sessions.clear()

    def ensure_connections(self):
        for session, task in list(self.sessions.items()):
            if not task or task.done():
                task = asyncio.create_task(session.ensure_session())
                task.add_done_callback(lambda _: self.ensure_connections())
                self.sessions[session] = task

    async def wait_for_fastest_session(self):
        while True:
            fastest = self.fastest_session
            if fastest:
                return fastest
            else:
                await asyncio.sleep(0.5)
