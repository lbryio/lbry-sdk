import logging
import asyncio
from operator import itemgetter
from typing import Dict, Optional, Tuple
from time import perf_counter

from torba.rpc import RPCSession as BaseClientSession, Connector, RPCError

from torba import __version__
from torba.stream import StreamController

log = logging.getLogger(__name__)


class ClientSession(BaseClientSession):
    def __init__(self, *args, network, server, timeout=30, on_connect_callback=None, **kwargs):
        self.network = network
        self.server = server
        super().__init__(*args, **kwargs)
        self._on_disconnect_controller = StreamController()
        self.on_disconnected = self._on_disconnect_controller.stream
        self.framer.max_size = self.max_errors = 1 << 32
        self.bw_limit = -1
        self.timeout = timeout
        self.max_seconds_idle = timeout * 2
        self.response_time: Optional[float] = None
        self.connection_latency: Optional[float] = None
        self._response_samples = 0
        self.pending_amount = 0
        self._on_connect_cb = on_connect_callback or (lambda: None)
        self.trigger_urgent_reconnect = asyncio.Event()
        self._semaphore = asyncio.Semaphore(int(self.timeout))

    @property
    def available(self):
        return not self.is_closing() and self._can_send.is_set() and self.response_time is not None

    @property
    def server_address_and_port(self) -> Optional[Tuple[str, int]]:
        if not self.transport:
            return None
        return self.transport.get_extra_info('peername')

    async def send_timed_server_version_request(self, args=(), timeout=None):
        timeout = timeout or self.timeout
        log.debug("send version request to %s:%i", *self.server)
        start = perf_counter()
        result = await asyncio.wait_for(
            super().send_request('server.version', args), timeout=timeout
        )
        current_response_time = perf_counter() - start
        response_sum = (self.response_time or 0) * self._response_samples + current_response_time
        self.response_time = response_sum / (self._response_samples + 1)
        self._response_samples += 1
        return result

    async def send_request(self, method, args=()):
        self.pending_amount += 1
        async with self._semaphore:
            return await self._send_request(method, args)

    async def _send_request(self, method, args=()):
        log.debug("send %s to %s:%i", method, *self.server)
        try:
            if method == 'server.version':
                reply = await self.send_timed_server_version_request(args, self.timeout)
            else:
                reply = await asyncio.wait_for(
                    super().send_request(method, args), timeout=self.timeout
                )
            log.debug("got reply for %s from %s:%i", method, *self.server)
            return reply
        except RPCError as e:
            log.warning("Wallet server (%s:%i) returned an error. Code: %s Message: %s",
                        *self.server, *e.args)
            raise e
        except ConnectionError:
            log.warning("connection to %s:%i lost", *self.server)
            self.synchronous_close()
            raise asyncio.CancelledError(f"connection to {self.server[0]}:{self.server[1]} lost")
        except asyncio.TimeoutError:
            log.info("timeout sending %s to %s:%i", method, *self.server)
            raise
        except asyncio.CancelledError:
            log.info("cancelled sending %s to %s:%i", method, *self.server)
            self.synchronous_close()
            raise
        finally:
            self.pending_amount -= 1

    async def ensure_session(self):
        # Handles reconnecting and maintaining a session alive
        # TODO: change to 'ping' on newer protocol (above 1.2)
        retry_delay = default_delay = 1.0
        while True:
            try:
                if self.is_closing():
                    await self.create_connection(self.timeout)
                    await self.ensure_server_version()
                    self._on_connect_cb()
                if (perf_counter() - self.last_send) > self.max_seconds_idle or self.response_time is None:
                    await self.ensure_server_version()
                retry_delay = default_delay
            except (asyncio.TimeoutError, OSError):
                await self.close()
                retry_delay = min(60, retry_delay * 2)
                log.debug("Wallet server timeout (retry in %s seconds): %s:%d", retry_delay, *self.server)
            try:
                await asyncio.wait_for(self.trigger_urgent_reconnect.wait(), timeout=retry_delay)
            except asyncio.TimeoutError:
                pass
            finally:
                self.trigger_urgent_reconnect.clear()

    async def ensure_server_version(self, required='1.2', timeout=3):
        return await asyncio.wait_for(
            self.send_request('server.version', [__version__, required]), timeout=timeout
        )

    async def create_connection(self, timeout=6):
        connector = Connector(lambda: self, *self.server)
        start = perf_counter()
        await asyncio.wait_for(connector.create_connection(), timeout=timeout)
        self.connection_latency = perf_counter() - start

    async def handle_request(self, request):
        controller = self.network.subscription_controllers[request.method]
        controller.add(request.args)

    def connection_lost(self, exc):
        log.debug("Connection lost: %s:%d", *self.server)
        super().connection_lost(exc)
        self.response_time = None
        self.connection_latency = None
        self._response_samples = 0
        self.pending_amount = 0
        self._on_disconnect_controller.add(True)


class BaseNetwork:

    def __init__(self, ledger):
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

    async def switch_to_fastest(self):
        try:
            client = await asyncio.wait_for(self.session_pool.wait_for_fastest_session(), 30)
        except asyncio.TimeoutError:
            if self.client:
                await self.client.close()
            self.client = None
            for session in self.session_pool.sessions:
                session.synchronous_close()
            log.warning("not connected to any wallet servers")
            return
        current_client = self.client
        self.client = client
        log.info("Switching to SPV wallet server: %s:%d", *self.client.server)
        self._on_connected_controller.add(True)
        try:
            self._update_remote_height((await self.subscribe_headers(),))
            log.info("Subscribed to headers: %s:%d", *self.client.server)
        except asyncio.TimeoutError:
            if self.client:
                await self.client.close()
                self.client = current_client
            return
        self.session_pool.new_connection_event.clear()
        return await self.session_pool.new_connection_event.wait()

    async def start(self):
        self.running = True
        self.session_pool.start(self.config['default_servers'])
        self.on_header.listen(self._update_remote_height)
        while self.running:
            await self.switch_to_fastest()

    async def stop(self):
        self.running = False
        self.session_pool.stop()

    @property
    def is_connected(self):
        return self.client and not self.client.is_closing()

    def rpc(self, list_or_method, args, session=None):
        session = session or self.session_pool.fastest_session
        if session:
            return session.send_request(list_or_method, args)
        else:
            self.session_pool.trigger_nodelay_connect()
            raise ConnectionError("Attempting to send rpc request when connection is not available.")

    async def retriable_call(self, function, *args, **kwargs):
        while self.running:
            if not self.is_connected:
                log.warning("Wallet server unavailable, waiting for it to come back and retry.")
                await self.on_connected.first
            await self.session_pool.wait_for_fastest_session()
            try:
                return await function(*args, **kwargs)
            except asyncio.TimeoutError:
                log.warning("Wallet server call timed out, retrying.")
            except ConnectionError:
                pass
        raise asyncio.CancelledError()  # if we got here, we are shutting down

    def _update_remote_height(self, header_args):
        self.remote_height = header_args[0]["height"]

    def get_transaction(self, tx_hash):
        return self.rpc('blockchain.transaction.get', [tx_hash])

    def get_transaction_height(self, tx_hash):
        return self.rpc('blockchain.transaction.get_height', [tx_hash])

    def get_merkle(self, tx_hash, height):
        return self.rpc('blockchain.transaction.get_merkle', [tx_hash, height])

    def get_headers(self, height, count=10000):
        return self.rpc('blockchain.block.headers', [height, count])

    #  --- Subscribes, history and broadcasts are always aimed towards the master client directly
    def get_history(self, address):
        return self.rpc('blockchain.address.get_history', [address], session=self.client)

    def broadcast(self, raw_transaction):
        return self.rpc('blockchain.transaction.broadcast', [raw_transaction], session=self.client)

    def subscribe_headers(self):
        return self.rpc('blockchain.headers.subscribe', [True], session=self.client)

    async def subscribe_address(self, address):
        try:
            return await self.rpc('blockchain.address.subscribe', [address], session=self.client)
        except asyncio.TimeoutError:
            # abort and cancel, we cant lose a subscription, it will happen again on reconnect
            self.client.abort()
            raise asyncio.CancelledError()


class SessionPool:

    def __init__(self, network: BaseNetwork, timeout: float):
        self.network = network
        self.sessions: Dict[ClientSession, Optional[asyncio.Task]] = dict()
        self.timeout = timeout
        self.new_connection_event = asyncio.Event()

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
        return min(
            [((session.response_time + session.connection_latency) * (session.pending_amount + 1), session)
             for session in self.available_sessions],
            key=itemgetter(0)
        )[1]

    def _get_session_connect_callback(self, session: ClientSession):
        loop = asyncio.get_event_loop()

        def callback():
            duplicate_connections = [
                s for s in self.sessions
                if s is not session and s.server_address_and_port == session.server_address_and_port
            ]
            already_connected = None if not duplicate_connections else duplicate_connections[0]
            if already_connected:
                self.sessions.pop(session).cancel()
                session.synchronous_close()
                log.debug("wallet server %s resolves to the same server as %s, rechecking in an hour",
                          session.server[0], already_connected.server[0])
                loop.call_later(3600, self._connect_session, session.server)
                return
            self.new_connection_event.set()
            log.info("connected to %s:%i", *session.server)

        return callback

    def _connect_session(self, server: Tuple[str, int]):
        session = None
        for s in self.sessions:
            if s.server == server:
                session = s
                break
        if not session:
            session = ClientSession(
                network=self.network, server=server
            )
            session._on_connect_cb = self._get_session_connect_callback(session)
        task = self.sessions.get(session, None)
        if not task or task.done():
            task = asyncio.create_task(session.ensure_session())
            task.add_done_callback(lambda _: self.ensure_connections())
            self.sessions[session] = task

    def start(self, default_servers):
        for server in default_servers:
            self._connect_session(server)

    def stop(self):
        for task in self.sessions.values():
            task.cancel()
        self.sessions.clear()

    def ensure_connections(self):
        for session in self.sessions:
            self._connect_session(session.server)

    def trigger_nodelay_connect(self):
        # used when other parts of the system sees we might have internet back
        # bypasses the retry interval
        for session in self.sessions:
            session.trigger_urgent_reconnect.set()

    async def wait_for_fastest_session(self):
        while not self.fastest_session:
            self.trigger_nodelay_connect()
            self.new_connection_event.clear()
            await self.new_connection_event.wait()
        return self.fastest_session
