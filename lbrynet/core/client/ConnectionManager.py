import logging
from twisted.internet import defer
from zope.interface import implements
from lbrynet import interfaces
from lbrynet.conf import MAX_CONNECTIONS_PER_STREAM
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

    def __init__(self, downloader, rate_limiter, primary_request_creators, secondary_request_creators):
        self.downloader = downloader
        self.rate_limiter = rate_limiter
        self._primary_request_creators = primary_request_creators
        self._secondary_request_creators = secondary_request_creators
        self._peer_connections = {}  # {Peer: PeerConnectionHandler}
        self._connections_closing = {}  # {Peer: deferred (fired when the connection is closed)}
        self._next_manage_call = None

    def start(self):
        from twisted.internet import reactor

        if self._next_manage_call is not None and self._next_manage_call.active() is True:
            self._next_manage_call.cancel()
        self._next_manage_call = reactor.callLater(0, self._manage)
        return defer.succeed(True)

    def stop(self):
        if self._next_manage_call is not None and self._next_manage_call.active() is True:
            self._next_manage_call.cancel()
        self._next_manage_call = None
        closing_deferreds = []
        for peer in self._peer_connections.keys():

            def close_connection(p):
                log.info("Abruptly closing a connection to %s due to downloading being paused",
                         str(p))

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

    def get_next_request(self, peer, protocol):

        log.debug("Trying to get the next request for peer %s", str(peer))

        if not peer in self._peer_connections:
            log.debug("The peer has already been told to shut down.")
            return defer.succeed(False)

        def handle_error(err):
            if err.check(InsufficientFundsError):
                self.downloader.insufficient_funds()
                return False
            else:
                return err

        def check_if_request_sent(request_sent, request_creator):
            if request_sent is False:
                if request_creator in self._peer_connections[peer].request_creators:
                    self._peer_connections[peer].request_creators.remove(request_creator)
            else:
                if not request_creator in self._peer_connections[peer].request_creators:
                    self._peer_connections[peer].request_creators.append(request_creator)
            return request_sent

        def check_requests(requests):
            have_request = True in [r[1] for r in requests if r[0] is True]
            return have_request

        def get_secondary_requests_if_necessary(have_request):
            if have_request is True:
                ds = []
                for s_r_c in self._secondary_request_creators:
                    d = s_r_c.send_next_request(peer, protocol)
                    ds.append(d)
                dl = defer.DeferredList(ds)
            else:
                dl = defer.succeed(None)
            dl.addCallback(lambda _: have_request)
            return dl

        ds = []

        for p_r_c in self._primary_request_creators:
            d = p_r_c.send_next_request(peer, protocol)
            d.addErrback(handle_error)
            d.addCallback(check_if_request_sent, p_r_c)
            ds.append(d)

        dl = defer.DeferredList(ds, fireOnOneErrback=True)
        dl.addCallback(check_requests)
        dl.addCallback(get_secondary_requests_if_necessary)
        return dl

    def protocol_disconnected(self, peer, protocol):
        if peer in self._peer_connections:
            del self._peer_connections[peer]
        if peer in self._connections_closing:
            d = self._connections_closing[peer]
            del self._connections_closing[peer]
            d.callback(True)

    def _rank_request_creator_connections(self):
        """
        @return: an ordered list of our request creators, ranked according to which has the least number of
            connections open that it likes
        """
        def count_peers(request_creator):
            return len([p for p in self._peer_connections.itervalues() if request_creator in p.request_creators])

        return sorted(self._primary_request_creators, key=count_peers)

    def _connect_to_peer(self, peer):

        from twisted.internet import reactor

        if peer is not None:
            log.debug("Trying to connect to %s", str(peer))
            factory = ClientProtocolFactory(peer, self.rate_limiter, self)
            self._peer_connections[peer] = PeerConnectionHandler(self._primary_request_creators[:],
                                                                 factory)
            connection = reactor.connectTCP(peer.host, peer.port, factory)
            self._peer_connections[peer].connection = connection

    def _manage(self):

        from twisted.internet import reactor

        def get_new_peers(request_creators):
            log.debug("Trying to get a new peer to connect to")
            if len(request_creators) > 0:
                log.debug("Got a creator to check: %s", str(request_creators[0]))
                d = request_creators[0].get_new_peers()
                d.addCallback(lambda h: h if h is not None else get_new_peers(request_creators[1:]))
                return d
            else:
                return defer.succeed(None)

        def pick_best_peer(peers):
            # TODO: Eventually rank them based on past performance/reputation. For now
            # TODO: just pick the first to which we don't have an open connection
            log.debug("Got a list of peers to choose from: %s", str(peers))
            if peers is None:
                return None
            for peer in peers:
                if not peer in self._peer_connections:
                    log.debug("Got a good peer. Returning peer %s", str(peer))
                    return peer
            log.debug("Couldn't find a good peer to connect to")
            return None

        if len(self._peer_connections) < MAX_CONNECTIONS_PER_STREAM:
            ordered_request_creators = self._rank_request_creator_connections()
            d = get_new_peers(ordered_request_creators)
            d.addCallback(pick_best_peer)
            d.addCallback(self._connect_to_peer)

        self._next_manage_call = reactor.callLater(1, self._manage)