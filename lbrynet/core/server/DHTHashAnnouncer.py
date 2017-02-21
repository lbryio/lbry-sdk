import binascii
import collections
import logging
import time

from twisted.internet import defer
from lbrynet.core import utils

log = logging.getLogger(__name__)


class DHTHashAnnouncer(object):
    ANNOUNCE_CHECK_INTERVAL = 60
    CONCURRENT_ANNOUNCERS = 5

    """This class announces to the DHT that this peer has certain blobs"""
    def __init__(self, dht_node, peer_port):
        self.dht_node = dht_node
        self.peer_port = peer_port
        self.suppliers = []
        self.next_manage_call = None
        self.hash_queue = collections.deque()
        self._concurrent_announcers = 0

    def run_manage_loop(self):
        if self.peer_port is not None:
            self._announce_available_hashes()
        self.next_manage_call = utils.call_later(self.ANNOUNCE_CHECK_INTERVAL, self.run_manage_loop)

    def stop(self):
        log.info("Stopping %s", self)
        if self.next_manage_call is not None:
            self.next_manage_call.cancel()
            self.next_manage_call = None

    def add_supplier(self, supplier):
        self.suppliers.append(supplier)

    def immediate_announce(self, blob_hashes):
        if self.peer_port is not None:
            return self._announce_hashes(blob_hashes, immediate=True)
        else:
            return defer.succeed(False)

    def hash_queue_size(self):
        return len(self.hash_queue)

    def _announce_available_hashes(self):
        log.debug('Announcing available hashes')
        ds = []
        for supplier in self.suppliers:
            d = supplier.hashes_to_announce()
            d.addCallback(self._announce_hashes)
            ds.append(d)
        dl = defer.DeferredList(ds)
        return dl

    def _announce_hashes(self, hashes, immediate=False):
        if not hashes:
            return
        log.debug('Announcing %s hashes', len(hashes))
        # TODO: add a timeit decorator
        start = time.time()
        ds = []

        for h in hashes:
            announce_deferred = defer.Deferred()
            ds.append(announce_deferred)
            if immediate:
                self.hash_queue.appendleft((h, announce_deferred))
            else:
                self.hash_queue.append((h, announce_deferred))
        log.debug('There are now %s hashes remaining to be announced', self.hash_queue_size())

        def announce():
            if len(self.hash_queue):
                h, announce_deferred = self.hash_queue.popleft()
                log.debug('Announcing blob %s to dht', h)
                d = self.dht_node.announceHaveBlob(binascii.unhexlify(h), self.peer_port)
                d.chainDeferred(announce_deferred)
                d.addBoth(lambda _: utils.call_later(0, announce))
            else:
                self._concurrent_announcers -= 1

        for i in range(self._concurrent_announcers, self.CONCURRENT_ANNOUNCERS):
            self._concurrent_announcers += 1
            announce()
        d = defer.DeferredList(ds)
        d.addCallback(lambda _: log.debug('Took %s seconds to announce %s hashes',
                                          time.time() - start, len(hashes)))
        return d


class DHTHashSupplier(object):
    # 1 hour is the min time hash will be reannounced
    MIN_HASH_REANNOUNCE_TIME = 60*60
    # conservative assumption of the time it takes to announce
    # a single hash
    SINGLE_HASH_ANNOUNCE_DURATION = 1

    """Classes derived from this class give hashes to a hash announcer"""
    def __init__(self, announcer):
        if announcer is not None:
            announcer.add_supplier(self)
        self.hash_announcer = announcer

    def hashes_to_announce(self):
        pass


    def get_next_announce_time(self, num_hashes_to_announce=1):
        """
        Hash reannounce time is set to current time + MIN_HASH_REANNOUNCE_TIME,
        unless we are announcing a lot of hashes at once which could cause the
        the announce queue to pile up.  To prevent pile up, reannounce
        only after a conservative estimate of when it will finish
        to announce all the hashes.

        Args:
            num_hashes_to_announce: number of hashes that will be added to the queue
        Returns:
            timestamp for next announce time
        """
        queue_size = self.hash_announcer.hash_queue_size()+num_hashes_to_announce
        reannounce = max(self.MIN_HASH_REANNOUNCE_TIME,
                            queue_size*self.SINGLE_HASH_ANNOUNCE_DURATION)
        return time.time() + reannounce


