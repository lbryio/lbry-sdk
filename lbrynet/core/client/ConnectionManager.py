import random
import logging
from twisted.internet import defer, reactor
from zope.interface import implements
from lbrynet import interfaces
from lbrynet import conf
from lbrynet.core.client.ClientProtocol import ClientProtocolFactory
from lbrynet.core.Error import InsufficientFundsError
from lbrynet.core import utils

log = logging.getLogger(__name__)


class PeerConnectionHandler(object):
    def __init__(self, request_creators, factory):
        self.request_creators = request_creators
        self.factory = factory
        self.connection = None


class ConnectionManager(object):
    implements(interfaces.IConnectionManager)
    MANAGE_CALL_INTERVAL_SEC = 5
    TCP_CONNECT_TIMEOUT = 15

    def __init__(self, downloader, rate_limiter,
                 primary_request_creators, secondary_request_creators):

        self.seek_head_blob_first = conf.settings['seek_head_blob_first']
        self.max_connections_per_stream = conf.settings['max_connections_per_stream']

        self.downloader = downloader
        self.rate_limiter = rate_limiter
        self._primary_request_creators = primary_request_creators
        self._secondary_request_creators = secondary_request_creators
        self._peer_connections = {}  # {Peer: PeerConnectionHandler}
        self._connections_closing = {}  # {Peer: deferred (fired when the connection is closed)}
        self._next_manage_call = None
        # a deferred that gets fired when a _manage call is set
        self._manage_deferred = None
        self.stopped = True
        log.debug("%s initialized", self._get_log_name())

    # this identifies what the connection manager is for,
    # used for logging purposes only
    def _get_log_name(self):
        out = 'Connection Manager Unknown'
        if hasattr(self.downloader, 'stream_name'):
            out = 'Connection Manager '+self.downloader.stream_name
        elif hasattr(self.downloader, 'blob_hash'):
            out = 'Connection Manager '+self.downloader.blob_hash
        return out

    def _start(self):
        self.stopped = False
        if self._next_manage_call is not None and self._next_manage_call.active() is True:
            self._next_manage_call.cancel()

    def start(self):
        log.debug("%s starting", self._get_log_name())
        self._start()
        self._next_manage_call = utils.call_later(0, self.manage)
        return defer.succeed(True)


    @defer.inlineCallbacks
    def stop(self):
        log.debug("%s stopping", self._get_log_name())
        self.stopped = True
        # wait for the current manage call to finish
        if self._manage_deferred:
            yield self._manage_deferred
        # in case we stopped between manage calls, cancel the next one
        if self._next_manage_call and self._next_manage_call.active():
            self._next_manage_call.cancel()
        self._next_manage_call = None
        yield self._close_peers()

    def num_peer_connections(self):
        return len(self._peer_connections)

    def _close_peers(self):
        def disconnect_peer(p):
            d = defer.Deferred()
            self._connections_closing[p] = d
            self._peer_connections[p].connection.disconnect()
            if p in self._peer_connections:
                del self._peer_connections[p]
            return d

        def close_connection(p):
            log.debug("%s Abruptly closing a connection to %s due to downloading being paused",
                        self._get_log_name(), p)
            if self._peer_connections[p].factory.p is not None:
                d = self._peer_connections[p].factory.p.cancel_requests()
            else:
                d = defer.succeed(True)
            d.addBoth(lambda _: disconnect_peer(p))
            return d

        closing_deferreds = [close_connection(peer) for peer in self._peer_connections.keys()]
        return defer.DeferredList(closing_deferreds)

    @defer.inlineCallbacks
    def get_next_request(self, peer, protocol):
        log.debug("%s Trying to get the next request for peer %s", self._get_log_name(), peer)
        if not peer in self._peer_connections or self.stopped is True:
            log.debug("%s The peer %s has already been told to shut down.",
                        self._get_log_name(), peer)
            defer.returnValue(False)
        requests = yield self._send_primary_requests(peer, protocol)
        have_request = any(r[1] for r in requests if r[0] is True)
        if have_request:
            yield self._send_secondary_requests(peer, protocol)
        defer.returnValue(have_request)

    def _send_primary_requests(self, peer, protocol):
        def handle_error(err):
            err.trap(InsufficientFundsError)
            self.downloader.insufficient_funds(err)
            return False

        def check_if_request_sent(request_sent, request_creator):
            if peer not in self._peer_connections:
                # This can happen if the connection is told to close
                return False
            if request_sent is False:
                if request_creator in self._peer_connections[peer].request_creators:
                    self._peer_connections[peer].request_creators.remove(request_creator)
            else:
                if not request_creator in self._peer_connections[peer].request_creators:
                    self._peer_connections[peer].request_creators.append(request_creator)
            return request_sent

        ds = []
        for p_r_c in self._primary_request_creators:
            d = p_r_c.send_next_request(peer, protocol)
            d.addErrback(handle_error)
            d.addCallback(check_if_request_sent, p_r_c)
            ds.append(d)
        return defer.DeferredList(ds, fireOnOneErrback=True)

    def _send_secondary_requests(self, peer, protocol):
        ds = [
            s_r_c.send_next_request(peer, protocol)
            for s_r_c in self._secondary_request_creators
        ]
        return defer.DeferredList(ds)

    @defer.inlineCallbacks
    def manage(self, schedule_next_call=True):
        self._manage_deferred = defer.Deferred()
        if len(self._peer_connections) < self.max_connections_per_stream:
            log.debug("%s have %d connections, looking for %d",
                        self._get_log_name(), len(self._peer_connections),
                        self.max_connections_per_stream)
            peers = yield self._get_new_peers()
            for peer in peers:
                self._connect_to_peer(peer)
        self._manage_deferred.callback(None)
        self._manage_deferred = None
        if not self.stopped and schedule_next_call:
            self._next_manage_call = utils.call_later(self.MANAGE_CALL_INTERVAL_SEC, self.manage)

    def return_shuffled_peers_not_connected_to(self, peers, new_conns_needed):
        out = [peer for peer in peers if peer not in self._peer_connections]
        random.shuffle(out)
        return out[0:new_conns_needed]

    @defer.inlineCallbacks
    def _get_new_peers(self):
        new_conns_needed = self.max_connections_per_stream - len(self._peer_connections)
        if new_conns_needed < 1:
            defer.returnValue([])
        # we always get the peer from the first request creator
        # must be a type BlobRequester...
        request_creator = self._primary_request_creators[0]
        log.debug("%s Trying to get a new peer to connect to", self._get_log_name())

        # find peers for the head blob if configured to do so
        if self.seek_head_blob_first:
            try:
                peers = yield request_creator.get_new_peers_for_head_blob()
                peers = self.return_shuffled_peers_not_connected_to(peers, new_conns_needed)
            except KeyError:
                log.warning("%s does not have a head blob", self._get_log_name())
                peers = []
        else:
            peers = []

        # we didn't find any new peers on the head blob,
        # we have to look for the first unavailable blob
        if not peers:
            peers = yield request_creator.get_new_peers_for_next_unavailable()
            peers = self.return_shuffled_peers_not_connected_to(peers, new_conns_needed)

        log.debug("%s Got a list of peers to choose from: %s",
                    self._get_log_name(), peers)
        log.debug("%s Current connections: %s",
                    self._get_log_name(), self._peer_connections.keys())
        log.debug("%s List of connection states: %s", self._get_log_name(),
                    [p_c_h.connection.state for p_c_h in self._peer_connections.values()])
        defer.returnValue(peers)

    def _connect_to_peer(self, peer):
        if self.stopped:
            return

        log.debug("%s Trying to connect to %s", self._get_log_name(), peer)
        factory = ClientProtocolFactory(peer, self.rate_limiter, self)
        factory.connection_was_made_deferred.addCallback(
                lambda c_was_made: self._peer_disconnected(c_was_made, peer))
        self._peer_connections[peer] = PeerConnectionHandler(self._primary_request_creators[:],
                                                             factory)
        connection = reactor.connectTCP(peer.host, peer.port, factory,
                                        timeout=self.TCP_CONNECT_TIMEOUT)
        self._peer_connections[peer].connection = connection

    def _peer_disconnected(self, connection_was_made, peer):
        log.debug("%s protocol disconnected for %s",
                    self._get_log_name(), peer)
        if peer in self._peer_connections:
            del self._peer_connections[peer]
        if peer in self._connections_closing:
            d = self._connections_closing[peer]
            del self._connections_closing[peer]
            d.callback(True)
        return connection_was_made


