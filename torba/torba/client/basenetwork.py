import logging
import asyncio
from asyncio import CancelledError
from time import time
from typing import List

from torba.rpc import RPCSession as BaseClientSession, Connector, RPCError

from torba import __version__
from torba.stream import StreamController

log = logging.getLogger(__name__)


class ClientSession(BaseClientSession):

    def __init__(self, *args, network, server, **kwargs):
        self.network = network
        self.server = server
        super().__init__(*args, **kwargs)
        self._on_disconnect_controller = StreamController()
        self.on_disconnected = self._on_disconnect_controller.stream
        self.bw_limit = self.framer.max_size = self.max_errors = 1 << 32
        self.max_seconds_idle = 60
        self.ping_task = None

    async def send_request(self, method, args=()):
        try:
            return await super().send_request(method, args)
        except RPCError as e:
            log.warning("Wallet server returned an error. Code: %s Message: %s", *e.args)
            raise e

    async def ping_forever(self):
        # TODO: change to 'ping' on newer protocol (above 1.2)
        while not self.is_closing():
            if (time() - self.last_send) > self.max_seconds_idle:
                await self.send_request('server.banner')
            await asyncio.sleep(self.max_seconds_idle//3)

    async def create_connection(self, timeout=6):
        connector = Connector(lambda: self, *self.server)
        await asyncio.wait_for(connector.create_connection(), timeout=timeout)
        self.ping_task = asyncio.create_task(self.ping_forever())

    async def handle_request(self, request):
        controller = self.network.subscription_controllers[request.method]
        controller.add(request.args)

    def connection_lost(self, exc):
        super().connection_lost(exc)
        self._on_disconnect_controller.add(True)
        if self.ping_task:
            self.ping_task.cancel()


class BaseNetwork:

    def __init__(self, ledger):
        self.config = ledger.config
        self.client: ClientSession = None
        self.session_pool: SessionPool = None
        self.running = False

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
        while True:
            try:
                self.client = await self.pick_fastest_session()
                if self.is_connected:
                    await self.ensure_server_version()
                    log.info("Successfully connected to SPV wallet server: %s:%d", *self.client.server)
                    self._on_connected_controller.add(True)
                    await self.client.on_disconnected.first
            except CancelledError:
                self.running = False
            except asyncio.TimeoutError:
                log.warning("Timed out while trying to find a server!")
            except Exception:  # pylint: disable=broad-except
                log.exception("Exception while trying to find a server!")
            if not self.running:
                return
            elif self.client:
                await self.client.close()
                self.client.connection.cancel_pending_requests()

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
        return self.client is not None and not self.client.is_closing()

    def rpc(self, list_or_method, args):
        if self.is_connected:
            return self.client.send_request(list_or_method, args)
        else:
            raise ConnectionError("Attempting to send rpc request when connection is not available.")

    async def pick_fastest_session(self):
        sessions = await self.session_pool.get_online_sessions()
        done, pending = await asyncio.wait([
            self.probe_session(session)
            for session in sessions if not session.is_closing()
        ], return_when='FIRST_COMPLETED')
        for task in pending:
            task.cancel()
        for session in done:
            return await session

    async def probe_session(self, session: ClientSession):
        await session.send_request('server.banner')
        return session

    def ensure_server_version(self, required='1.2'):
        return self.rpc('server.version', [__version__, required])

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
        self.sessions: List[ClientSession] = []
        self._dead_servers: List[ClientSession] = []
        self.maintain_connections_task = None
        self.timeout = timeout
        # triggered when the master server is out, to speed up reconnect
        self._lost_master = asyncio.Event()

    @property
    def online(self):
        for session in self.sessions:
            if not session.is_closing():
                return True
        return False

    def start(self, default_servers):
        self.sessions = [
            ClientSession(network=self.network, server=server)
            for server in default_servers
        ]
        self.maintain_connections_task = asyncio.create_task(self.ensure_connections())

    def stop(self):
        if self.maintain_connections_task:
            self.maintain_connections_task.cancel()
        for session in self.sessions:
            if not session.is_closing():
                session.abort()
        self.sessions, self._dead_servers, self.maintain_connections_task = [], [], None

    async def ensure_connections(self):
        while True:
            await asyncio.gather(*[
                self.ensure_connection(session)
                for session in self.sessions
            ], return_exceptions=True)
            await asyncio.wait([asyncio.sleep(3), self._lost_master.wait()], return_when='FIRST_COMPLETED')
            self._lost_master.clear()
            if not self.sessions:
                self.sessions.extend(self._dead_servers)
                self._dead_servers = []

    async def ensure_connection(self, session):
        if not session.is_closing():
            return
        try:
            return await session.create_connection(self.timeout)
        except asyncio.TimeoutError:
            log.warning("Timeout connecting to %s:%d", *session.server)
        except asyncio.CancelledError:  # pylint: disable=try-except-raise
            raise
        except Exception as err:  # pylint: disable=broad-except
            if 'Connect call failed' in str(err):
                log.warning("Could not connect to %s:%d", *session.server)
            else:
                log.exception("Connecting to %s:%d raised an exception:", *session.server)
        self._dead_servers.append(session)
        self.sessions.remove(session)

    async def get_online_sessions(self):
        self._lost_master.set()
        while not self.online:
            await asyncio.sleep(0.1)
        return self.sessions
