import binascii
import collections
import logging

from twisted.internet import defer, reactor


log = logging.getLogger(__name__)


class DHTHashAnnouncer(object):
    """This class announces to the DHT that this peer has certain blobs"""
    def __init__(self, dht_node, peer_port):
        self.dht_node = dht_node
        self.peer_port = peer_port
        self.suppliers = []
        self.next_manage_call = None
        self.hash_queue = collections.deque()
        self._concurrent_announcers = 0

    def run_manage_loop(self):

        from twisted.internet import reactor

        if self.peer_port is not None:
            self._announce_available_hashes()
        self.next_manage_call = reactor.callLater(60, self.run_manage_loop)

    def stop(self):
        log.info("Stopping %s", self)
        if self.next_manage_call is not None:
            self.next_manage_call.cancel()
            self.next_manage_call = None

    def add_supplier(self, supplier):
        self.suppliers.append(supplier)

    def immediate_announce(self, blob_hashes):
        if self.peer_port is not None:
            return self._announce_hashes(blob_hashes)
        else:
            return defer.succeed(False)

    def _announce_available_hashes(self):
        ds = []
        for supplier in self.suppliers:
            d = supplier.hashes_to_announce()
            d.addCallback(self._announce_hashes)
            ds.append(d)
        dl = defer.DeferredList(ds)
        return dl

    def _announce_hashes(self, hashes):

        ds = []

        for h in hashes:
            announce_deferred = defer.Deferred()
            ds.append(announce_deferred)
            self.hash_queue.append((h, announce_deferred))

        def announce():
            if len(self.hash_queue):
                h, announce_deferred = self.hash_queue.popleft()
                d = self.dht_node.announceHaveBlob(binascii.unhexlify(h), self.peer_port)
                d.chainDeferred(announce_deferred)
                d.addBoth(lambda _: reactor.callLater(0, announce))
            else:
                self._concurrent_announcers -= 1

        for i in range(self._concurrent_announcers, 5):
            # TODO: maybe make the 5 configurable
            self._concurrent_announcers += 1
            announce()
        return defer.DeferredList(ds)


class DHTHashSupplier(object):
    """Classes derived from this class give hashes to a hash announcer"""
    def __init__(self, announcer):
        if announcer is not None:
            announcer.add_supplier(self)
        self.hash_announcer = announcer
        self.hash_reannounce_time = 60 * 60  # 1 hour

    def hashes_to_announce(self):
        pass
