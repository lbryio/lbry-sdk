import logging
import asyncio
import json
import socket
import random
from time import perf_counter
from collections import defaultdict
from typing import Dict, Optional, Tuple
import aiohttp

from lbry import __version__
from lbry.utils import resolve_host
from lbry.error import IncompatibleWalletServerError
from lbry.wallet.rpc import RPCSession as BaseClientSession, Connector, RPCError, ProtocolError
from lbry.wallet.stream import StreamController
from lbry.wallet.server.udp import SPVStatusClientProtocol, SPVPong
from lbry.conf import KnownHubsList

log = logging.getLogger(__name__)


class ClientSession(BaseClientSession):
    def __init__(self, *args, network: 'Network', server, timeout=30, **kwargs):
        self.network = network
        self.server = server
        super().__init__(*args, **kwargs)
        self.framer.max_size = self.max_errors = 1 << 32
        self.timeout = timeout
        self.max_seconds_idle = timeout * 2
        self.response_time: Optional[float] = None
        self.connection_latency: Optional[float] = None
        self._response_samples = 0
        self.pending_amount = 0

    @property
    def available(self):
        return not self.is_closing() and self.response_time is not None

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
        log.debug("send %s%s to %s:%i (%i timeout)", method, tuple(args), self.server[0], self.server[1], self.timeout)
        try:
            if method == 'server.version':
                return await self.send_timed_server_version_request(args, self.timeout)
            request = asyncio.ensure_future(super().send_request(method, args))
            while not request.done():
                done, pending = await asyncio.wait([request], timeout=self.timeout)
                if pending:
                    log.debug("Time since last packet: %s", perf_counter() - self.last_packet_received)
                    if (perf_counter() - self.last_packet_received) < self.timeout:
                        continue
                    log.warning("timeout sending %s to %s:%i", method, *self.server)
                    raise asyncio.TimeoutError
                if done:
                    try:
                        return request.result()
                    except ConnectionResetError:
                        log.error(
                            "wallet server (%s) reset connection upon our %s request, json of %i args is %i bytes",
                            self.server[0], method, len(args), len(json.dumps(args))
                        )
                        raise
        except (RPCError, ProtocolError) as e:
            log.warning("Wallet server (%s:%i) returned an error. Code: %s Message: %s",
                        *self.server, *e.args)
            raise e
        except ConnectionError:
            log.warning("connection to %s:%i lost", *self.server)
            self.synchronous_close()
            raise
        except asyncio.CancelledError:
            log.warning("cancelled sending %s to %s:%i", method, *self.server)
            # self.synchronous_close()
            raise
        finally:
            self.pending_amount -= 1

    async def ensure_server_version(self, required=None, timeout=3):
        required = required or self.network.PROTOCOL_VERSION
        response = await asyncio.wait_for(
            self.send_request('server.version', [__version__, required]), timeout=timeout
        )
        if tuple(int(piece) for piece in response[0].split(".")) < self.network.MINIMUM_REQUIRED:
            raise IncompatibleWalletServerError(*self.server)
        return response

    async def keepalive_loop(self, timeout=3, max_idle=60):
        try:
            while True:
                now = perf_counter()
                if min(self.last_send, self.last_packet_received) + max_idle < now:
                    await asyncio.wait_for(
                        self.send_request('server.ping', []), timeout=timeout
                    )
                else:
                    await asyncio.sleep(max(0, max_idle - (now - self.last_send)))
        except Exception as err:
            if isinstance(err, asyncio.CancelledError):
                log.warning("closing connection to %s:%i", *self.server)
            else:
                log.exception("lost connection to spv")
        finally:
            if not self.is_closing():
                self._close()

    async def create_connection(self, timeout=6):
        connector = Connector(lambda: self, *self.server)
        start = perf_counter()
        await asyncio.wait_for(connector.create_connection(), timeout=timeout)
        self.connection_latency = perf_counter() - start

    async def handle_request(self, request):
        controller = self.network.subscription_controllers[request.method]
        controller.add(request.args)

    def connection_lost(self, exc):
        log.warning("Connection lost: %s:%d", *self.server)
        super().connection_lost(exc)
        self.response_time = None
        self.connection_latency = None
        self._response_samples = 0
        # self._on_disconnect_controller.add(True)
        if self.network:
            self.network.disconnect()


class Network:

    PROTOCOL_VERSION = __version__
    MINIMUM_REQUIRED = (0, 65, 0)

    def __init__(self, ledger):
        self.ledger = ledger
        self.client: Optional[ClientSession] = None
        self.server_features = None
        # self._switch_task: Optional[asyncio.Task] = None
        self.running = False
        self.remote_height: int = 0
        self._concurrency = asyncio.Semaphore(16)

        self._on_connected_controller = StreamController()
        self.on_connected = self._on_connected_controller.stream

        self._on_header_controller = StreamController(merge_repeated_events=True)
        self.on_header = self._on_header_controller.stream

        self._on_status_controller = StreamController(merge_repeated_events=True)
        self.on_status = self._on_status_controller.stream

        self._on_hub_controller = StreamController(merge_repeated_events=True)
        self.on_hub = self._on_hub_controller.stream

        self.subscription_controllers = {
            'blockchain.headers.subscribe': self._on_header_controller,
            'blockchain.address.subscribe': self._on_status_controller,
            'blockchain.peers.subscribe': self._on_hub_controller,
        }

        self.aiohttp_session: Optional[aiohttp.ClientSession] = None
        self._urgent_need_reconnect = asyncio.Event()
        self._loop_task: Optional[asyncio.Task] = None
        self._keepalive_task: Optional[asyncio.Task] = None

    @property
    def config(self):
        return self.ledger.config

    @property
    def known_hubs(self):
        return self.config.get('known_hubs', KnownHubsList())

    def disconnect(self):
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
        self._keepalive_task = None

    async def start(self):
        if not self.running:
            self.running = True
            self.aiohttp_session = aiohttp.ClientSession()
            self.on_header.listen(self._update_remote_height)
            self.on_hub.listen(self._update_hubs)
            self._loop_task = asyncio.create_task(self.network_loop())
            self._urgent_need_reconnect.set()

        def loop_task_done_callback(f):
            try:
                f.result()
            except Exception:
                if self.running:
                    log.exception("wallet server connection loop crashed")

        self._loop_task.add_done_callback(loop_task_done_callback)

    async def resolve_spv_dns(self):
        hostname_to_ip = {}
        ip_to_hostnames = defaultdict(list)

        async def resolve_spv(server, port):
            try:
                server_addr = await resolve_host(server, port, 'udp')
                hostname_to_ip[server] = (server_addr, port)
                ip_to_hostnames[(server_addr, port)].append(server)
            except socket.error:
                log.warning("error looking up dns for spv server %s:%i", server, port)
            except Exception:
                log.exception("error looking up dns for spv server %s:%i", server, port)

        # accumulate the dns results
        hubs = self.known_hubs if self.known_hubs else self.config['default_servers']
        await asyncio.gather(*(resolve_spv(server, port) for (server, port) in hubs))
        return hostname_to_ip, ip_to_hostnames

    async def get_n_fastest_spvs(self, timeout=3.0) -> Dict[Tuple[str, int], Optional[SPVPong]]:
        loop = asyncio.get_event_loop()
        pong_responses = asyncio.Queue()
        connection = SPVStatusClientProtocol(pong_responses)
        sent_ping_timestamps = {}
        _, ip_to_hostnames = await self.resolve_spv_dns()
        n = len(ip_to_hostnames)
        log.info("%i possible spv servers to try (%i urls in config)", n, len(self.config['default_servers']))
        pongs = {}
        try:
            await loop.create_datagram_endpoint(lambda: connection, ('0.0.0.0', 0))
            # could raise OSError if it cant bind
            start = perf_counter()
            for server in ip_to_hostnames:
                connection.ping(server)
                sent_ping_timestamps[server] = perf_counter()
            while len(pongs) < n:
                (remote, ts), pong = await asyncio.wait_for(pong_responses.get(), timeout - (perf_counter() - start))
                latency = ts - start
                log.info("%s:%i has latency of %sms (available: %s, height: %i)",
                         '/'.join(ip_to_hostnames[remote]), remote[1], round(latency * 1000, 2),
                         pong.available, pong.height)

                if pong.available:
                    pongs[(ip_to_hostnames[remote][0], remote[1])] = pong
            return pongs
        except asyncio.TimeoutError:
            if pongs:
                log.info("%i/%i probed spv servers are accepting connections", len(pongs), len(ip_to_hostnames))
                return pongs
            else:
                log.warning("%i spv status probes failed, retrying later. servers tried: %s",
                            len(sent_ping_timestamps),
                            ', '.join('/'.join(hosts) + f' ({ip})' for ip, hosts in ip_to_hostnames.items()))
                random_server = random.choice(list(ip_to_hostnames.keys()))
                host, port = random_server
                log.warning("trying fallback to randomly selected spv: %s:%i", host, port)
                return {(host, port): None}
        finally:
            connection.close()

    async def connect_to_fastest(self) -> Optional[ClientSession]:
        fastest_spvs = await self.get_n_fastest_spvs()
        for (host, port) in fastest_spvs:
            client = ClientSession(network=self, server=(host, port))
            try:
                await client.create_connection()
                log.warning("Connected to spv server %s:%i", host, port)
                await client.ensure_server_version()
                return client
            except (asyncio.TimeoutError, ConnectionError, OSError, IncompatibleWalletServerError, RPCError):
                log.warning("Connecting to %s:%d failed", host, port)
                client._close()
        return

    async def network_loop(self):
        sleep_delay = 30
        while self.running:
            await asyncio.wait(
                [asyncio.sleep(30), self._urgent_need_reconnect.wait()], return_when=asyncio.FIRST_COMPLETED
            )
            if self._urgent_need_reconnect.is_set():
                sleep_delay = 30
            self._urgent_need_reconnect.clear()
            if not self.is_connected:
                client = await self.connect_to_fastest()
                if not client:
                    log.warning("failed to connect to any spv servers, retrying later")
                    sleep_delay *= 2
                    sleep_delay = min(sleep_delay, 300)
                    continue
                log.debug("get spv server features %s:%i", *client.server)
                features = await client.send_request('server.features', [])
                self.client, self.server_features = client, features
                log.debug("discover other hubs %s:%i", *client.server)
                self._update_hubs(await client.send_request('server.peers.subscribe', []))
                log.info("subscribe to headers %s:%i", *client.server)
                self._update_remote_height((await self.subscribe_headers(),))
                self._on_connected_controller.add(True)
                server_str = "%s:%i" % client.server
                log.info("maintaining connection to spv server %s", server_str)
                self._keepalive_task = asyncio.create_task(self.client.keepalive_loop())
                try:
                    if not self._urgent_need_reconnect.is_set():
                        await asyncio.wait(
                            [self._keepalive_task, self._urgent_need_reconnect.wait()],
                            return_when=asyncio.FIRST_COMPLETED
                        )
                    else:
                        await self._keepalive_task
                    if self._urgent_need_reconnect.is_set():
                        log.warning("urgent reconnect needed")
                        self._urgent_need_reconnect.clear()
                    if self._keepalive_task and not self._keepalive_task.done():
                        self._keepalive_task.cancel()
                except asyncio.CancelledError:
                    pass
                finally:
                    self._keepalive_task = None
                    self.client = None
                    self.server_features = None
                    log.warning("connection lost to %s", server_str)
        log.info("network loop finished")

    async def stop(self):
        self.running = False
        self.disconnect()
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
        self._loop_task = None
        if self.aiohttp_session:
            await self.aiohttp_session.close()
            self.aiohttp_session = None

    @property
    def is_connected(self):
        return self.client and not self.client.is_closing()

    def rpc(self, list_or_method, args, restricted=True, session: Optional[ClientSession] = None):
        if session or self.is_connected:
            session = session or self.client
            return session.send_request(list_or_method, args)
        else:
            self._urgent_need_reconnect.set()
            raise ConnectionError("Attempting to send rpc request when connection is not available.")

    async def retriable_call(self, function, *args, **kwargs):
        async with self._concurrency:
            while self.running:
                if not self.is_connected:
                    log.warning("Wallet server unavailable, waiting for it to come back and retry.")
                    self._urgent_need_reconnect.set()
                    await self.on_connected.first
                try:
                    return await function(*args, **kwargs)
                except asyncio.TimeoutError:
                    log.warning("Wallet server call timed out, retrying.")
                except ConnectionError:
                    log.warning("connection error")

        raise asyncio.CancelledError()  # if we got here, we are shutting down

    def _update_remote_height(self, header_args):
        self.remote_height = header_args[0]["height"]

    def _update_hubs(self, hubs):
        if hubs:
            try:
                if self.known_hubs.add_hubs(hubs):
                    self.known_hubs.save()
            except Exception:
                log.exception("could not add hubs: %s", hubs)

    def get_transaction(self, tx_hash, known_height=None):
        # use any server if its old, otherwise restrict to who gave us the history
        restricted = known_height in (None, -1, 0) or 0 > known_height > self.remote_height - 10
        return self.rpc('blockchain.transaction.get', [tx_hash], restricted)

    def get_transaction_batch(self, txids, restricted=True):
        # use any server if its old, otherwise restrict to who gave us the history
        return self.rpc('blockchain.transaction.get_batch', txids, restricted)

    def get_transaction_and_merkle(self, tx_hash, known_height=None):
        # use any server if its old, otherwise restrict to who gave us the history
        restricted = known_height in (None, -1, 0) or 0 > known_height > self.remote_height - 10
        return self.rpc('blockchain.transaction.info', [tx_hash], restricted)

    def get_transaction_height(self, tx_hash, known_height=None):
        restricted = not known_height or 0 > known_height > self.remote_height - 10
        return self.rpc('blockchain.transaction.get_height', [tx_hash], restricted)

    def get_merkle(self, tx_hash, height):
        restricted = 0 > height > self.remote_height - 10
        return self.rpc('blockchain.transaction.get_merkle', [tx_hash, height], restricted)

    def get_headers(self, height, count=10000, b64=False):
        restricted = height >= self.remote_height - 100
        return self.rpc('blockchain.block.headers', [height, count, 0, b64], restricted)

    #  --- Subscribes, history and broadcasts are always aimed towards the master client directly
    def get_history(self, address):
        return self.rpc('blockchain.address.get_history', [address], True)

    def broadcast(self, raw_transaction):
        return self.rpc('blockchain.transaction.broadcast', [raw_transaction], True)

    def subscribe_headers(self):
        return self.rpc('blockchain.headers.subscribe', [True], True)

    async def subscribe_address(self, address, *addresses):
        addresses = list((address, ) + addresses)
        server_addr_and_port = self.client.server_address_and_port  # on disconnect client will be None
        try:
            return await self.rpc('blockchain.address.subscribe', addresses, True)
        except asyncio.TimeoutError:
            log.warning(
                "timed out subscribing to addresses from %s:%i",
                *server_addr_and_port
            )
            # abort and cancel, we can't lose a subscription, it will happen again on reconnect
            if self.client:
                self.client.abort()
            raise asyncio.CancelledError()

    def unsubscribe_address(self, address):
        return self.rpc('blockchain.address.unsubscribe', [address], True)

    def get_server_features(self):
        return self.rpc('server.features', (), restricted=True)

    def resolve(self, urls, session_override=None):
        return self.rpc('blockchain.claimtrie.resolve', urls, False, session_override)

    def claim_search(self, session_override=None, **kwargs):
        return self.rpc('blockchain.claimtrie.search', kwargs, False, session_override)

    async def new_resolve(self, server, urls):
        message = {"method": "resolve", "params": {"urls": urls, "protobuf": True}}
        async with self.aiohttp_session.post(server, json=message) as r:
            result = await r.json()
            return result['result']

    async def new_claim_search(self, server, **kwargs):
        kwargs['protobuf'] = True
        message = {"method": "claim_search", "params": kwargs}
        async with self.aiohttp_session.post(server, json=message) as r:
            result = await r.json()
            return result['result']

    async def sum_supports(self, server, **kwargs):
        message = {"method": "support_sum", "params": kwargs}
        async with self.aiohttp_session.post(server, json=message) as r:
            result = await r.json()
            return result['result']
