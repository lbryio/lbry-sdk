import logging
import asyncio
from typing import Dict
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
        return not self.is_closing() and self._can_send.is_set()

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
        except asyncio.TimeoutError:
            self.abort()
            raise

    async def ensure_session(self):
        # Handles reconnecting and maintaining a session alive
        # TODO: change to 'ping' on newer protocol (above 1.2)
        retry_delay = 1.0
        while True:
            try:
                if self.is_closing():
                    await self.create_connection(self.timeout)
                    await self.ensure_server_version()
                if (time() - self.last_send) > self.max_seconds_idle:
                    await self.send_request('server.banner')
                retry_delay = 1.0
            except asyncio.TimeoutError:
                log.warning("Wallet server timeout (retry in %s seconds): %s:%d", retry_delay, *self.server)
                retry_delay = max(60, retry_delay * 2)
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
        self.config = ledger.config
        self.client: ClientSession = None
        self.session_pool: SessionPool = None
        self.running = False
        self.remote_height: int = 0

        self._on_connected_controller = StreamController()
        self.on_connected = self._on_connected_controller.stream

        self._on_header_controller = StreamController()
        self.on_header = self._on_header_controller.stream

        self._on_status_controller = StreamController()
        self.on_status = self._on_status_controller.stream

        self.subscription_controllers = {
            'blockchain.headers.subscribe': self._on_header_controller,
            'blockchain.address.subscribe': self._on_status_controller,
        }

    async def start(self):
        self.running = True
        connect_timeout = self.config.get('connect_timeout', 6)
        self.session_pool = SessionPool(network=self, timeout=connect_timeout)
        self.session_pool.start(self.config['default_servers'])
        self.on_header.listen(self._update_remote_height)
        while self.running:
            try:
                self.client = await self.session_pool.wait_for_fastest_session()
                self._update_remote_height((await self.subscribe_headers(),))
                log.info("Successfully connected to SPV wallet server: %s:%d", *self.client.server)
                self._on_connected_controller.add(True)
                await self.client.on_disconnected.first
            except asyncio.CancelledError:
                await self.stop()
                raise
            except asyncio.TimeoutError:
                pass
            except Exception:  # pylint: disable=broad-except
                log.exception("Exception while trying to find a server!")

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
        return self.session_pool.online

    async def rpc(self, list_or_method, args):
        if self.is_connected:
            await self.session_pool.wait_for_fastest_session()
            return await self.session_pool.fastest_session.send_request(list_or_method, args)
        else:
            raise ConnectionError("Attempting to send rpc request when connection is not available.")

    async def probe_session(self, session: ClientSession):
        await session.send_request('server.banner')
        return session

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
        return self.client.send_request('blockchain.headers.subscribe', [True])

    def subscribe_address(self, address):
        return self.client.send_request('blockchain.address.subscribe', [address])


class SessionPool:

    def __init__(self, network: BaseNetwork, timeout: float):
        self.network = network
        self.sessions: Dict[ClientSession, asyncio.Task] = dict()
        self.maintain_connections_task = None
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
        return min([(session.latency, session) for session in self.available_sessions])[1]

    def start(self, default_servers):
        for server in default_servers:
            session = ClientSession(network=self.network, server=server)
            self.sessions[session] = asyncio.create_task(session.ensure_session())
        self.maintain_connections_task = asyncio.create_task(self.ensure_connections())

    def stop(self):
        if self.maintain_connections_task:
            self.maintain_connections_task.cancel()
            self.maintain_connections_task = None
        for session, maintenance_task in self.sessions.items():
            maintenance_task.cancel()
            if not session.is_closing():
                session.abort()
        self.sessions.clear()

    async def ensure_connections(self):
        while True:
            log.info("Checking conns")
            for session, task in list(self.sessions.items()):
                if task.done():
                    self.sessions[session] = asyncio.create_task(session.ensure_session())
            await asyncio.wait(self.sessions.items(), timeout=10)

    async def wait_for_fastest_session(self):
        while True:
            fastest = self.fastest_session
            if fastest:
                return fastest
            else:
                await asyncio.sleep(0.5)
