import logging
from twisted.internet import defer
from zope.interface import implements
from lbrynet import interfaces
from lbrynet import conf
from lbrynet.core.client.ClientProtocol import ClientProtocolFactory
from lbrynet.core.Error import InsufficientFundsError


log = logging.getLogger(__name__)


class PeerConnectionHandler(object):
    def __init__(self, request_creators, factory):
        self.request_creators = request_creators
        self.factory = factory
        self.connection = None


class ConnectionManager(object):
    implements(interfaces.IConnectionManager)

    def __init__(self, downloader, rate_limiter,
                 primary_request_creators, secondary_request_creators):
        self.downloader = downloader
        self.rate_limiter = rate_limiter
        self._primary_request_creators = primary_request_creators
        self._secondary_request_creators = secondary_request_creators
        self._peer_connections = {}  # {Peer: PeerConnectionHandler}
        self._connections_closing = {}  # {Peer: deferred (fired when the connection is closed)}
        self._next_manage_call = None
        self.stopped = True

    def start(self):
        from twisted.internet import reactor

        self.stopped = False

        if self._next_manage_call is not None and self._next_manage_call.active() is True:
            self._next_manage_call.cancel()
        self._next_manage_call = reactor.callLater(0, self._manage)
        return defer.succeed(True)

    def stop(self):
        self.stopped = True
        if self._next_manage_call is not None and self._next_manage_call.active() is True:
            self._next_manage_call.cancel()
        self._next_manage_call = None
        closing_deferreds = []
        for peer in self._peer_connections.keys():

            def close_connection(p):
                log.info(
                    "Abruptly closing a connection to %s due to downloading being paused", p)

                if self._peer_connections[p].factory.p is not None:
                    d = self._peer_connections[p].factory.p.cancel_requests()
                else:
                    d = defer.succeed(True)

                def disconnect_peer():
                    d = defer.Deferred()
                    self._connections_closing[p] = d
                    self._peer_connections[p].connection.disconnect()
                    if p in self._peer_connections:
                        del self._peer_connections[p]
                    return d

                d.addBoth(lambda _: disconnect_peer())
                return d

            closing_deferreds.append(close_connection(peer))
        return defer.DeferredList(closing_deferreds)

    @defer.inlineCallbacks
    def get_next_request(self, peer, protocol):
        log.debug("Trying to get the next request for peer %s", peer)
        if not peer in self._peer_connections or self.stopped is True:
            log.debug("The peer has already been told to shut down.")
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

    def protocol_disconnected(self, peer, protocol):
        if peer in self._peer_connections:
            del self._peer_connections[peer]
        if peer in self._connections_closing:
            d = self._connections_closing[peer]
            del self._connections_closing[peer]
            d.callback(True)

    def _rank_request_creator_connections(self):
        """Returns an ordered list of our request creators, ranked according
        to which has the least number of connections open that it
        likes
        """
        def count_peers(request_creator):
            return len([
                p for p in self._peer_connections.itervalues()
                if request_creator in p.request_creators])

        return sorted(self._primary_request_creators, key=count_peers)

    def _connect_to_peer(self, peer):
        if peer is None or self.stopped:
            return

        from twisted.internet import reactor

        log.debug("Trying to connect to %s", peer)
        factory = ClientProtocolFactory(peer, self.rate_limiter, self)
        self._peer_connections[peer] = PeerConnectionHandler(self._primary_request_creators[:],
                                                             factory)
        connection = reactor.connectTCP(peer.host, peer.port, factory)
        self._peer_connections[peer].connection = connection

    @defer.inlineCallbacks
    def _manage(self):
        from twisted.internet import reactor
        if len(self._peer_connections) < conf.settings.max_connections_per_stream:
            try:
                ordered_request_creators = self._rank_request_creator_connections()
                peers = yield self._get_new_peers(ordered_request_creators)
                peer = self._pick_best_peer(peers)
                yield self._connect_to_peer(peer)
            except Exception:
                # log this otherwise it will just end up as an unhandled error in deferred
                log.exception('Something bad happened picking a peer')
        self._next_manage_call = reactor.callLater(1, self._manage)

    @defer.inlineCallbacks
    def _get_new_peers(self, request_creators):
        log.debug("Trying to get a new peer to connect to")
        if not request_creators:
            defer.returnValue(None)
        log.debug("Got a creator to check: %s", request_creators[0])
        new_peers = yield request_creators[0].get_new_peers()
        if not new_peers:
            new_peers = yield self._get_new_peers(request_creators[1:])
        defer.returnValue(new_peers)

    def _pick_best_peer(self, peers):
        # TODO: Eventually rank them based on past performance/reputation. For now
        # TODO: just pick the first to which we don't have an open connection
        log.debug("Got a list of peers to choose from: %s", peers)
        if peers is None:
            return None
        for peer in peers:
            if not peer in self._peer_connections:
                log.debug("Got a good peer. Returning peer %s", peer)
                return peer
        log.debug("Couldn't find a good peer to connect to")
        return None
