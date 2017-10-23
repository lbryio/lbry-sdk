import binascii
import collections
import logging
import time
import datetime

from twisted.internet import defer, task
from lbrynet.core import utils

log = logging.getLogger(__name__)


class DHTHashAnnouncer(object):
    ANNOUNCE_CHECK_INTERVAL = 60
    CONCURRENT_ANNOUNCERS = 5

    """This class announces to the DHT that this peer has certain blobs"""
    STORE_RETRIES = 3

    def __init__(self, dht_node, peer_port):
        self.dht_node = dht_node
        self.peer_port = peer_port
        self.suppliers = []
        self.next_manage_call = None
        self.hash_queue = collections.deque()
        self._concurrent_announcers = 0
        self._manage_call_lc = task.LoopingCall(self.manage_lc)
        self._lock = utils.DeferredLockContextManager(defer.DeferredLock())
        self._last_checked = time.time(), self.CONCURRENT_ANNOUNCERS
        self._retries = {}
        self._total = None

    def run_manage_loop(self):
        log.info("Starting hash announcer")
        if not self._manage_call_lc.running:
            self._manage_call_lc.start(self.ANNOUNCE_CHECK_INTERVAL)

    def manage_lc(self):
        last_time, last_hashes = self._last_checked
        hashes = len(self.hash_queue)
        if hashes:
            t, h = time.time() - last_time, last_hashes - hashes
            blobs_per_second = float(h) / float(t)
            if blobs_per_second > 0:
                estimated_time_remaining = int(float(hashes) / blobs_per_second)
                remaining = str(datetime.timedelta(seconds=estimated_time_remaining))
            else:
                remaining = "unknown"
            log.info("Announcing blobs: %i blobs left to announce, %i%s complete, "
                     "est time remaining: %s", hashes + self._concurrent_announcers,
                     100 - int(100.0 * float(hashes + self._concurrent_announcers) /
                               float(self._total)), "%", remaining)
            self._last_checked = t + last_time, hashes
        else:
            self._total = 0
        if self.peer_port is not None:
            return self._announce_available_hashes()

    def stop(self):
        log.info("Stopping DHT hash announcer.")
        if self._manage_call_lc.running:
            self._manage_call_lc.stop()

    def add_supplier(self, supplier):
        self.suppliers.append(supplier)

    def immediate_announce(self, blob_hashes):
        if self.peer_port is not None:
            return self._announce_hashes(blob_hashes, immediate=True)
        else:
            return defer.succeed(False)

    def hash_queue_size(self):
        return len(self.hash_queue)

    @defer.inlineCallbacks
    def _announce_available_hashes(self):
        log.debug('Announcing available hashes')
        for supplier in self.suppliers:
            hashes = yield supplier.hashes_to_announce()
            yield self._announce_hashes(hashes)

    @defer.inlineCallbacks
    def _announce_hashes(self, hashes, immediate=False):
        if not hashes:
            defer.returnValue(None)
        if not self.dht_node.can_store:
            log.warning("Client only DHT node cannot store, skipping announce")
            defer.returnValue(None)
        log.info('Announcing %s hashes', len(hashes))
        # TODO: add a timeit decorator
        start = time.time()

        ds = []
        with self._lock:
            for h in hashes:
                announce_deferred = defer.Deferred()
                if immediate:
                    self.hash_queue.appendleft((h, announce_deferred))
                else:
                    self.hash_queue.append((h, announce_deferred))
            if not self._total:
                self._total = len(hashes)

        log.debug('There are now %s hashes remaining to be announced', self.hash_queue_size())

        @defer.inlineCallbacks
        def do_store(blob_hash, announce_d):
            if announce_d.called:
                defer.returnValue(announce_deferred.result)
            try:
                store_nodes = yield self.dht_node.announceHaveBlob(binascii.unhexlify(blob_hash))
                if not store_nodes:
                    retries = self._retries.get(blob_hash, 0)
                    retries += 1
                    self._retries[blob_hash] = retries
                    if retries <= self.STORE_RETRIES:
                        log.debug("No nodes stored %s, retrying", blob_hash)
                        result = yield do_store(blob_hash, announce_d)
                    else:
                        log.warning("No nodes stored %s", blob_hash)
                else:
                    result = store_nodes
                if not announce_d.called:
                    announce_d.callback(result)
                defer.returnValue(result)
            except Exception as err:
                if not announce_d.called:
                    announce_d.errback(err)
                raise err

        @defer.inlineCallbacks
        def announce(progress=None):
            progress = progress or {}
            if len(self.hash_queue):
                with self._lock:
                    h, announce_deferred = self.hash_queue.popleft()
                log.debug('Announcing blob %s to dht', h[:16])
                stored_to_nodes = yield do_store(h, announce_deferred)
                progress[h] = stored_to_nodes
                log.debug("Stored %s to %i peers (hashes announced by this announcer: %i)",
                          h.encode('hex')[:16],
                          len(stored_to_nodes), len(progress))

                yield announce(progress)
            else:
                with self._lock:
                    self._concurrent_announcers -= 1
            defer.returnValue(progress)

        for i in range(self._concurrent_announcers, self.CONCURRENT_ANNOUNCERS):
            self._concurrent_announcers += 1
            ds.append(announce())
        announcer_results = yield defer.DeferredList(ds)
        stored_to = {}
        for _, announced_to in announcer_results:
            stored_to.update(announced_to)
        log.info('Took %s seconds to announce %s hashes', time.time() - start, len(hashes))
        defer.returnValue(stored_to)


class DHTHashSupplier(object):
    # 1 hour is the min time hash will be reannounced
    MIN_HASH_REANNOUNCE_TIME = 60 * 60
    # conservative assumption of the time it takes to announce
    # a single hash
    SINGLE_HASH_ANNOUNCE_DURATION = 5

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
        queue_size = self.hash_announcer.hash_queue_size() + num_hashes_to_announce
        reannounce = max(self.MIN_HASH_REANNOUNCE_TIME,
                         queue_size * self.SINGLE_HASH_ANNOUNCE_DURATION)
        return time.time() + reannounce
