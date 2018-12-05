# Copyright (c) 2016-2018, Neil Booth
#
# All rights reserved.
#
# See the file "LICENCE" for information about the copyright
# and warranty status of this software.

'''Classes for local RPC server and remote client TCP/SSL servers.'''

import asyncio
import codecs
import datetime
import itertools
import json
import os
import pylru
import ssl
import time
from collections import defaultdict
from functools import partial

import torba
from torba.rpc import (
    RPCSession, JSONRPCAutoDetect, JSONRPCConnection,
    TaskGroup, handler_invocation, RPCError, Request, ignore_after, sleep,
    Event
)
from torba.server import text
from torba.server import util
from torba.server.hash import (sha256, hash_to_hex_str, hex_str_to_hash,
                                HASHX_LEN, Base58Error)
from torba.server.daemon import DaemonError
from torba.server.peers import PeerManager


BAD_REQUEST = 1
DAEMON_ERROR = 2


def scripthash_to_hashX(scripthash):
    try:
        bin_hash = hex_str_to_hash(scripthash)
        if len(bin_hash) == 32:
            return bin_hash[:HASHX_LEN]
    except Exception:
        pass
    raise RPCError(BAD_REQUEST, f'{scripthash} is not a valid script hash')


def non_negative_integer(value):
    '''Return param value it is or can be converted to a non-negative
    integer, otherwise raise an RPCError.'''
    try:
        value = int(value)
        if value >= 0:
            return value
    except ValueError:
        pass
    raise RPCError(BAD_REQUEST,
                   f'{value} should be a non-negative integer')


def assert_boolean(value):
    '''Return param value it is boolean otherwise raise an RPCError.'''
    if value in (False, True):
        return value
    raise RPCError(BAD_REQUEST, f'{value} should be a boolean value')


def assert_tx_hash(value):
    '''Raise an RPCError if the value is not a valid transaction
    hash.'''
    try:
        if len(util.hex_to_bytes(value)) == 32:
            return
    except Exception:
        pass
    raise RPCError(BAD_REQUEST, f'{value} should be a transaction hash')


class Semaphores:
    '''For aiorpcX's semaphore handling.'''

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

    def __init__(self, gid):
        self.gid = gid
        # Concurrency per group
        self.semaphore = asyncio.Semaphore(20)


class SessionManager:
    '''Holds global state about all sessions.'''

    def __init__(self, env, db, bp, daemon, mempool, shutdown_event):
        env.max_send = max(350000, env.max_send)
        self.env = env
        self.db = db
        self.bp = bp
        self.daemon = daemon
        self.mempool = mempool
        self.peer_mgr = PeerManager(env, db)
        self.shutdown_event = shutdown_event
        self.logger = util.class_logger(__name__, self.__class__.__name__)
        self.servers = {}
        self.sessions = set()
        self.max_subs = env.max_subs
        self.cur_group = SessionGroup(0)
        self.txs_sent = 0
        self.start_time = time.time()
        self.history_cache = pylru.lrucache(256)
        self.notified_height = None
        # Cache some idea of room to avoid recounting on each subscription
        self.subs_room = 0
        # Masternode stuff only for such coins
        if issubclass(env.coin.SESSIONCLS, DashElectrumX):
            self.mn_cache_height = 0
            self.mn_cache = []

        self.session_event = Event()

        # Set up the RPC request handlers
        cmds = ('add_peer daemon_url disconnect getinfo groups log peers '
                'query reorg sessions stop'.split())
        LocalRPC.request_handlers = {cmd: getattr(self, 'rpc_' + cmd)
                                     for cmd in cmds}

    async def _start_server(self, kind, *args, **kw_args):
        loop = asyncio.get_event_loop()
        if kind == 'RPC':
            protocol_class = LocalRPC
        else:
            protocol_class = self.env.coin.SESSIONCLS
        protocol_factory = partial(protocol_class, self, self.db,
                                   self.mempool, self.peer_mgr, kind)
        server = loop.create_server(protocol_factory, *args, **kw_args)

        host, port = args[:2]
        try:
            self.servers[kind] = await server
        except OSError as e:    # don't suppress CancelledError
            self.logger.error(f'{kind} server failed to listen on {host}:'
                              f'{port:d} :{e!r}')
        else:
            self.logger.info(f'{kind} server listening on {host}:{port:d}')

    async def _start_external_servers(self):
        '''Start listening on TCP and SSL ports, but only if the respective
        port was given in the environment.
        '''
        env = self.env
        host = env.cs_host(for_rpc=False)
        if env.tcp_port is not None:
            await self._start_server('TCP', host, env.tcp_port)
        if env.ssl_port is not None:
            sslc = ssl.SSLContext(ssl.PROTOCOL_TLS)
            sslc.load_cert_chain(env.ssl_certfile, keyfile=env.ssl_keyfile)
            await self._start_server('SSL', host, env.ssl_port, ssl=sslc)

    async def _close_servers(self, kinds):
        '''Close the servers of the given kinds (TCP etc.).'''
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
        '''Periodically log sessions.'''
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

    def _sub_count(self):
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
        '''Cut off sessions that haven't done anything for 10 minutes.'''
        while True:
            await sleep(60)
            stale_cutoff = time.time() - self.env.session_timeout
            stale_sessions = [session for session in self.sessions
                              if session.last_recv < stale_cutoff]
            if stale_sessions:
                text = ', '.join(str(session.session_id)
                                 for session in stale_sessions)
                self.logger.info(f'closing stale connections {text}')
                # Give the sockets some time to close gracefully
                async with TaskGroup() as group:
                    for session in stale_sessions:
                        await group.spawn(session.close())

            # Consolidate small groups
            bw_limit = self.env.bandwidth_limit
            group_map = self._group_map()
            groups = [group for group, sessions in group_map.items()
                      if len(sessions) <= 5 and
                      sum(s.bw_charge for s in sessions) < bw_limit]
            if len(groups) > 1:
                new_group = groups[-1]
                for group in groups:
                    for session in group_map[group]:
                        session.group = new_group

    def _get_info(self):
        '''A summary of server state.'''
        group_map = self._group_map()
        return {
            'closing': len([s for s in self.sessions if s.is_closing()]),
            'daemon': self.daemon.logged_url(),
            'daemon_height': self.daemon.cached_height(),
            'db_height': self.db.db_height,
            'errors': sum(s.errors for s in self.sessions),
            'groups': len(group_map),
            'logged': len([s for s in self.sessions if s.log_me]),
            'paused': sum(not s.can_send.is_set() for s in self.sessions),
            'pid': os.getpid(),
            'peers': self.peer_mgr.info(),
            'requests': sum(s.count_pending_items() for s in self.sessions),
            'sessions': self.session_count(),
            'subs': self._sub_count(),
            'txs_sent': self.txs_sent,
            'uptime': util.formatted_time(time.time() - self.start_time),
            'version': torba.__version__,
        }

    def _session_data(self, for_log):
        '''Returned to the RPC 'sessions' call.'''
        now = time.time()
        sessions = sorted(self.sessions, key=lambda s: s.start_time)
        return [(session.session_id,
                 session.flags(),
                 session.peer_address_str(for_log=for_log),
                 session.client,
                 session.protocol_version_string(),
                 session.count_pending_items(),
                 session.txs_sent,
                 session.sub_count(),
                 session.recv_count, session.recv_size,
                 session.send_count, session.send_size,
                 now - session.start_time)
                for session in sessions]

    def _group_data(self):
        '''Returned to the RPC 'groups' call.'''
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
        '''Refresh the cached header subscription responses to be for height,
        and record that as notified_height.
        '''
        # Paranoia: a reorg could race and leave db_height lower
        height = min(height, self.db.db_height)
        electrum, raw = await self._electrum_and_raw_headers(height)
        self.hsub_results = (electrum, {'hex': raw.hex(), 'height': height})
        self.notified_height = height

    # --- LocalRPC command handlers

    async def rpc_add_peer(self, real_name):
        '''Add a peer.

        real_name: "bch.electrumx.cash t50001 s50002" for example
        '''
        await self.peer_mgr.add_localRPC_peer(real_name)
        return "peer '{}' added".format(real_name)

    async def rpc_disconnect(self, session_ids):
        '''Disconnect sesssions.

        session_ids: array of session IDs
        '''
        async def close(session):
            '''Close the session's transport.'''
            await session.close(force_after=2)
            return f'disconnected {session.session_id}'

        return await self._for_each_session(session_ids, close)

    async def rpc_log(self, session_ids):
        '''Toggle logging of sesssions.

        session_ids: array of session IDs
        '''
        async def toggle_logging(session):
            '''Toggle logging of the session.'''
            session.toggle_logging()
            return f'log {session.session_id}: {session.log_me}'

        return await self._for_each_session(session_ids, toggle_logging)

    async def rpc_daemon_url(self, daemon_url):
        '''Replace the daemon URL.'''
        daemon_url = daemon_url or self.env.daemon_url
        try:
            self.daemon.set_url(daemon_url)
        except Exception as e:
            raise RPCError(BAD_REQUEST, f'an error occured: {e!r}')
        return f'now using daemon at {self.daemon.logged_url()}'

    async def rpc_stop(self):
        '''Shut down the server cleanly.'''
        self.shutdown_event.set()
        return 'stopping'

    async def rpc_getinfo(self):
        '''Return summary information about the server process.'''
        return self._get_info()

    async def rpc_groups(self):
        '''Return statistics about the session groups.'''
        return self._group_data()

    async def rpc_peers(self):
        '''Return a list of data about server peers.'''
        return self.peer_mgr.rpc_data()

    async def rpc_query(self, items, limit):
        '''Return a list of data about server peers.'''
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
        '''Return statistics about connected sessions.'''
        return self._session_data(for_log=False)

    async def rpc_reorg(self, count):
        '''Force a reorg of the given number of blocks.

        count: number of blocks to reorg
        '''
        count = non_negative_integer(count)
        if not self.bp.force_chain_reorg(count):
            raise RPCError(BAD_REQUEST, 'still catching up with daemon')
        return f'scheduled a reorg of {count:,d} blocks'

    # --- External Interface

    async def serve(self, notifications, server_listening_event):
        '''Start the RPC server if enabled.  When the event is triggered,
        start TCP and SSL servers.'''
        try:
            if self.env.rpc_port is not None:
                await self._start_server('RPC', self.env.cs_host(for_rpc=True),
                                         self.env.rpc_port)
            self.logger.info(f'max session count: {self.env.max_sessions:,d}')
            self.logger.info(f'session timeout: '
                             f'{self.env.session_timeout:,d} seconds')
            self.logger.info('session bandwidth limit {:,d} bytes'
                             .format(self.env.bandwidth_limit))
            self.logger.info('max response size {:,d} bytes'
                             .format(self.env.max_send))
            self.logger.info('max subscriptions across all sessions: {:,d}'
                             .format(self.max_subs))
            self.logger.info('max subscriptions per session: {:,d}'
                             .format(self.env.max_session_subs))
            if self.env.drop_client is not None:
                self.logger.info('drop clients matching: {}'
                                 .format(self.env.drop_client.pattern))
            # Start notifications; initialize hsub_results
            await notifications.start(self.db.db_height, self._notify_sessions)
            await self._start_external_servers()
            server_listening_event.set()
            # Peer discovery should start after the external servers
            # because we connect to ourself
            async with TaskGroup() as group:
                await group.spawn(self.peer_mgr.discover_peers())
                await group.spawn(self._clear_stale_sessions())
                await group.spawn(self._log_sessions())
                await group.spawn(self._manage_servers())
        finally:
            # Close servers and sessions
            await self._close_servers(list(self.servers.keys()))
            async with TaskGroup() as group:
                for session in list(self.sessions):
                    await group.spawn(session.close(force_after=1))

    def session_count(self):
        '''The number of connections that we've sent something to.'''
        return len(self.sessions)

    async def daemon_request(self, method, *args):
        '''Catch a DaemonError and convert it to an RPCError.'''
        try:
            return await getattr(self.daemon, method)(*args)
        except DaemonError as e:
            raise RPCError(DAEMON_ERROR, f'daemon error: {e!r}') from None

    async def raw_header(self, height):
        '''Return the binary header at the given height.'''
        try:
            return await self.db.raw_header(height)
        except IndexError:
            raise RPCError(BAD_REQUEST, f'height {height:,d} '
                           'out of range') from None

    async def electrum_header(self, height):
        '''Return the deserialized header at the given height.'''
        electrum_header, _ = await self._electrum_and_raw_headers(height)
        return electrum_header

    async def broadcast_transaction(self, raw_tx):
        hex_hash = await self.daemon.broadcast_transaction(raw_tx)
        self.txs_sent += 1
        return hex_hash

    async def limited_history(self, hashX):
        '''A caching layer.'''
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
        '''Notify sessions about height changes and touched addresses.'''
        height_changed = height != self.notified_height
        if height_changed:
            await self._refresh_hsub_results(height)
            # Invalidate our history cache for touched hashXs
            hc = self.history_cache
            for hashX in set(hc).intersection(touched):
                del hc[hashX]

        async with TaskGroup() as group:
            for session in self.sessions:
                await group.spawn(session.notify(touched, height_changed))

    def add_session(self, session):
        self.sessions.add(session)
        self.session_event.set()
        gid = int(session.start_time - self.start_time) // 900
        if self.cur_group.gid != gid:
            self.cur_group = SessionGroup(gid)
        return self.cur_group

    def remove_session(self, session):
        '''Remove a session from our sessions list if there.'''
        self.sessions.remove(session)
        self.session_event.set()

    def new_subscription(self):
        if self.subs_room <= 0:
            self.subs_room = self.max_subs - self._sub_count()
            if self.subs_room <= 0:
                raise RPCError(BAD_REQUEST, f'server subscription limit '
                               f'{self.max_subs:,d} reached')
        self.subs_room -= 1


class SessionBase(RPCSession):
    '''Base class of ElectrumX JSON sessions.

    Each session runs its tasks in asynchronous parallelism with other
    sessions.
    '''

    MAX_CHUNK_SIZE = 2016
    session_counter = itertools.count()

    def __init__(self, session_mgr, db, mempool, peer_mgr, kind):
        connection = JSONRPCConnection(JSONRPCAutoDetect)
        super().__init__(connection=connection)
        self.logger = util.class_logger(__name__, self.__class__.__name__)
        self.session_mgr = session_mgr
        self.db = db
        self.mempool = mempool
        self.peer_mgr = peer_mgr
        self.kind = kind  # 'RPC', 'TCP' etc.
        self.env = session_mgr.env
        self.coin = self.env.coin
        self.client = 'unknown'
        self.anon_logs = self.env.anon_logs
        self.txs_sent = 0
        self.log_me = False
        self.bw_limit = self.env.bandwidth_limit
        self.daemon_request = self.session_mgr.daemon_request
        # Hijack the connection so we can log messages
        self._receive_message_orig = self.connection.receive_message
        self.connection.receive_message = self.receive_message

    async def notify(self, touched, height_changed):
        pass

    def peer_address_str(self, *, for_log=True):
        '''Returns the peer's IP address and port as a human-readable
        string, respecting anon logs if the output is for a log.'''
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
        '''Status flags.'''
        status = self.kind[0]
        if self.is_closing():
            status += 'C'
        if self.log_me:
            status += 'L'
        status += str(self.concurrency.max_concurrent)
        return status

    def connection_made(self, transport):
        '''Handle an incoming client connection.'''
        super().connection_made(transport)
        self.session_id = next(self.session_counter)
        context = {'conn_id': f'{self.session_id}'}
        self.logger = util.ConnectionLogger(self.logger, context)
        self.group = self.session_mgr.add_session(self)
        self.logger.info(f'{self.kind} {self.peer_address_str()}, '
                         f'{self.session_mgr.session_count():,d} total')

    def connection_lost(self, exc):
        '''Handle client disconnection.'''
        super().connection_lost(exc)
        self.session_mgr.remove_session(self)
        msg = ''
        if not self._can_send.is_set():
            msg += ' whilst paused'
        if self._concurrency.max_concurrent != self.max_concurrent:
            msg += ' whilst throttled'
        if self.send_size >= 1024*1024:
            msg += ('.  Sent {:,d} bytes in {:,d} messages'
                    .format(self.send_size, self.send_count))
        if msg:
            msg = 'disconnected' + msg
            self.logger.info(msg)

    def count_pending_items(self):
        return len(self.connection.pending_requests())

    def semaphore(self):
        return Semaphores([self.concurrency.semaphore, self.group.semaphore])

    def sub_count(self):
        return 0

    async def handle_request(self, request):
        '''Handle an incoming request.  ElectrumX doesn't receive
        notifications from client sessions.
        '''
        if isinstance(request, Request):
            handler = self.request_handlers.get(request.method)
        else:
            handler = None
        coro = handler_invocation(handler, request)()
        return await coro


class ElectrumX(SessionBase):
    '''A TCP server that handles incoming Electrum connections.'''

    PROTOCOL_MIN = (1, 1)
    PROTOCOL_MAX = (1, 4)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subscribe_headers = False
        self.subscribe_headers_raw = False
        self.connection.max_response_size = self.env.max_send
        self.max_subs = self.env.max_session_subs
        self.hashX_subs = {}
        self.sv_seen = False
        self.mempool_statuses = {}
        self.set_request_handlers(self.PROTOCOL_MIN)

    @classmethod
    def protocol_min_max_strings(cls):
        return [util.version_string(ver)
                for ver in (cls.PROTOCOL_MIN, cls.PROTOCOL_MAX)]

    @classmethod
    def server_features(cls, env):
        '''Return the server features dictionary.'''
        min_str, max_str = cls.protocol_min_max_strings()
        return {
            'hosts': env.hosts_dict(),
            'pruning': None,
            'server_version': torba.__version__,
            'protocol_min': min_str,
            'protocol_max': max_str,
            'genesis_hash': env.coin.GENESIS_HASH,
            'hash_function': 'sha256',
        }

    async def server_features_async(self):
        return self.server_features(self.env)

    @classmethod
    def server_version_args(cls):
        '''The arguments to a server.version RPC call to a peer.'''
        return [torba.__version__, cls.protocol_min_max_strings()]

    def protocol_version_string(self):
        return util.version_string(self.protocol_tuple)

    def sub_count(self):
        return len(self.hashX_subs)

    async def notify(self, touched, height_changed):
        '''Notify the client about changes to touched addresses (from mempool
        updates or new blocks) and height.
        '''
        if height_changed and self.subscribe_headers:
            args = (await self.subscribe_headers_result(), )
            await self.send_notification('blockchain.headers.subscribe', args)

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
                await self.send_notification(method, (alias, status))

            if changed:
                es = '' if len(changed) == 1 else 'es'
                self.logger.info(f'notified of {len(changed):,d} address{es}')

    async def subscribe_headers_result(self):
        '''The result of a header subscription or notification.'''
        return self.session_mgr.hsub_results[self.subscribe_headers_raw]

    async def _headers_subscribe(self, raw):
        '''Subscribe to get headers of new blocks.'''
        self.subscribe_headers_raw = assert_boolean(raw)
        self.subscribe_headers = True
        return await self.subscribe_headers_result()

    async def headers_subscribe(self):
        '''Subscribe to get raw headers of new blocks.'''
        return await self._headers_subscribe(True)

    async def headers_subscribe_True(self, raw=True):
        '''Subscribe to get headers of new blocks.'''
        return await self._headers_subscribe(raw)

    async def headers_subscribe_False(self, raw=False):
        '''Subscribe to get headers of new blocks.'''
        return await self._headers_subscribe(raw)

    async def add_peer(self, features):
        '''Add a peer (but only if the peer resolves to the source).'''
        return await self.peer_mgr.on_add_peer(features, self.peer_address())

    async def peers_subscribe(self):
        '''Return the server peers as a list of (ip, host, details) tuples.'''
        return self.peer_mgr.on_peers_subscribe(self.is_tor())

    async def address_status(self, hashX):
        '''Returns an address status.

        Status is a hex string, but must be None if there is no history.
        '''
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
        '''Return the list of UTXOs of a script hash, including mempool
        effects.'''
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
        # First check our limit.
        if len(self.hashX_subs) >= self.max_subs:
            raise RPCError(BAD_REQUEST, 'your address subscription limit '
                           f'{self.max_subs:,d} reached')

        # Now let the session manager check its limit
        self.session_mgr.new_subscription()
        self.hashX_subs[hashX] = alias
        return await self.address_status(hashX)

    def address_to_hashX(self, address):
        try:
            return self.coin.address_to_hashX(address)
        except Exception:
            pass
        raise RPCError(BAD_REQUEST, f'{address} is not a valid address')

    async def address_get_balance(self, address):
        '''Return the confirmed and unconfirmed balance of an address.'''
        hashX = self.address_to_hashX(address)
        return await self.get_balance(hashX)

    async def address_get_history(self, address):
        '''Return the confirmed and unconfirmed history of an address.'''
        hashX = self.address_to_hashX(address)
        return await self.confirmed_and_unconfirmed_history(hashX)

    async def address_get_mempool(self, address):
        '''Return the mempool transactions touching an address.'''
        hashX = self.address_to_hashX(address)
        return await self.unconfirmed_history(hashX)

    async def address_listunspent(self, address):
        '''Return the list of UTXOs of an address.'''
        hashX = self.address_to_hashX(address)
        return await self.hashX_listunspent(hashX)

    async def address_subscribe(self, address):
        '''Subscribe to an address.

        address: the address to subscribe to'''
        hashX = self.address_to_hashX(address)
        return await self.hashX_subscribe(hashX, address)

    async def get_balance(self, hashX):
        utxos = await self.db.all_utxos(hashX)
        confirmed = sum(utxo.value for utxo in utxos)
        unconfirmed = await self.mempool.balance_delta(hashX)
        return {'confirmed': confirmed, 'unconfirmed': unconfirmed}

    async def scripthash_get_balance(self, scripthash):
        '''Return the confirmed and unconfirmed balance of a scripthash.'''
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
        '''Return the confirmed and unconfirmed history of a scripthash.'''
        hashX = scripthash_to_hashX(scripthash)
        return await self.confirmed_and_unconfirmed_history(hashX)

    async def scripthash_get_mempool(self, scripthash):
        '''Return the mempool transactions touching a scripthash.'''
        hashX = scripthash_to_hashX(scripthash)
        return await self.unconfirmed_history(hashX)

    async def scripthash_listunspent(self, scripthash):
        '''Return the list of UTXOs of a scripthash.'''
        hashX = scripthash_to_hashX(scripthash)
        return await self.hashX_listunspent(hashX)

    async def scripthash_subscribe(self, scripthash):
        '''Subscribe to a script hash.

        scripthash: the SHA256 hash of the script to subscribe to'''
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
        '''Return a raw block header as a hexadecimal string, or as a
        dictionary with a merkle proof.'''
        height = non_negative_integer(height)
        cp_height = non_negative_integer(cp_height)
        raw_header_hex = (await self.session_mgr.raw_header(height)).hex()
        if cp_height == 0:
            return raw_header_hex
        result = {'header': raw_header_hex}
        result.update(await self._merkle_proof(cp_height, height))
        return result

    async def block_header_13(self, height):
        '''Return a raw block header as a hexadecimal string.

        height: the header's height'''
        return await self.block_header(height)

    async def block_headers(self, start_height, count, cp_height=0):
        '''Return count concatenated block headers as hex for the main chain;
        starting at start_height.

        start_height and count must be non-negative integers.  At most
        MAX_CHUNK_SIZE headers will be returned.
        '''
        start_height = non_negative_integer(start_height)
        count = non_negative_integer(count)
        cp_height = non_negative_integer(cp_height)

        max_size = self.MAX_CHUNK_SIZE
        count = min(count, max_size)
        headers, count = await self.db.read_headers(start_height, count)
        result = {'hex': headers.hex(), 'count': count, 'max': max_size}
        if count and cp_height:
            last_height = start_height + count - 1
            result.update(await self._merkle_proof(cp_height, last_height))
        return result

    async def block_headers_12(self, start_height, count):
        return await self.block_headers(start_height, count)

    async def block_get_chunk(self, index):
        '''Return a chunk of block headers as a hexadecimal string.

        index: the chunk index'''
        index = non_negative_integer(index)
        size = self.coin.CHUNK_SIZE
        start_height = index * size
        headers, _ = await self.db.read_headers(start_height, size)
        return headers.hex()

    async def block_get_header(self, height):
        '''The deserialized header at a given height.

        height: the header's height'''
        height = non_negative_integer(height)
        return await self.session_mgr.electrum_header(height)

    def is_tor(self):
        '''Try to detect if the connection is to a tor hidden service we are
        running.'''
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
        daemon_version = '{:d}.{:d}.{:d}'.format(major, minor, revision)
        for pair in [
                ('$SERVER_VERSION', torba.__version__),
                ('$DAEMON_VERSION', daemon_version),
                ('$DAEMON_SUBVERSION', network_info['subversion']),
                ('$DONATION_ADDRESS', self.env.donation_address),
        ]:
            banner = banner.replace(*pair)
        return banner

    async def donation_address(self):
        '''Return the donation address as a string, empty if there is none.'''
        return self.env.donation_address

    async def banner(self):
        '''Return the server banner text.'''
        banner = f'You are connected to an {torba.__version__} server.'

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
        '''The minimum fee a low-priority tx must pay in order to be accepted
        to the daemon's memory pool.'''
        return await self.daemon_request('relayfee')

    async def estimatefee(self, number):
        '''The estimated transaction fee per kilobyte to be paid for a
        transaction to be included within a certain number of blocks.

        number: the number of blocks
        '''
        number = non_negative_integer(number)
        return await self.daemon_request('estimatefee', number)

    async def ping(self):
        '''Serves as a connection keep-alive mechanism and for the client to
        confirm the server is still responding.
        '''
        return None

    async def server_version(self, client_name='', protocol_version=None):
        '''Returns the server version as a string.

        client_name: a string identifying the client
        protocol_version: the protocol version spoken by the client
        '''
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
            self.client = client_name[:17]

        # Find the highest common protocol version.  Disconnect if
        # that protocol version in unsupported.
        ptuple, client_min = util.protocol_version(
            protocol_version, self.PROTOCOL_MIN, self.PROTOCOL_MAX)
        if ptuple is None:
            if client_min > self.PROTOCOL_MIN:
                self.logger.info(f'client requested future protocol version '
                                 f'{util.version_string(client_min)} '
                                 f'- is your software out of date?')
            self.close_after_send = True
            raise RPCError(BAD_REQUEST,
                           f'unsupported protocol version: {protocol_version}')
        self.set_request_handlers(ptuple)

        return torba.__version__, self.protocol_version_string()

    async def transaction_broadcast(self, raw_tx):
        '''Broadcast a raw transaction to the network.

        raw_tx: the raw transaction as a hexadecimal string'''
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

    async def transaction_get(self, tx_hash, verbose=False):
        '''Return the serialized raw transaction given its hash

        tx_hash: the transaction hash as a hexadecimal string
        verbose: passed on to the daemon
        '''
        assert_tx_hash(tx_hash)
        if verbose not in (True, False):
            raise RPCError(BAD_REQUEST, f'"verbose" must be a boolean')

        return await self.daemon_request('getrawtransaction', tx_hash, verbose)

    async def _block_hash_and_tx_hashes(self, height):
        '''Returns a pair (block_hash, tx_hashes) for the main chain block at
        the given height.

        block_hash is a hexadecimal string, and tx_hashes is an
        ordered list of hexadecimal strings.
        '''
        height = non_negative_integer(height)
        hex_hashes = await self.daemon_request('block_hex_hashes', height, 1)
        block_hash = hex_hashes[0]
        block = await self.daemon_request('deserialised_block', block_hash)
        return block_hash, block['tx']

    def _get_merkle_branch(self, tx_hashes, tx_pos):
        '''Return a merkle branch to a transaction.

        tx_hashes: ordered list of hex strings of tx hashes in a block
        tx_pos: index of transaction in tx_hashes to create branch for
        '''
        hashes = [hex_str_to_hash(hash) for hash in tx_hashes]
        branch, root = self.db.merkle.branch_and_root(hashes, tx_pos)
        branch = [hash_to_hex_str(hash) for hash in branch]
        return branch

    async def transaction_merkle(self, tx_hash, height):
        '''Return the markle branch to a confirmed transaction given its hash
        and height.

        tx_hash: the transaction hash as a hexadecimal string
        height: the height of the block it is in
        '''
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
        '''Return the txid and optionally a merkle proof, given
        a block height and position in the block.
        '''
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

    def set_request_handlers(self, ptuple):
        self.protocol_tuple = ptuple

        handlers = {
            'blockchain.block.get_chunk': self.block_get_chunk,
            'blockchain.block.get_header': self.block_get_header,
            'blockchain.estimatefee': self.estimatefee,
            'blockchain.relayfee': self.relayfee,
            'blockchain.scripthash.get_balance': self.scripthash_get_balance,
            'blockchain.scripthash.get_history': self.scripthash_get_history,
            'blockchain.scripthash.get_mempool': self.scripthash_get_mempool,
            'blockchain.scripthash.listunspent': self.scripthash_listunspent,
            'blockchain.scripthash.subscribe': self.scripthash_subscribe,
            'blockchain.transaction.broadcast': self.transaction_broadcast,
            'blockchain.transaction.get': self.transaction_get,
            'blockchain.transaction.get_merkle': self.transaction_merkle,
            'server.add_peer': self.add_peer,
            'server.banner': self.banner,
            'server.donation_address': self.donation_address,
            'server.features': self.server_features_async,
            'server.peers.subscribe': self.peers_subscribe,
            'server.version': self.server_version,
        }

        if ptuple >= (1, 2):
            # New handler as of 1.2
            handlers.update({
                'mempool.get_fee_histogram':
                self.mempool.compact_fee_histogram,
                'blockchain.block.headers': self.block_headers_12,
                'server.ping': self.ping,
            })

        if ptuple >= (1, 4):
            handlers.update({
                'blockchain.block.header': self.block_header,
                'blockchain.block.headers': self.block_headers,
                'blockchain.headers.subscribe': self.headers_subscribe,
                'blockchain.transaction.id_from_pos':
                    self.transaction_id_from_pos,
            })
        elif ptuple >= (1, 3):
            handlers.update({
                'blockchain.block.header': self.block_header_13,
                'blockchain.headers.subscribe': self.headers_subscribe_True,
            })
        else:
            handlers.update({
                'blockchain.headers.subscribe': self.headers_subscribe_False,
                'blockchain.address.get_balance': self.address_get_balance,
                'blockchain.address.get_history': self.address_get_history,
                'blockchain.address.get_mempool': self.address_get_mempool,
                'blockchain.address.listunspent': self.address_listunspent,
                'blockchain.address.subscribe': self.address_subscribe,
            })

        self.request_handlers = handlers


class LocalRPC(SessionBase):
    '''A local TCP RPC server session.'''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = 'RPC'
        self.connection._max_response_size = 0

    def protocol_version_string(self):
        return 'RPC'


class DashElectrumX(ElectrumX):
    '''A TCP server that handles incoming Electrum Dash connections.'''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mns = set()

    def set_request_handlers(self, ptuple):
        super().set_request_handlers(ptuple)
        self.request_handlers.update({
            'masternode.announce.broadcast':
            self.masternode_announce_broadcast,
            'masternode.subscribe': self.masternode_subscribe,
            'masternode.list': self.masternode_list
        })

    async def notify(self, touched, height_changed):
        '''Notify the client about changes in masternode list.'''
        await super().notify(touched, height_changed)
        for mn in self.mns:
            status = await self.daemon_request('masternode_list',
                                               ['status', mn])
            await self.send_notification('masternode.subscribe',
                                         [mn, status.get(mn)])

    # Masternode command handlers
    async def masternode_announce_broadcast(self, signmnb):
        '''Pass through the masternode announce message to be broadcast
        by the daemon.

        signmnb: signed masternode broadcast message.'''
        try:
            return await self.daemon_request('masternode_broadcast',
                                             ['relay', signmnb])
        except DaemonError as e:
            error, = e.args
            message = error['message']
            self.logger.info(f'masternode_broadcast: {message}')
            raise RPCError(BAD_REQUEST, 'the masternode broadcast was '
                           f'rejected.\n\n{message}\n[{signmnb}]')

    async def masternode_subscribe(self, collateral):
        '''Returns the status of masternode.

        collateral: masternode collateral.
        '''
        result = await self.daemon_request('masternode_list',
                                           ['status', collateral])
        if result is not None:
            self.mns.add(collateral)
            return result.get(collateral)
        return None

    async def masternode_list(self, payees):
        '''
        Returns the list of masternodes.

        payees: a list of masternode payee addresses.
        '''
        if not isinstance(payees, list):
            raise RPCError(BAD_REQUEST, 'expected a list of payees')

        def get_masternode_payment_queue(mns):
            '''Returns the calculated position in the payment queue for all the
            valid masterernodes in the given mns list.

            mns: a list of masternodes information.
            '''
            now = int(datetime.datetime.utcnow().strftime("%s"))
            mn_queue = []

            # Only ENABLED masternodes are considered for the list.
            for line in mns:
                mnstat = mns[line].split()
                if mnstat[0] == 'ENABLED':
                    # if last paid time == 0
                    if int(mnstat[5]) == 0:
                        # use active seconds
                        mnstat.append(int(mnstat[4]))
                    else:
                        # now minus last paid
                        delta = now - int(mnstat[5])
                        # if > active seconds, use active seconds
                        if delta >= int(mnstat[4]):
                            mnstat.append(int(mnstat[4]))
                        # use active seconds
                        else:
                            mnstat.append(delta)
                    mn_queue.append(mnstat)
            mn_queue = sorted(mn_queue, key=lambda x: x[8], reverse=True)
            return mn_queue

        def get_payment_position(payment_queue, address):
            '''
            Returns the position of the payment list for the given address.

            payment_queue: position in the payment queue for the masternode.
            address: masternode payee address.
            '''
            position = -1
            for pos, mn in enumerate(payment_queue, start=1):
                if mn[2] == address:
                    position = pos
                    break
            return position

        # Accordingly with the masternode payment queue, a custom list
        # with the masternode information including the payment
        # position is returned.
        cache = self.session_mgr.mn_cache
        if not cache or self.session_mgr.mn_cache_height != self.db.db_height:
            full_mn_list = await self.daemon_request('masternode_list',
                                                     ['full'])
            mn_payment_queue = get_masternode_payment_queue(full_mn_list)
            mn_payment_count = len(mn_payment_queue)
            mn_list = []
            for key, value in full_mn_list.items():
                mn_data = value.split()
                mn_info = {}
                mn_info['vin'] = key
                mn_info['status'] = mn_data[0]
                mn_info['protocol'] = mn_data[1]
                mn_info['payee'] = mn_data[2]
                mn_info['lastseen'] = mn_data[3]
                mn_info['activeseconds'] = mn_data[4]
                mn_info['lastpaidtime'] = mn_data[5]
                mn_info['lastpaidblock'] = mn_data[6]
                mn_info['ip'] = mn_data[7]
                mn_info['paymentposition'] = get_payment_position(
                    mn_payment_queue, mn_info['payee'])
                mn_info['inselection'] = (
                    mn_info['paymentposition'] < mn_payment_count // 10)
                balance = await self.address_get_balance(mn_info['payee'])
                mn_info['balance'] = (sum(balance.values())
                                      / self.coin.VALUE_PER_COIN)
                mn_list.append(mn_info)
            cache.clear()
            cache.extend(mn_list)
            self.session_mgr.mn_cache_height = self.db.db_height

        # If payees is an empty list the whole masternode list is returned
        if payees:
            return [mn for mn in cache if mn['payee'] in payees]
        else:
            return cache
