# Copyright (c) 2017-2018, Neil Booth
#
# All rights reserved.
#
# See the file "LICENCE" for information about the copyright
# and warranty status of this software.

'''Peer management.'''

import asyncio
import random
import socket
import ssl
import time
from collections import defaultdict, Counter

from torba.rpc import (Connector, RPCSession, SOCKSProxy,
                     Notification, handler_invocation,
                     SOCKSError, RPCError, TaskTimeout, TaskGroup, Event,
                     sleep, run_in_thread, ignore_after, timeout_after)
from torba.server.peer import Peer
from torba.server.util import class_logger, protocol_tuple

PEER_GOOD, PEER_STALE, PEER_NEVER, PEER_BAD = range(4)
STALE_SECS = 24 * 3600
WAKEUP_SECS = 300


class BadPeerError(Exception):
    pass


def assert_good(message, result, instance):
    if not isinstance(result, instance):
        raise BadPeerError(f'{message} returned bad result type '
                           f'{type(result).__name__}')


class PeerSession(RPCSession):
    '''An outgoing session to a peer.'''

    async def handle_request(self, request):
        # We subscribe so might be unlucky enough to get a notification...
        if (isinstance(request, Notification) and
                request.method == 'blockchain.headers.subscribe'):
            pass
        else:
            await handler_invocation(None, request)   # Raises


class PeerManager:
    '''Looks after the DB of peer network servers.

    Attempts to maintain a connection with up to 8 peers.
    Issues a 'peers.subscribe' RPC to them and tells them our data.
    '''
    def __init__(self, env, db):
        self.logger = class_logger(__name__, self.__class__.__name__)
        # Initialise the Peer class
        Peer.DEFAULT_PORTS = env.coin.PEER_DEFAULT_PORTS
        self.env = env
        self.db = db

        # Our clearnet and Tor Peers, if any
        sclass = env.coin.SESSIONCLS
        self.myselves = [Peer(ident.host, sclass.server_features(env), 'env')
                         for ident in env.identities]
        self.server_version_args = sclass.server_version_args()
        # Peers have one entry per hostname.  Once connected, the
        # ip_addr property is either None, an onion peer, or the
        # IP address that was connected to.  Adding a peer will evict
        # any other peers with the same host name or IP address.
        self.peers = set()
        self.permit_onion_peer_time = time.time()
        self.proxy = None
        self.group = TaskGroup()

    def _my_clearnet_peer(self):
        '''Returns the clearnet peer representing this server, if any.'''
        clearnet = [peer for peer in self.myselves if not peer.is_tor]
        return clearnet[0] if clearnet else None

    def _set_peer_statuses(self):
        '''Set peer statuses.'''
        cutoff = time.time() - STALE_SECS
        for peer in self.peers:
            if peer.bad:
                peer.status = PEER_BAD
            elif peer.last_good > cutoff:
                peer.status = PEER_GOOD
            elif peer.last_good:
                peer.status = PEER_STALE
            else:
                peer.status = PEER_NEVER

    def _features_to_register(self, peer, remote_peers):
        '''If we should register ourselves to the remote peer, which has
        reported the given list of known peers, return the clearnet
        identity features to register, otherwise None.
        '''
        # Announce ourself if not present.  Don't if disabled, we
        # are a non-public IP address, or to ourselves.
        if not self.env.peer_announce or peer in self.myselves:
            return None
        my = self._my_clearnet_peer()
        if not my or not my.is_public:
            return None
        # Register if no matches, or ports have changed
        for peer in my.matches(remote_peers):
            if peer.tcp_port == my.tcp_port and peer.ssl_port == my.ssl_port:
                return None
        return my.features

    def _permit_new_onion_peer(self):
        '''Accept a new onion peer only once per random time interval.'''
        now = time.time()
        if now < self.permit_onion_peer_time:
            return False
        self.permit_onion_peer_time = now + random.randrange(0, 1200)
        return True

    async def _import_peers(self):
        '''Import hard-coded peers from a file or the coin defaults.'''
        imported_peers = self.myselves.copy()
        # Add the hard-coded ones unless only reporting ourself
        if self.env.peer_discovery != self.env.PD_SELF:
            imported_peers.extend(Peer.from_real_name(real_name, 'coins.py')
                                  for real_name in self.env.coin.PEERS)
        await self._note_peers(imported_peers, limit=None)

    async def _detect_proxy(self):
        '''Detect a proxy if we don't have one and some time has passed since
        the last attempt.

        If found self.proxy is set to a SOCKSProxy instance, otherwise
        None.
        '''
        host = self.env.tor_proxy_host
        if self.env.tor_proxy_port is None:
            ports = [9050, 9150, 1080]
        else:
            ports = [self.env.tor_proxy_port]
        while True:
            self.logger.info(f'trying to detect proxy on "{host}" '
                             f'ports {ports}')
            proxy = await SOCKSProxy.auto_detect_host(host, ports, None)
            if proxy:
                self.proxy = proxy
                self.logger.info(f'detected {proxy}')
                return
            self.logger.info('no proxy detected, will try later')
            await sleep(900)

    async def _note_peers(self, peers, limit=2, check_ports=False,
                          source=None):
        '''Add a limited number of peers that are not already present.'''
        new_peers = []
        for peer in peers:
            if not peer.is_public or (peer.is_tor and not self.proxy):
                continue

            matches = peer.matches(self.peers)
            if not matches:
                new_peers.append(peer)
            elif check_ports:
                for match in matches:
                    if match.check_ports(peer):
                        self.logger.info(f'ports changed for {peer}')
                        match.retry_event.set()

        if new_peers:
            source = source or new_peers[0].source
            if limit:
                random.shuffle(new_peers)
                use_peers = new_peers[:limit]
            else:
                use_peers = new_peers
            for peer in use_peers:
                self.logger.info(f'accepted new peer {peer} from {source}')
                peer.retry_event = Event()
                self.peers.add(peer)
                await self.group.spawn(self._monitor_peer(peer))

    async def _monitor_peer(self, peer):
        # Stop monitoring if we were dropped (a duplicate peer)
        while peer in self.peers:
            if await self._should_drop_peer(peer):
                self.peers.discard(peer)
                break
            # Figure out how long to sleep before retrying.  Retry a
            # good connection when it is about to turn stale, otherwise
            # exponentially back off retries.
            if peer.try_count == 0:
                pause = STALE_SECS - WAKEUP_SECS * 2
            else:
                pause = WAKEUP_SECS * 2 ** peer.try_count
            async with ignore_after(pause):
                await peer.retry_event.wait()
                peer.retry_event.clear()

    async def _should_drop_peer(self, peer):
        peer.try_count += 1
        is_good = False
        for kind, port in peer.connection_port_pairs():
            peer.last_try = time.time()

            kwargs = {}
            if kind == 'SSL':
                kwargs['ssl'] = ssl.SSLContext(ssl.PROTOCOL_TLS)

            host = self.env.cs_host(for_rpc=False)
            if isinstance(host, list):
                host = host[0]

            if self.env.force_proxy or peer.is_tor:
                if not self.proxy:
                    return
                kwargs['proxy'] = self.proxy
                kwargs['resolve'] = not peer.is_tor
            elif host:
                # Use our listening Host/IP for outgoing non-proxy
                # connections so our peers see the correct source.
                kwargs['local_addr'] = (host, None)

            peer_text = f'[{peer}:{port} {kind}]'
            try:
                async with timeout_after(120 if peer.is_tor else 30):
                    async with Connector(PeerSession, peer.host, port,
                                         **kwargs) as session:
                        await self._verify_peer(session, peer)
                is_good = True
                break
            except BadPeerError as e:
                self.logger.error(f'{peer_text} marking bad: ({e})')
                peer.mark_bad()
                break
            except RPCError as e:
                self.logger.error(f'{peer_text} RPC error: {e.message} '
                                  f'({e.code})')
            except (OSError, SOCKSError, ConnectionError, TaskTimeout) as e:
                self.logger.info(f'{peer_text} {e}')

        if is_good:
            now = time.time()
            elapsed = now - peer.last_try
            self.logger.info(f'{peer_text} verified in {elapsed:.1f}s')
            peer.try_count = 0
            peer.last_good = now
            peer.source = 'peer'
            # At most 2 matches if we're a host name, potentially
            # several if we're an IP address (several instances
            # can share a NAT).
            matches = peer.matches(self.peers)
            for match in matches:
                if match.ip_address:
                    if len(matches) > 1:
                        self.peers.remove(match)
                        # Force the peer's monitoring task to exit
                        match.retry_event.set()
                elif peer.host in match.features['hosts']:
                    match.update_features_from_peer(peer)
        else:
            # Forget the peer if long-term unreachable
            if peer.last_good and not peer.bad:
                try_limit = 10
            else:
                try_limit = 3
            if peer.try_count >= try_limit:
                desc = 'bad' if peer.bad else 'unreachable'
                self.logger.info(f'forgetting {desc} peer: {peer}')
                return True
        return False

    async def _verify_peer(self, session, peer):
        if not peer.is_tor:
            address = session.peer_address()
            if address:
                peer.ip_addr = address[0]

        # server.version goes first
        message = 'server.version'
        result = await session.send_request(message, self.server_version_args)
        assert_good(message, result, list)

        # Protocol version 1.1 returns a pair with the version first
        if len(result) != 2 or not all(isinstance(x, str) for x in result):
            raise BadPeerError(f'bad server.version result: {result}')
        server_version, protocol_version = result
        peer.server_version = server_version
        peer.features['server_version'] = server_version
        ptuple = protocol_tuple(protocol_version)

        async with TaskGroup() as g:
            await g.spawn(self._send_headers_subscribe(session, peer, ptuple))
            await g.spawn(self._send_server_features(session, peer))
            await g.spawn(self._send_peers_subscribe(session, peer))

    async def _send_headers_subscribe(self, session, peer, ptuple):
        message = 'blockchain.headers.subscribe'
        result = await session.send_request(message)
        assert_good(message, result, dict)

        our_height = self.db.db_height
        if ptuple < (1, 3):
            their_height = result.get('block_height')
        else:
            their_height = result.get('height')
        if not isinstance(their_height, int):
            raise BadPeerError(f'invalid height {their_height}')
        if abs(our_height - their_height) > 5:
            raise BadPeerError(f'bad height {their_height:,d} '
                               f'(ours: {our_height:,d})')

        # Check prior header too in case of hard fork.
        check_height = min(our_height, their_height)
        raw_header = await self.db.raw_header(check_height)
        if ptuple >= (1, 4):
            ours = raw_header.hex()
            message = 'blockchain.block.header'
            theirs = await session.send_request(message, [check_height])
            assert_good(message, theirs, str)
            if ours != theirs:
                raise BadPeerError(f'our header {ours} and '
                                   f'theirs {theirs} differ')
        else:
            ours = self.env.coin.electrum_header(raw_header, check_height)
            ours = ours.get('prev_block_hash')
            message = 'blockchain.block.get_header'
            theirs = await session.send_request(message, [check_height])
            assert_good(message, theirs, dict)
            theirs = theirs.get('prev_block_hash')
            if ours != theirs:
                raise BadPeerError(f'our header hash {ours} and '
                                   f'theirs {theirs} differ')

    async def _send_server_features(self, session, peer):
        message = 'server.features'
        features = await session.send_request(message)
        assert_good(message, features, dict)
        hosts = [host.lower() for host in features.get('hosts', {})]
        if self.env.coin.GENESIS_HASH != features.get('genesis_hash'):
            raise BadPeerError('incorrect genesis hash')
        elif peer.host.lower() in hosts:
            peer.update_features(features)
        else:
            raise BadPeerError(f'not listed in own hosts list {hosts}')

    async def _send_peers_subscribe(self, session, peer):
        message = 'server.peers.subscribe'
        raw_peers = await session.send_request(message)
        assert_good(message, raw_peers, list)

        # Check the peers list we got from a remote peer.
        # Each is expected to be of the form:
        #    [ip_addr, hostname, ['v1.0', 't51001', 's51002']]
        # Call add_peer if the remote doesn't appear to know about us.
        try:
            real_names = [' '.join([u[1]] + u[2]) for u in raw_peers]
            peers = [Peer.from_real_name(real_name, str(peer))
                     for real_name in real_names]
        except Exception:
            raise BadPeerError('bad server.peers.subscribe response')

        await self._note_peers(peers)
        features = self._features_to_register(peer, peers)
        if not features:
            return
        self.logger.info(f'registering ourself with {peer}')
        # We only care to wait for the response
        await session.send_request('server.add_peer', [features])

    #
    # External interface
    #
    async def discover_peers(self):
        '''Perform peer maintenance.  This includes

          1) Forgetting unreachable peers.
          2) Verifying connectivity of new peers.
          3) Retrying old peers at regular intervals.
        '''
        if self.env.peer_discovery != self.env.PD_ON:
            self.logger.info('peer discovery is disabled')
            return

        self.logger.info(f'beginning peer discovery. Force use of '
                         f'proxy: {self.env.force_proxy}')
        forever = Event()
        async with self.group as group:
            await group.spawn(forever.wait())
            await group.spawn(self._detect_proxy())
            await group.spawn(self._import_peers())
            # Consume tasks as they complete, logging unexpected failures
            async for task in group:
                if not task.cancelled():
                    try:
                        task.result()
                    except Exception:
                        self.logger.exception('task failed unexpectedly')

    def info(self):
        '''The number of peers.'''
        self._set_peer_statuses()
        counter = Counter(peer.status for peer in self.peers)
        return {
            'bad': counter[PEER_BAD],
            'good': counter[PEER_GOOD],
            'never': counter[PEER_NEVER],
            'stale': counter[PEER_STALE],
            'total': len(self.peers),
        }

    async def add_localRPC_peer(self, real_name):
        '''Add a peer passed by the admin over LocalRPC.'''
        await self._note_peers([Peer.from_real_name(real_name, 'RPC')])

    async def on_add_peer(self, features, source_info):
        '''Add a peer (but only if the peer resolves to the source).'''
        if not source_info:
            self.logger.info('ignored add_peer request: no source info')
            return False
        source = source_info[0]
        peers = Peer.peers_from_features(features, source)
        if not peers:
            self.logger.info('ignored add_peer request: no peers given')
            return False

        # Just look at the first peer, require it
        peer = peers[0]
        host = peer.host
        if peer.is_tor:
            permit = self._permit_new_onion_peer()
            reason = 'rate limiting'
        else:
            getaddrinfo = asyncio.get_event_loop().getaddrinfo
            try:
                infos = await getaddrinfo(host, 80, type=socket.SOCK_STREAM)
            except socket.gaierror:
                permit = False
                reason = 'address resolution failure'
            else:
                permit = any(source == info[-1][0] for info in infos)
                reason = 'source-destination mismatch'

        if permit:
            self.logger.info(f'accepted add_peer request from {source} '
                             f'for {host}')
            await self._note_peers([peer], check_ports=True)
        else:
            self.logger.warning(f'rejected add_peer request from {source} '
                                f'for {host} ({reason})')

        return permit

    def on_peers_subscribe(self, is_tor):
        '''Returns the server peers as a list of (ip, host, details) tuples.

        We return all peers we've connected to in the last day.
        Additionally, if we don't have onion routing, we return a few
        hard-coded onion servers.
        '''
        cutoff = time.time() - STALE_SECS
        recent = [peer for peer in self.peers
                  if peer.last_good > cutoff and
                  not peer.bad and peer.is_public]
        onion_peers = []

        # Always report ourselves if valid (even if not public)
        peers = set(myself for myself in self.myselves
                    if myself.last_good > cutoff)

        # Bucket the clearnet peers and select up to two from each
        buckets = defaultdict(list)
        for peer in recent:
            if peer.is_tor:
                onion_peers.append(peer)
            else:
                buckets[peer.bucket()].append(peer)
        for bucket_peers in buckets.values():
            random.shuffle(bucket_peers)
            peers.update(bucket_peers[:2])

        # Add up to 20% onion peers (but up to 10 is OK anyway)
        random.shuffle(onion_peers)
        max_onion = 50 if is_tor else max(10, len(peers) // 4)

        peers.update(onion_peers[:max_onion])

        return [peer.to_tuple() for peer in peers]

    def proxy_peername(self):
        '''Return the peername of the proxy, if there is a proxy, otherwise
        None.'''
        return self.proxy.peername if self.proxy else None

    def rpc_data(self):
        '''Peer data for the peers RPC method.'''
        self._set_peer_statuses()
        descs = ['good', 'stale', 'never', 'bad']

        def peer_data(peer):
            data = peer.serialize()
            data['status'] = descs[peer.status]
            return data

        def peer_key(peer):
            return (peer.bad, -peer.last_good)

        return [peer_data(peer) for peer in sorted(self.peers, key=peer_key)]
