import logging
import asyncio
from asyncio import CancelledError
from itertools import cycle

from aiorpcx import ClientSession as BaseClientSession

from torba import __version__
from torba.stream import StreamController

log = logging.getLogger(__name__)


class ClientSession(BaseClientSession):

    def __init__(self, *args, network, **kwargs):
        self.network = network
        super().__init__(*args, **kwargs)
        self._on_disconnect_controller = StreamController()
        self.on_disconnected = self._on_disconnect_controller.stream
        self.bw_limit = self.framer.max_size = self.max_errors = 1 << 32

    async def handle_request(self, request):
        controller = self.network.subscription_controllers[request.method]
        controller.add(request.args)

    def connection_lost(self, exc):
        super().connection_lost(exc)
        self._on_disconnect_controller.add(True)


class BaseNetwork:

    def __init__(self, ledger):
        self.config = ledger.config
        self.client: ClientSession = None
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
        delay = 0.0
        for server in cycle(self.config['default_servers']):
            connection_string = '{}:{}'.format(*server)
            self.client = ClientSession(*server, network=self)
            try:
                await self.client.create_connection()
                await self.ensure_server_version()
                log.info("Successfully connected to SPV wallet server: %s", connection_string)
                self._on_connected_controller.add(True)
                delay = 0.0
                await self.client.on_disconnected.first
            except (Exception, CancelledError):  # pylint: disable=broad-except
                log.exception("Connecting to %s raised an exception:", connection_string)
            if not self.running:
                return
            elif self.client:
                await self.client.close()
                self.client.connection.cancel_pending_requests()
                await asyncio.sleep(delay)
                delay = min(delay + 1.0, 10.0)

    async def stop(self):
        self.running = False
        if self.is_connected:
            disconnected = self.client.on_disconnected.first
            await self.client.close()
            await disconnected

    @property
    def is_connected(self):
        return self.client is not None and not self.client.is_closing()

    def rpc(self, list_or_method, *args):
        if self.is_connected:
            return self.client.send_request(list_or_method, args)
        else:
            raise ConnectionError("Attempting to send rpc request when connection is not available.")

    def ensure_server_version(self, required='1.2'):
        return self.rpc('server.version', __version__, required)

    def broadcast(self, raw_transaction):
        return self.rpc('blockchain.transaction.broadcast', raw_transaction)

    def get_history(self, address):
        return self.rpc('blockchain.address.get_history', address)

    def get_transaction(self, tx_hash):
        return self.rpc('blockchain.transaction.get', tx_hash)

    def get_merkle(self, tx_hash, height):
        return self.rpc('blockchain.transaction.get_merkle', tx_hash, height)

    def get_headers(self, height, count=10000):
        return self.rpc('blockchain.block.headers', height, count)

    def subscribe_headers(self):
        return self.rpc('blockchain.headers.subscribe', True)

    def subscribe_address(self, address):
        return self.rpc('blockchain.address.subscribe', address)
