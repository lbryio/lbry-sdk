import binascii
import collections
import logging
import time

from twisted.internet import defer, reactor


log = logging.getLogger(__name__)


class DequeSet(object):
    def __init__(self):
        self._queue = collections.deque()
        self._items = set()

    def append(self, item):
        if item in self._items:
            return
        self._queue.append(item)
        self._items.add(item)

    def popleft(self):
        item = self._queue.popleft()
        self._items.remove(item)
        return item

    def __len__(self):
        return len(self._queue)

    def __nonzero__(self):
        return self._queue.__nonzero__()


class DHTHashAnnouncer(object):
    """This class announces to the DHT that this peer has certain blobs"""
    def __init__(self, dht_node, peer_port):
        self.dht_node = dht_node
        self.peer_port = peer_port
        self.suppliers = []
        self.next_manage_call = None
        self.hash_queue = DequeSet()
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

    def immediate_announce(self, blob_hashes, supplier):
        if self.peer_port is not None:
            return self._announce_hashes(blob_hashes, supplier)
        else:
            return defer.succeed(False)

    def _announce_available_hashes(self):
        log.debug('Announcing available hashes')
        ds = []
        for supplier in self.suppliers:
            d = supplier.hashes_to_announce()
            d.addCallback(self._announce_hashes, supplier)
            ds.append(d)
        dl = defer.DeferredList(ds)
        return dl

    def _announce_hashes(self, hashes, supplier):
        if not hashes:
            return
        log.debug('Announcing %s hashes', len(hashes))
        # TODO: add a timeit decorator
        start = time.time()
        ds = []

        for h in hashes:
            announce_deferred = defer.Deferred()
            ds.append(announce_deferred)
            self.hash_queue.append((h, announce_deferred))
        log.debug('There are now %s hashes remaining to be announced', len(self.hash_queue))

        def announce():
            if self.hash_queue:
                h, announce_deferred = self.hash_queue.popleft()
                log.debug('Announcing blob %s to dht', h)
                d = self.dht_node.announceHaveBlob(binascii.unhexlify(h), self.peer_port)
                d.addCallback(lambda _: supplier.on_hash_announced(h))
                d.chainDeferred(announce_deferred)
                d.addBoth(lambda _: reactor.callLater(0, announce))
            else:
                self._concurrent_announcers -= 1

        for i in range(self._concurrent_announcers, 5):
            # TODO: maybe make the 5 configurable
            self._concurrent_announcers += 1
            announce()
        d = defer.DeferredList(ds)
        d.addCallback(lambda _: log.debug('Took %s seconds to announce %s hashes',
                                          time.time() - start, len(hashes)))
        return d


class DHTHashSupplier(object):
    """Classes derived from this class give hashes to a hash announcer"""
    def __init__(self, announcer):
        if announcer is not None:
            announcer.add_supplier(self)
        self.hash_announcer = announcer
        self.hash_reannounce_time = 60 * 60  # 1 hour

    def hashes_to_announce(self):
        pass
