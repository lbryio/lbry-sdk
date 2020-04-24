import os
import ssl
import math
import time
import json
import zlib
import pylru
import base64
import codecs
import typing
import asyncio
import logging
import itertools
import collections

from asyncio import Event, sleep
from collections import defaultdict
from functools import partial

from binascii import hexlify
from pylru import lrucache
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

import lbry
from lbry.wallet.server.block_processor import LBRYBlockProcessor
from lbry.wallet.server.db.writer import LBRYLevelDB
from lbry.wallet.server.db import reader
from lbry.wallet.server.websocket import AdminWebSocket
from lbry.wallet.server.metrics import ServerLoadData, APICallMetrics
from lbry.wallet.server import prometheus
from lbry.wallet.rpc.framing import NewlineFramer
import lbry.wallet.server.version as VERSION

from lbry.wallet.rpc import (
    RPCSession, JSONRPCAutoDetect, JSONRPCConnection,
    handler_invocation, RPCError, Request, JSONRPC
)
from lbry.wallet.server import text
from lbry.wallet.server import util
from lbry.wallet.server.hash import sha256, hash_to_hex_str, hex_str_to_hash, HASHX_LEN, Base58Error
from lbry.wallet.server.daemon import DaemonError
from lbry.wallet.server.peers import PeerManager
if typing.TYPE_CHECKING:
    from lbry.wallet.server.env import Env
    from lbry.wallet.server.mempool import MemPool
    from lbry.wallet.server.daemon import Daemon

BAD_REQUEST = 1
DAEMON_ERROR = 2

log = logging.getLogger(__name__)


def scripthash_to_hashX(scripthash: str) -> bytes:
    try:
        bin_hash = hex_str_to_hash(scripthash)
        if len(bin_hash) == 32:
            return bin_hash[:HASHX_LEN]
    except Exception:
        pass
    raise RPCError(BAD_REQUEST, f'{scripthash} is not a valid script hash')


def non_negative_integer(value) -> int:
    """Return param value it is or can be converted to a non-negative
    integer, otherwise raise an RPCError."""
    try:
        value = int(value)
        if value >= 0:
            return value
    except ValueError:
        pass
    raise RPCError(BAD_REQUEST,
                   f'{value} should be a non-negative integer')


def assert_boolean(value) -> bool:
    """Return param value it is boolean otherwise raise an RPCError."""
    if value in (False, True):
        return value
    raise RPCError(BAD_REQUEST, f'{value} should be a boolean value')


def assert_tx_hash(value: str) -> None:
    """Raise an RPCError if the value is not a valid transaction
    hash."""
    try:
        if len(util.hex_to_bytes(value)) == 32:
            return
    except Exception:
        pass
    raise RPCError(BAD_REQUEST, f'{value} should be a transaction hash')


class Semaphores:
    """For aiorpcX's semaphore handling."""

    def __init__(self, semaphores):
        self.semaphores = semaphores
        self.acquired = []

    async def __aenter__(self):
        for semaphore in self.semaphores:
            await semaphore.acquire()
            self.acquired.append(semaphore)

    async def __aexit__(self, exc_type, exc_value, traceback):
        for semaphore in self.acquired:
            semaphore.release()


class SessionGroup:

    def __init__(self, gid: int):
        self.gid = gid
        # Concurrency per group
        self.semaphore = asyncio.Semaphore(20)


class SessionManager:
    """Holds global state about all sessions."""

    def __init__(self, env: 'Env', db: LBRYLevelDB, bp: LBRYBlockProcessor, daemon: 'Daemon', mempool: 'MemPool',
                 shutdown_event: asyncio.Event):
        env.max_send = max(350000, env.max_send)
        self.env = env
        self.db = db
        self.bp = bp
        self.daemon = daemon
        self.mempool = mempool
        self.peer_mgr = PeerManager(env, db)
        self.shutdown_event = shutdown_event
        self.logger = util.class_logger(__name__, self.__class__.__name__)
        self.servers: typing.Dict[str, asyncio.AbstractServer] = {}
        self.sessions: typing.Set['SessionBase'] = set()
        self.cur_group = SessionGroup(0)
        self.txs_sent = 0
        self.start_time = time.time()
        self.history_cache = pylru.lrucache(256)
        self.notified_height: typing.Optional[int] = None
        # Cache some idea of room to avoid recounting on each subscription
        self.subs_room = 0

        self.session_event = Event()

    async def _start_server(self, kind, *args, **kw_args):
        loop = asyncio.get_event_loop()
        if kind == 'RPC':
            protocol_class = LocalRPC
        else:
            protocol_class = self.env.coin.SESSIONCLS
        protocol_factory = partial(protocol_class, self, self.db,
                                   self.mempool, self.peer_mgr, kind)

        host, port = args[:2]
        try:
            self.servers[kind] = await loop.create_server(protocol_factory, *args, **kw_args)
        except OSError as e:    # don't suppress CancelledError
            self.logger.error(f'{kind} server failed to listen on {host}:'
                              f'{port:d} :{e!r}')
        else:
            self.logger.info(f'{kind} server listening on {host}:{port:d}')

    async def _start_external_servers(self):
        """Start listening on TCP and SSL ports, but only if the respective
        port was given in the environment.
        """
        env = self.env
        host = env.cs_host(for_rpc=False)
        if env.tcp_port is not None:
            await self._start_server('TCP', host, env.tcp_port)
        if env.ssl_port is not None:
            sslc = ssl.SSLContext(ssl.PROTOCOL_TLS)
            sslc.load_cert_chain(env.ssl_certfile, keyfile=env.ssl_keyfile)
            await self._start_server('SSL', host, env.ssl_port, ssl=sslc)

    async def _close_servers(self, kinds):
        """Close the servers of the given kinds (TCP etc.)."""
        if kinds:
            self.logger.info('closing down {} listening servers'
                             .format(', '.join(kinds)))
        for kind in kinds:
            server = self.servers.pop(kind, None)
            if server:
                server.close()
                await server.wait_closed()

    async def _manage_servers(self):
        paused = False
        max_sessions = self.env.max_sessions
        low_watermark = max_sessions * 19 // 20
        while True:
            await self.session_event.wait()
            self.session_event.clear()
            if not paused and len(self.sessions) >= max_sessions:
                self.logger.info(f'maximum sessions {max_sessions:,d} '
                                 f'reached, stopping new connections until '
                                 f'count drops to {low_watermark:,d}')
                await self._close_servers(['TCP', 'SSL'])
                paused = True
            # Start listening for incoming connections if paused and
            # session count has fallen
            if paused and len(self.sessions) <= low_watermark:
                self.logger.info('resuming listening for incoming connections')
                await self._start_external_servers()
                paused = False

    async def _log_sessions(self):
        """Periodically log sessions."""
        log_interval = self.env.log_sessions
        if log_interval:
            while True:
                await sleep(log_interval)
                data = self._session_data(for_log=True)
                for line in text.sessions_lines(data):
                    self.logger.info(line)
                self.logger.info(json.dumps(self._get_info()))

    def _group_map(self):
        group_map = defaultdict(list)
        for session in self.sessions:
            group_map[session.group].append(session)
        return group_map

    def _sub_count(self) -> int:
        return sum(s.sub_count() for s in self.sessions)

    def _lookup_session(self, session_id):
        try:
            session_id = int(session_id)
        except Exception:
            pass
        else:
            for session in self.sessions:
                if session.session_id == session_id:
                    return session
        return None

    async def _for_each_session(self, session_ids, operation):
        if not isinstance(session_ids, list):
            raise RPCError(BAD_REQUEST, 'expected a list of session IDs')

        result = []
        for session_id in session_ids:
            session = self._lookup_session(session_id)
            if session:
                result.append(await operation(session))
            else:
                result.append(f'unknown session: {session_id}')
        return result

    async def _clear_stale_sessions(self):
        """Cut off sessions that haven't done anything for 10 minutes."""
        session_timeout = self.env.session_timeout
        while True:
            await sleep(session_timeout // 10)
            stale_cutoff = time.perf_counter() - session_timeout
            stale_sessions = [session for session in self.sessions
                              if session.last_recv < stale_cutoff]
            if stale_sessions:
                text = ', '.join(str(session.session_id)
                                 for session in stale_sessions)
                self.logger.info(f'closing stale connections {text}')
                # Give the sockets some time to close gracefully
                if stale_sessions:
                    await asyncio.wait([
                        session.close(force_after=session_timeout // 10) for session in stale_sessions
                    ])

            # Consolidate small groups
            group_map = self._group_map()
            groups = [group for group, sessions in group_map.items()
                      if len(sessions) <= 5]  # fixme: apply session cost here
            if len(groups) > 1:
                new_group = groups[-1]
                for group in groups:
                    for session in group_map[group]:
                        session.group = new_group

    def _get_info(self):
        """A summary of server state."""
        group_map = self._group_map()
        method_counts = collections.defaultdict(int)
        error_count = 0
        logged = 0
        paused = 0
        pending_requests = 0
        closing = 0

        for s in self.sessions:
            error_count += s.errors
            if s.log_me:
                logged += 1
            if not s._can_send.is_set():
                paused += 1
            pending_requests += s.count_pending_items()
            if s.is_closing():
                closing += 1
            for request, _ in s.connection._requests.values():
                method_counts[request.method] += 1
        return {
            'closing': closing,
            'daemon': self.daemon.logged_url(),
            'daemon_height': self.daemon.cached_height(),
            'db_height': self.db.db_height,
            'errors': error_count,
            'groups': len(group_map),
            'logged': logged,
            'paused': paused,
            'pid': os.getpid(),
            'peers': self.peer_mgr.info(),
            'requests': pending_requests,
            'method_counts': method_counts,
            'sessions': self.session_count(),
            'subs': self._sub_count(),
            'txs_sent': self.txs_sent,
            'uptime': util.formatted_time(time.time() - self.start_time),
            'version': lbry.__version__,
        }

    def _session_data(self, for_log):
        """Returned to the RPC 'sessions' call."""
        now = time.time()
        sessions = sorted(self.sessions, key=lambda s: s.start_time)
        return [(session.session_id,
                 session.flags(),
                 session.peer_address_str(for_log=for_log),
                 session.client_version,
                 session.protocol_version_string(),
                 session.count_pending_items(),
                 session.txs_sent,
                 session.sub_count(),
                 session.recv_count, session.recv_size,
                 session.send_count, session.send_size,
                 now - session.start_time)
                for session in sessions]

    def _group_data(self):
        """Returned to the RPC 'groups' call."""
        result = []
        group_map = self._group_map()
        for group, sessions in group_map.items():
            result.append([group.gid,
                           len(sessions),
                           sum(s.bw_charge for s in sessions),
                           sum(s.count_pending_items() for s in sessions),
                           sum(s.txs_sent for s in sessions),
                           sum(s.sub_count() for s in sessions),
                           sum(s.recv_count for s in sessions),
                           sum(s.recv_size for s in sessions),
                           sum(s.send_count for s in sessions),
                           sum(s.send_size for s in sessions),
                           ])
        return result

    async def _electrum_and_raw_headers(self, height):
        raw_header = await self.raw_header(height)
        electrum_header = self.env.coin.electrum_header(raw_header, height)
        return electrum_header, raw_header

    async def _refresh_hsub_results(self, height):
        """Refresh the cached header subscription responses to be for height,
        and record that as notified_height.
        """
        # Paranoia: a reorg could race and leave db_height lower
        height = min(height, self.db.db_height)
        electrum, raw = await self._electrum_and_raw_headers(height)
        self.hsub_results = (electrum, {'hex': raw.hex(), 'height': height})
        self.notified_height = height

    # --- LocalRPC command handlers

    async def rpc_add_peer(self, real_name):
        """Add a peer.

        real_name: "bch.electrumx.cash t50001 s50002" for example
        """
        await self.peer_mgr.add_localRPC_peer(real_name)
        return f"peer '{real_name}' added"

    async def rpc_disconnect(self, session_ids):
        """Disconnect sessions.

        session_ids: array of session IDs
        """
        async def close(session):
            """Close the session's transport."""
            await session.close(force_after=2)
            return f'disconnected {session.session_id}'

        return await self._for_each_session(session_ids, close)

    async def rpc_log(self, session_ids):
        """Toggle logging of sessions.

        session_ids: array of session IDs
        """
        async def toggle_logging(session):
            """Toggle logging of the session."""
            session.toggle_logging()
            return f'log {session.session_id}: {session.log_me}'

        return await self._for_each_session(session_ids, toggle_logging)

    async def rpc_daemon_url(self, daemon_url):
        """Replace the daemon URL."""
        daemon_url = daemon_url or self.env.daemon_url
        try:
            self.daemon.set_url(daemon_url)
        except Exception as e:
            raise RPCError(BAD_REQUEST, f'an error occurred: {e!r}')
        return f'now using daemon at {self.daemon.logged_url()}'

    async def rpc_stop(self):
        """Shut down the server cleanly."""
        self.shutdown_event.set()
        return 'stopping'

    async def rpc_getinfo(self):
        """Return summary information about the server process."""
        return self._get_info()

    async def rpc_groups(self):
        """Return statistics about the session groups."""
        return self._group_data()

    async def rpc_peers(self):
        """Return a list of data about server peers."""
        return self.peer_mgr.rpc_data()

    async def rpc_query(self, items, limit):
        """Return a list of data about server peers."""
        coin = self.env.coin
        db = self.db
        lines = []

        def arg_to_hashX(arg):
            try:
                script = bytes.fromhex(arg)
                lines.append(f'Script: {arg}')
                return coin.hashX_from_script(script)
            except ValueError:
                pass

            try:
                hashX = coin.address_to_hashX(arg)
            except Base58Error as e:
                lines.append(e.args[0])
                return None
            lines.append(f'Address: {arg}')
            return hashX

        for arg in items:
            hashX = arg_to_hashX(arg)
            if not hashX:
                continue
            n = None
            history = await db.limited_history(hashX, limit=limit)
            for n, (tx_hash, height) in enumerate(history):
                lines.append(f'History #{n:,d}: height {height:,d} '
                             f'tx_hash {hash_to_hex_str(tx_hash)}')
            if n is None:
                lines.append('No history found')
            n = None
            utxos = await db.all_utxos(hashX)
            for n, utxo in enumerate(utxos, start=1):
                lines.append(f'UTXO #{n:,d}: tx_hash '
                             f'{hash_to_hex_str(utxo.tx_hash)} '
                             f'tx_pos {utxo.tx_pos:,d} height '
                             f'{utxo.height:,d} value {utxo.value:,d}')
                if n == limit:
                    break
            if n is None:
                lines.append('No UTXOs found')

            balance = sum(utxo.value for utxo in utxos)
            lines.append(f'Balance: {coin.decimal_value(balance):,f} '
                         f'{coin.SHORTNAME}')

        return lines

    async def rpc_sessions(self):
        """Return statistics about connected sessions."""
        return self._session_data(for_log=False)

    async def rpc_reorg(self, count):
        """Force a reorg of the given number of blocks.

        count: number of blocks to reorg
        """
        count = non_negative_integer(count)
        if not self.bp.force_chain_reorg(count):
            raise RPCError(BAD_REQUEST, 'still catching up with daemon')
        return f'scheduled a reorg of {count:,d} blocks'

    # --- External Interface

    async def serve(self, notifications, server_listening_event):
        """Start the RPC server if enabled.  When the event is triggered,
        start TCP and SSL servers."""
        try:
            if self.env.rpc_port is not None:
                await self._start_server('RPC', self.env.cs_host(for_rpc=True),
                                         self.env.rpc_port)
            self.logger.info(f'max session count: {self.env.max_sessions:,d}')
            self.logger.info(f'session timeout: '
                             f'{self.env.session_timeout:,d} seconds')
            self.logger.info(f'max response size {self.env.max_send:,d} bytes')
            if self.env.drop_client is not None:
                self.logger.info(f'drop clients matching: {self.env.drop_client.pattern}')
            # Start notifications; initialize hsub_results
            await notifications.start(self.db.db_height, self._notify_sessions)
            await self.start_other()
            await self._start_external_servers()
            server_listening_event.set()
            # Peer discovery should start after the external servers
            # because we connect to ourself
            await asyncio.wait([
                self.peer_mgr.discover_peers(),
                self._clear_stale_sessions(),
                self._log_sessions(),
                self._manage_servers()
            ])
        finally:
            await self._close_servers(list(self.servers.keys()))
            if self.sessions:
                await asyncio.wait([
                    session.close(force_after=1) for session in self.sessions
                ])
            await self.stop_other()

    async def start_other(self):
        pass

    async def stop_other(self):
        pass

    def session_count(self) -> int:
        """The number of connections that we've sent something to."""
        return len(self.sessions)

    async def daemon_request(self, method, *args):
        """Catch a DaemonError and convert it to an RPCError."""
        try:
            return await getattr(self.daemon, method)(*args)
        except DaemonError as e:
            raise RPCError(DAEMON_ERROR, f'daemon error: {e!r}') from None

    async def raw_header(self, height):
        """Return the binary header at the given height."""
        try:
            return await self.db.raw_header(height)
        except IndexError:
            raise RPCError(BAD_REQUEST, f'height {height:,d} '
                                        'out of range') from None

    async def electrum_header(self, height):
        """Return the deserialized header at the given height."""
        electrum_header, _ = await self._electrum_and_raw_headers(height)
        return electrum_header

    async def broadcast_transaction(self, raw_tx):
        hex_hash = await self.daemon.broadcast_transaction(raw_tx)
        self.mempool.wakeup.set()
        self.txs_sent += 1
        return hex_hash

    async def limited_history(self, hashX):
        """A caching layer."""
        hc = self.history_cache
        if hashX not in hc:
            # History DoS limit.  Each element of history is about 99
            # bytes when encoded as JSON.  This limits resource usage
            # on bloated history requests, and uses a smaller divisor
            # so large requests are logged before refusing them.
            limit = self.env.max_send // 97
            hc[hashX] = await self.db.limited_history(hashX, limit=limit)
        return hc[hashX]

    async def _notify_sessions(self, height, touched):
        """Notify sessions about height changes and touched addresses."""
        height_changed = height != self.notified_height
        if height_changed:
            await self._refresh_hsub_results(height)
            # Invalidate our history cache for touched hashXs
            hc = self.history_cache
            for hashX in set(hc).intersection(touched):
                del hc[hashX]

        if self.sessions:
            await asyncio.wait([
                session.notify(touched, height_changed) for session in self.sessions
            ])

    def add_session(self, session):
        self.sessions.add(session)
        self.session_event.set()
        gid = int(session.start_time - self.start_time) // 900
        if self.cur_group.gid != gid:
            self.cur_group = SessionGroup(gid)
        return self.cur_group

    def remove_session(self, session):
        """Remove a session from our sessions list if there."""
        self.sessions.remove(session)
        self.session_event.set()


class SessionBase(RPCSession):
    """Base class of ElectrumX JSON sessions.

    Each session runs its tasks in asynchronous parallelism with other
    sessions.
    """

    MAX_CHUNK_SIZE = 40960
    session_counter = itertools.count()
    request_handlers: typing.Dict[str, typing.Callable] = {}
    version = '0.5.7'

    def __init__(self, session_mgr, db, mempool, peer_mgr, kind):
        connection = JSONRPCConnection(JSONRPCAutoDetect)
        self.env = session_mgr.env
        super().__init__(connection=connection)
        self.logger = util.class_logger(__name__, self.__class__.__name__)
        self.session_mgr = session_mgr
        self.db = db
        self.mempool = mempool
        self.peer_mgr = peer_mgr
        self.kind = kind  # 'RPC', 'TCP' etc.
        self.coin = self.env.coin
        self.anon_logs = self.env.anon_logs
        self.txs_sent = 0
        self.log_me = False
        self.daemon_request = self.session_mgr.daemon_request
        # Hijack the connection so we can log messages
        self._receive_message_orig = self.connection.receive_message
        self.connection.receive_message = self.receive_message

    async def notify(self, touched, height_changed):
        pass

    def default_framer(self):
        return NewlineFramer(self.env.max_receive)

    def peer_address_str(self, *, for_log=True):
        """Returns the peer's IP address and port as a human-readable
        string, respecting anon logs if the output is for a log."""
        if for_log and self.anon_logs:
            return 'xx.xx.xx.xx:xx'
        return super().peer_address_str()

    def receive_message(self, message):
        if self.log_me:
            self.logger.info(f'processing {message}')
        return self._receive_message_orig(message)

    def toggle_logging(self):
        self.log_me = not self.log_me

    def flags(self):
        """Status flags."""
        status = self.kind[0]
        if self.is_closing():
            status += 'C'
        if self.log_me:
            status += 'L'
        status += str(self._concurrency.max_concurrent)
        return status

    def connection_made(self, transport):
        """Handle an incoming client connection."""
        super().connection_made(transport)
        self.session_id = next(self.session_counter)
        context = {'conn_id': f'{self.session_id}'}
        self.logger = util.ConnectionLogger(self.logger, context)
        self.group = self.session_mgr.add_session(self)
        prometheus.METRICS.SESSIONS_COUNT.labels(version=self.client_version).inc()
        peer_addr_str = self.peer_address_str()
        self.logger.info(f'{self.kind} {peer_addr_str}, '
                         f'{self.session_mgr.session_count():,d} total')

    def connection_lost(self, exc):
        """Handle client disconnection."""
        super().connection_lost(exc)
        self.session_mgr.remove_session(self)
        prometheus.METRICS.SESSIONS_COUNT.labels(version=self.client_version).dec()
        msg = ''
        if not self._can_send.is_set():
            msg += ' whilst paused'
        if self.send_size >= 1024*1024:
            msg += ('.  Sent {:,d} bytes in {:,d} messages'
                    .format(self.send_size, self.send_count))
        if msg:
            msg = 'disconnected' + msg
            self.logger.info(msg)

    def count_pending_items(self):
        return len(self.connection.pending_requests())

    def semaphore(self):
        return Semaphores([self.group.semaphore])

    def sub_count(self):
        return 0

    async def handle_request(self, request):
        """Handle an incoming request.  ElectrumX doesn't receive
        notifications from client sessions.
        """
        prometheus.METRICS.REQUESTS_COUNT.labels(method=request.method, version=self.client_version).inc()
        if isinstance(request, Request):
            handler = self.request_handlers.get(request.method)
            handler = partial(handler, self)
        else:
            handler = None
        coro = handler_invocation(handler, request)()
        return await coro


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
            data = self.metrics.to_json_and_reset({
                'sessions': self.session_count(),
                'height': self.db.db_height,
            })
            if self.websocket is not None:
                self.websocket.send_message(data)
            await asyncio.sleep(1)

    async def start_other(self):
        self.running = True
        path = os.path.join(self.env.db_dir, 'claims.db')
        args = dict(
            initializer=reader.initializer,
            initargs=(
                self.logger, path, self.env.coin.NET, self.env.database_query_timeout,
                self.env.track_metrics, (
                    self.db.sql.blocked_streams, self.db.sql.blocked_channels,
                    self.db.sql.filtered_streams, self.db.sql.filtered_channels
                )
            )
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


class LBRYElectrumX(SessionBase):
    """A TCP server that handles incoming Electrum connections."""

    PROTOCOL_MIN = VERSION.PROTOCOL_MIN
    PROTOCOL_MAX = VERSION.PROTOCOL_MAX
    max_errors = math.inf  # don't disconnect people for errors! let them happen...
    session_mgr: LBRYSessionManager
    version = lbry.__version__

    @classmethod
    def initialize_request_handlers(cls):
        cls.request_handlers.update({
            'blockchain.block.get_chunk': cls.block_get_chunk,
            'blockchain.block.get_header': cls.block_get_header,
            'blockchain.estimatefee': cls.estimatefee,
            'blockchain.relayfee': cls.relayfee,
            'blockchain.scripthash.get_balance': cls.scripthash_get_balance,
            'blockchain.scripthash.get_history': cls.scripthash_get_history,
            'blockchain.scripthash.get_mempool': cls.scripthash_get_mempool,
            'blockchain.scripthash.listunspent': cls.scripthash_listunspent,
            'blockchain.scripthash.subscribe': cls.scripthash_subscribe,
            'blockchain.transaction.broadcast': cls.transaction_broadcast,
            'blockchain.transaction.get': cls.transaction_get,
            'blockchain.transaction.get_batch': cls.transaction_get_batch,
            'blockchain.transaction.info': cls.transaction_info,
            'blockchain.transaction.get_merkle': cls.transaction_merkle,
            'server.add_peer': cls.add_peer,
            'server.banner': cls.banner,
            'server.payment_address': cls.payment_address,
            'server.donation_address': cls.donation_address,
            'server.features': cls.server_features_async,
            'server.peers.subscribe': cls.peers_subscribe,
            'server.version': cls.server_version,
            'blockchain.transaction.get_height': cls.transaction_get_height,
            'blockchain.claimtrie.search': cls.claimtrie_search,
            'blockchain.claimtrie.resolve': cls.claimtrie_resolve,
            'blockchain.claimtrie.getclaimsbyids': cls.claimtrie_getclaimsbyids,
            'blockchain.block.get_server_height': cls.get_server_height,
            'mempool.get_fee_histogram': cls.mempool_compact_histogram,
            'blockchain.block.headers': cls.block_headers,
            'server.ping': cls.ping,
            'blockchain.headers.subscribe': cls.headers_subscribe_False,
            'blockchain.address.get_balance': cls.address_get_balance,
            'blockchain.address.get_history': cls.address_get_history,
            'blockchain.address.get_mempool': cls.address_get_mempool,
            'blockchain.address.listunspent': cls.address_listunspent,
            'blockchain.address.subscribe': cls.address_subscribe,
            'blockchain.address.unsubscribe': cls.address_unsubscribe,
        })

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not LBRYElectrumX.request_handlers:
            LBRYElectrumX.initialize_request_handlers()
        self.subscribe_headers = False
        self.subscribe_headers_raw = False
        self.connection.max_response_size = self.env.max_send
        self.hashX_subs = {}
        self.sv_seen = False
        self.mempool_statuses = {}
        self.protocol_tuple = self.PROTOCOL_MIN

        self.daemon = self.session_mgr.daemon
        self.bp: LBRYBlockProcessor = self.session_mgr.bp
        self.db: LBRYLevelDB = self.bp.db

    @classmethod
    def protocol_min_max_strings(cls):
        return [util.version_string(ver)
                for ver in (cls.PROTOCOL_MIN, cls.PROTOCOL_MAX)]

    @classmethod
    def server_features(cls, env):
        """Return the server features dictionary."""
        min_str, max_str = cls.protocol_min_max_strings()
        return {
            'hosts': env.hosts_dict(),
            'pruning': None,
            'server_version': cls.version,
            'protocol_min': min_str,
            'protocol_max': max_str,
            'genesis_hash': env.coin.GENESIS_HASH,
            'description': env.description,
            'payment_address': env.payment_address,
            'donation_address': env.donation_address,
            'daily_fee': env.daily_fee,
            'hash_function': 'sha256',
            'trending_algorithm': env.trending_algorithms[0]
        }

    async def server_features_async(self):
        return self.server_features(self.env)

    @classmethod
    def server_version_args(cls):
        """The arguments to a server.version RPC call to a peer."""
        return [cls.version, cls.protocol_min_max_strings()]

    def protocol_version_string(self):
        return util.version_string(self.protocol_tuple)

    def sub_count(self):
        return len(self.hashX_subs)

    async def notify(self, touched, height_changed):
        """Notify the client about changes to touched addresses (from mempool
        updates or new blocks) and height.
        """
        if height_changed and self.subscribe_headers:
            args = (await self.subscribe_headers_result(), )
            try:
                await self.send_notification('blockchain.headers.subscribe', args)
            except asyncio.TimeoutError:
                self.logger.info("timeout sending headers notification to %s", self.peer_address_str(for_log=True))
                self.abort()
                return

        touched = touched.intersection(self.hashX_subs)
        if touched or (height_changed and self.mempool_statuses):
            changed = {}

            for hashX in touched:
                alias = self.hashX_subs[hashX]
                status = await self.address_status(hashX)
                changed[alias] = status

            # Check mempool hashXs - the status is a function of the
            # confirmed state of other transactions.  Note: we cannot
            # iterate over mempool_statuses as it changes size.
            for hashX in tuple(self.mempool_statuses):
                # Items can be evicted whilst await-ing status; False
                # ensures such hashXs are notified
                old_status = self.mempool_statuses.get(hashX, False)
                status = await self.address_status(hashX)
                if status != old_status:
                    alias = self.hashX_subs[hashX]
                    changed[alias] = status

            for alias, status in changed.items():
                if len(alias) == 64:
                    method = 'blockchain.scripthash.subscribe'
                else:
                    method = 'blockchain.address.subscribe'

                try:
                    await self.send_notification(method, (alias, status))
                except asyncio.TimeoutError:
                    self.logger.info("timeout sending address notification to %s", self.peer_address_str(for_log=True))
                    self.abort()
                    return

            if changed:
                es = '' if len(changed) == 1 else 'es'
                self.logger.info(f'notified of {len(changed):,d} address{es}')

    def get_metrics_or_placeholder_for_api(self, query_name):
        """ Do not hold on to a reference to the metrics
            returned by this method past an `await` or
            you may be working with a stale metrics object.
        """
        if self.env.track_metrics:
            return self.session_mgr.metrics.for_api(query_name)
        else:
            return APICallMetrics(query_name)

    async def run_in_executor(self, query_name, func, kwargs):
        start = time.perf_counter()
        try:
            prometheus.METRICS.SQLITE_PENDING_COUNT.inc()
            result = await asyncio.get_running_loop().run_in_executor(
                self.session_mgr.query_executor, func, kwargs
            )
        except asyncio.CancelledError:
            raise
        except reader.SQLiteInterruptedError as error:
            metrics = self.get_metrics_or_placeholder_for_api(query_name)
            metrics.query_interrupt(start, error.metrics)
            prometheus.METRICS.prometheus.METRICS.SQLITE_INTERRUPT_COUNT.inc()
            raise RPCError(JSONRPC.QUERY_TIMEOUT, 'sqlite query timed out')
        except reader.SQLiteOperationalError as error:
            metrics = self.get_metrics_or_placeholder_for_api(query_name)
            metrics.query_error(start, error.metrics)
            prometheus.METRICS.SQLITE_OPERATIONAL_ERROR_COUNT.inc()
            raise RPCError(JSONRPC.INTERNAL_ERROR, 'query failed to execute')
        except Exception:
            log.exception("dear devs, please handle this exception better")
            metrics = self.get_metrics_or_placeholder_for_api(query_name)
            metrics.query_error(start, {})
            prometheus.METRICS.SQLITE_INTERNAL_ERROR_COUNT.inc()
            raise RPCError(JSONRPC.INTERNAL_ERROR, 'unknown server error')
        else:
            if self.env.track_metrics:
                metrics = self.get_metrics_or_placeholder_for_api(query_name)
                (result, metrics_data) = result
                metrics.query_response(start, metrics_data)
            return base64.b64encode(result).decode()
        finally:
            prometheus.METRICS.SQLITE_PENDING_COUNT.dec()
            prometheus.METRICS.SQLITE_EXECUTOR_TIMES.observe(time.perf_counter() - start)

    async def run_and_cache_query(self, query_name, function, kwargs):
        metrics = self.get_metrics_or_placeholder_for_api(query_name)
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
                    query_name, function, kwargs
                )
            else:
                metrics = self.get_metrics_or_placeholder_for_api(query_name)
                metrics.cache_response()
            return cache_item.result

    async def mempool_compact_histogram(self):
        return self.mempool.compact_fee_histogram()

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

    async def subscribe_headers_result(self):
        """The result of a header subscription or notification."""
        return self.session_mgr.hsub_results[self.subscribe_headers_raw]

    async def _headers_subscribe(self, raw):
        """Subscribe to get headers of new blocks."""
        self.subscribe_headers_raw = assert_boolean(raw)
        self.subscribe_headers = True
        return await self.subscribe_headers_result()

    async def headers_subscribe(self):
        """Subscribe to get raw headers of new blocks."""
        return await self._headers_subscribe(True)

    async def headers_subscribe_True(self, raw=True):
        """Subscribe to get headers of new blocks."""
        return await self._headers_subscribe(raw)

    async def headers_subscribe_False(self, raw=False):
        """Subscribe to get headers of new blocks."""
        return await self._headers_subscribe(raw)

    async def add_peer(self, features):
        """Add a peer (but only if the peer resolves to the source)."""
        return await self.peer_mgr.on_add_peer(features, self.peer_address())

    async def peers_subscribe(self):
        """Return the server peers as a list of (ip, host, details) tuples."""
        return self.peer_mgr.on_peers_subscribe(self.is_tor())

    async def address_status(self, hashX):
        """Returns an address status.

        Status is a hex string, but must be None if there is no history.
        """
        # Note history is ordered and mempool unordered in electrum-server
        # For mempool, height is -1 if it has unconfirmed inputs, otherwise 0
        db_history = await self.session_mgr.limited_history(hashX)
        mempool = await self.mempool.transaction_summaries(hashX)

        status = ''.join(f'{hash_to_hex_str(tx_hash)}:'
                         f'{height:d}:'
                         for tx_hash, height in db_history)
        status += ''.join(f'{hash_to_hex_str(tx.hash)}:'
                          f'{-tx.has_unconfirmed_inputs:d}:'
                          for tx in mempool)
        if status:
            status = sha256(status.encode()).hex()
        else:
            status = None

        if mempool:
            self.mempool_statuses[hashX] = status
        else:
            self.mempool_statuses.pop(hashX, None)

        return status

    async def hashX_listunspent(self, hashX):
        """Return the list of UTXOs of a script hash, including mempool
        effects."""
        utxos = await self.db.all_utxos(hashX)
        utxos = sorted(utxos)
        utxos.extend(await self.mempool.unordered_UTXOs(hashX))
        spends = await self.mempool.potential_spends(hashX)

        return [{'tx_hash': hash_to_hex_str(utxo.tx_hash),
                 'tx_pos': utxo.tx_pos,
                 'height': utxo.height, 'value': utxo.value}
                for utxo in utxos
                if (utxo.tx_hash, utxo.tx_pos) not in spends]

    async def hashX_subscribe(self, hashX, alias):
        self.hashX_subs[hashX] = alias
        return await self.address_status(hashX)

    async def hashX_unsubscribe(self, hashX, alias):
        del self.hashX_subs[hashX]

    def address_to_hashX(self, address):
        try:
            return self.coin.address_to_hashX(address)
        except Exception:
            pass
        raise RPCError(BAD_REQUEST, f'{address} is not a valid address')

    async def address_get_balance(self, address):
        """Return the confirmed and unconfirmed balance of an address."""
        hashX = self.address_to_hashX(address)
        return await self.get_balance(hashX)

    async def address_get_history(self, address):
        """Return the confirmed and unconfirmed history of an address."""
        hashX = self.address_to_hashX(address)
        return await self.confirmed_and_unconfirmed_history(hashX)

    async def address_get_mempool(self, address):
        """Return the mempool transactions touching an address."""
        hashX = self.address_to_hashX(address)
        return await self.unconfirmed_history(hashX)

    async def address_listunspent(self, address):
        """Return the list of UTXOs of an address."""
        hashX = self.address_to_hashX(address)
        return await self.hashX_listunspent(hashX)

    async def address_subscribe(self, *addresses):
        """Subscribe to an address.

        address: the address to subscribe to"""
        if len(addresses) > 1000:
            raise RPCError(BAD_REQUEST, f'too many addresses in subscription request: {len(addresses)}')
        hashXes = [
            (self.address_to_hashX(address), address) for address in addresses
        ]
        return await asyncio.gather(*(self.hashX_subscribe(*args) for args in hashXes))

    async def address_unsubscribe(self, address):
        """Unsubscribe an address.

        address: the address to unsubscribe"""
        hashX = self.address_to_hashX(address)
        return await self.hashX_unsubscribe(hashX, address)

    async def get_balance(self, hashX):
        utxos = await self.db.all_utxos(hashX)
        confirmed = sum(utxo.value for utxo in utxos)
        unconfirmed = await self.mempool.balance_delta(hashX)
        return {'confirmed': confirmed, 'unconfirmed': unconfirmed}

    async def scripthash_get_balance(self, scripthash):
        """Return the confirmed and unconfirmed balance of a scripthash."""
        hashX = scripthash_to_hashX(scripthash)
        return await self.get_balance(hashX)

    async def unconfirmed_history(self, hashX):
        # Note unconfirmed history is unordered in electrum-server
        # height is -1 if it has unconfirmed inputs, otherwise 0
        return [{'tx_hash': hash_to_hex_str(tx.hash),
                 'height': -tx.has_unconfirmed_inputs,
                 'fee': tx.fee}
                for tx in await self.mempool.transaction_summaries(hashX)]

    async def confirmed_and_unconfirmed_history(self, hashX):
        # Note history is ordered but unconfirmed is unordered in e-s
        history = await self.session_mgr.limited_history(hashX)
        conf = [{'tx_hash': hash_to_hex_str(tx_hash), 'height': height}
                for tx_hash, height in history]
        return conf + await self.unconfirmed_history(hashX)

    async def scripthash_get_history(self, scripthash):
        """Return the confirmed and unconfirmed history of a scripthash."""
        hashX = scripthash_to_hashX(scripthash)
        return await self.confirmed_and_unconfirmed_history(hashX)

    async def scripthash_get_mempool(self, scripthash):
        """Return the mempool transactions touching a scripthash."""
        hashX = scripthash_to_hashX(scripthash)
        return await self.unconfirmed_history(hashX)

    async def scripthash_listunspent(self, scripthash):
        """Return the list of UTXOs of a scripthash."""
        hashX = scripthash_to_hashX(scripthash)
        return await self.hashX_listunspent(hashX)

    async def scripthash_subscribe(self, scripthash):
        """Subscribe to a script hash.

        scripthash: the SHA256 hash of the script to subscribe to"""
        hashX = scripthash_to_hashX(scripthash)
        return await self.hashX_subscribe(hashX, scripthash)

    async def _merkle_proof(self, cp_height, height):
        max_height = self.db.db_height
        if not height <= cp_height <= max_height:
            raise RPCError(BAD_REQUEST,
                           f'require header height {height:,d} <= '
                           f'cp_height {cp_height:,d} <= '
                           f'chain height {max_height:,d}')
        branch, root = await self.db.header_branch_and_root(cp_height + 1,
                                                            height)
        return {
            'branch': [hash_to_hex_str(elt) for elt in branch],
            'root': hash_to_hex_str(root),
        }

    async def block_header(self, height, cp_height=0):
        """Return a raw block header as a hexadecimal string, or as a
        dictionary with a merkle proof."""
        height = non_negative_integer(height)
        cp_height = non_negative_integer(cp_height)
        raw_header_hex = (await self.session_mgr.raw_header(height)).hex()
        if cp_height == 0:
            return raw_header_hex
        result = {'header': raw_header_hex}
        result.update(await self._merkle_proof(cp_height, height))
        return result

    async def block_header_13(self, height):
        """Return a raw block header as a hexadecimal string.

        height: the header's height"""
        return await self.block_header(height)

    async def block_headers(self, start_height, count, cp_height=0, b64=False):
        """Return count concatenated block headers as hex for the main chain;
        starting at start_height.

        start_height and count must be non-negative integers.  At most
        MAX_CHUNK_SIZE headers will be returned.
        """
        start_height = non_negative_integer(start_height)
        count = non_negative_integer(count)
        cp_height = non_negative_integer(cp_height)

        max_size = self.MAX_CHUNK_SIZE
        count = min(count, max_size)
        headers, count = await self.db.read_headers(start_height, count)
        compressobj = zlib.compressobj(wbits=-15, level=1, memLevel=9)
        headers = base64.b64encode(compressobj.compress(headers) + compressobj.flush()).decode() if b64 else headers.hex()
        result = {
            'base64' if b64 else 'hex': headers,
            'count': count,
            'max': max_size
        }
        if count and cp_height:
            last_height = start_height + count - 1
            result.update(await self._merkle_proof(cp_height, last_height))
        return result

    async def block_get_chunk(self, index):
        """Return a chunk of block headers as a hexadecimal string.

        index: the chunk index"""
        index = non_negative_integer(index)
        size = self.coin.CHUNK_SIZE
        start_height = index * size
        headers, _ = await self.db.read_headers(start_height, size)
        return headers.hex()

    async def block_get_header(self, height):
        """The deserialized header at a given height.

        height: the header's height"""
        height = non_negative_integer(height)
        return await self.session_mgr.electrum_header(height)

    def is_tor(self):
        """Try to detect if the connection is to a tor hidden service we are
        running."""
        peername = self.peer_mgr.proxy_peername()
        if not peername:
            return False
        peer_address = self.peer_address()
        return peer_address and peer_address[0] == peername[0]

    async def replaced_banner(self, banner):
        network_info = await self.daemon_request('getnetworkinfo')
        ni_version = network_info['version']
        major, minor = divmod(ni_version, 1000000)
        minor, revision = divmod(minor, 10000)
        revision //= 100
        daemon_version = f'{major:d}.{minor:d}.{revision:d}'
        for pair in [
            ('$SERVER_VERSION', self.version),
            ('$DAEMON_VERSION', daemon_version),
            ('$DAEMON_SUBVERSION', network_info['subversion']),
            ('$PAYMENT_ADDRESS', self.env.payment_address),
            ('$DONATION_ADDRESS', self.env.donation_address),
        ]:
            banner = banner.replace(*pair)
        return banner

    async def payment_address(self):
        """Return the payment address as a string, empty if there is none."""
        return self.env.payment_address

    async def donation_address(self):
        """Return the donation address as a string, empty if there is none."""
        return self.env.donation_address

    async def banner(self):
        """Return the server banner text."""
        banner = f'You are connected to an {self.version} server.'

        if self.is_tor():
            banner_file = self.env.tor_banner_file
        else:
            banner_file = self.env.banner_file
        if banner_file:
            try:
                with codecs.open(banner_file, 'r', 'utf-8') as f:
                    banner = f.read()
            except Exception as e:
                self.logger.error(f'reading banner file {banner_file}: {e!r}')
            else:
                banner = await self.replaced_banner(banner)

        return banner

    async def relayfee(self):
        """The minimum fee a low-priority tx must pay in order to be accepted
        to the daemon's memory pool."""
        return await self.daemon_request('relayfee')

    async def estimatefee(self, number):
        """The estimated transaction fee per kilobyte to be paid for a
        transaction to be included within a certain number of blocks.

        number: the number of blocks
        """
        number = non_negative_integer(number)
        return await self.daemon_request('estimatefee', number)

    async def ping(self):
        """Serves as a connection keep-alive mechanism and for the client to
        confirm the server is still responding.
        """
        return None

    async def server_version(self, client_name='', protocol_version=None):
        """Returns the server version as a string.

        client_name: a string identifying the client
        protocol_version: the protocol version spoken by the client
        """

        if self.sv_seen and self.protocol_tuple >= (1, 4):
            raise RPCError(BAD_REQUEST, f'server.version already sent')
        self.sv_seen = True

        if client_name:
            client_name = str(client_name)
            if self.env.drop_client is not None and \
                    self.env.drop_client.match(client_name):
                self.close_after_send = True
                raise RPCError(BAD_REQUEST,
                               f'unsupported client: {client_name}')
            if self.client_version != client_name[:17]:
                prometheus.METRICS.SESSIONS_COUNT.labels(version=self.client_version).dec()
                self.client_version = client_name[:17]
                prometheus.METRICS.SESSIONS_COUNT.labels(version=self.client_version).inc()
        prometheus.METRICS.CLIENT_VERSIONS.labels(version=self.client_version).inc()

        # Find the highest common protocol version.  Disconnect if
        # that protocol version in unsupported.
        ptuple, client_min = util.protocol_version(
            protocol_version, self.PROTOCOL_MIN, self.PROTOCOL_MAX)
        if ptuple is None:
            # FIXME: this fills the logs
            # if client_min > self.PROTOCOL_MIN:
            #     self.logger.info(f'client requested future protocol version '
            #                      f'{util.version_string(client_min)} '
            #                      f'- is your software out of date?')
            self.close_after_send = True
            raise RPCError(BAD_REQUEST,
                           f'unsupported protocol version: {protocol_version}')
        self.protocol_tuple = ptuple
        return self.version, self.protocol_version_string()

    async def transaction_broadcast(self, raw_tx):
        """Broadcast a raw transaction to the network.

        raw_tx: the raw transaction as a hexadecimal string"""
        # This returns errors as JSON RPC errors, as is natural
        try:
            hex_hash = await self.session_mgr.broadcast_transaction(raw_tx)
            self.txs_sent += 1
            self.logger.info(f'sent tx: {hex_hash}')
            return hex_hash
        except DaemonError as e:
            error, = e.args
            message = error['message']
            self.logger.info(f'error sending transaction: {message}')
            raise RPCError(BAD_REQUEST, 'the transaction was rejected by '
                                        f'network rules.\n\n{message}\n[{raw_tx}]')

    async def transaction_info(self, tx_hash: str):
        assert_tx_hash(tx_hash)
        tx_info = await self.daemon_request('getrawtransaction', tx_hash, True)
        raw_tx = tx_info['hex']
        block_hash = tx_info.get('blockhash')
        if not block_hash:
            return raw_tx, {'block_height': -1}
        merkle_height = (await self.daemon_request('deserialised_block', block_hash))['height']
        merkle = await self.transaction_merkle(tx_hash, merkle_height)
        return raw_tx, merkle

    async def transaction_get_batch(self, *tx_hashes):
        if len(tx_hashes) > 100:
            raise RPCError(BAD_REQUEST, f'too many tx hashes in request: {len(tx_hashes)}')
        for tx_hash in tx_hashes:
            assert_tx_hash(tx_hash)
        batch_result = {}
        height = None
        block_hash = None
        block = None
        for tx_hash in tx_hashes:
            tx_info = await self.daemon_request('getrawtransaction', tx_hash, True)
            raw_tx = tx_info['hex']
            if height is None:
                if 'blockhash' in tx_info:
                    block_hash = tx_info['blockhash']
                    block = await self.daemon_request('deserialised_block', block_hash)
                    height = block['height']
                else:
                    height = -1
            if block_hash != tx_info.get('blockhash'):
                raise RPCError(BAD_REQUEST, f'request contains a mix of transaction heights')
            else:
                if not block_hash:
                    merkle = {'block_height': -1}
                else:
                    try:
                        pos = block['tx'].index(tx_hash)
                    except ValueError:
                        raise RPCError(BAD_REQUEST, f'tx hash {tx_hash} not in '
                                                    f'block {block_hash} at height {height:,d}')
                    merkle = {
                        "merkle": self._get_merkle_branch(block['tx'], pos),
                        "pos": pos
                    }
                batch_result[tx_hash] = [raw_tx, merkle]
        return batch_result

    async def transaction_get(self, tx_hash, verbose=False):
        """Return the serialized raw transaction given its hash

        tx_hash: the transaction hash as a hexadecimal string
        verbose: passed on to the daemon
        """
        assert_tx_hash(tx_hash)
        if verbose not in (True, False):
            raise RPCError(BAD_REQUEST, f'"verbose" must be a boolean')

        return await self.daemon_request('getrawtransaction', tx_hash, verbose)

    async def _block_hash_and_tx_hashes(self, height):
        """Returns a pair (block_hash, tx_hashes) for the main chain block at
        the given height.

        block_hash is a hexadecimal string, and tx_hashes is an
        ordered list of hexadecimal strings.
        """
        height = non_negative_integer(height)
        hex_hashes = await self.daemon_request('block_hex_hashes', height, 1)
        block_hash = hex_hashes[0]
        block = await self.daemon_request('deserialised_block', block_hash)
        return block_hash, block['tx']

    def _get_merkle_branch(self, tx_hashes, tx_pos):
        """Return a merkle branch to a transaction.

        tx_hashes: ordered list of hex strings of tx hashes in a block
        tx_pos: index of transaction in tx_hashes to create branch for
        """
        hashes = [hex_str_to_hash(hash) for hash in tx_hashes]
        branch, root = self.db.merkle.branch_and_root(hashes, tx_pos)
        branch = [hash_to_hex_str(hash) for hash in branch]
        return branch

    async def transaction_merkle(self, tx_hash, height):
        """Return the markle branch to a confirmed transaction given its hash
        and height.

        tx_hash: the transaction hash as a hexadecimal string
        height: the height of the block it is in
        """
        assert_tx_hash(tx_hash)
        block_hash, tx_hashes = await self._block_hash_and_tx_hashes(height)
        try:
            pos = tx_hashes.index(tx_hash)
        except ValueError:
            raise RPCError(BAD_REQUEST, f'tx hash {tx_hash} not in '
                                        f'block {block_hash} at height {height:,d}')
        branch = self._get_merkle_branch(tx_hashes, pos)
        return {"block_height": height, "merkle": branch, "pos": pos}

    async def transaction_id_from_pos(self, height, tx_pos, merkle=False):
        """Return the txid and optionally a merkle proof, given
        a block height and position in the block.
        """
        tx_pos = non_negative_integer(tx_pos)
        if merkle not in (True, False):
            raise RPCError(BAD_REQUEST, f'"merkle" must be a boolean')

        block_hash, tx_hashes = await self._block_hash_and_tx_hashes(height)
        try:
            tx_hash = tx_hashes[tx_pos]
        except IndexError:
            raise RPCError(BAD_REQUEST, f'no tx at position {tx_pos:,d} in '
                                        f'block {block_hash} at height {height:,d}')

        if merkle:
            branch = self._get_merkle_branch(tx_hashes, tx_pos)
            return {"tx_hash": tx_hash, "merkle": branch}
        else:
            return tx_hash


class LocalRPC(SessionBase):
    """A local TCP RPC server session."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = 'RPC'
        self.connection._max_response_size = 0

    def protocol_version_string(self):
        return 'RPC'


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


def get_from_possible_keys(dictionary, *keys):
    for key in keys:
        if key in dictionary:
            return dictionary[key]
