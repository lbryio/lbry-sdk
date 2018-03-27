import binascii
import logging

from twisted.internet import defer, task
from lbrynet.core import utils
from lbrynet import conf

log = logging.getLogger(__name__)


class DHTHashAnnouncer(object):
    def __init__(self, dht_node, storage, concurrent_announcers=None):
        self.dht_node = dht_node
        self.storage = storage
        self.clock = dht_node.clock
        self.peer_port = dht_node.peerPort
        self.hash_queue = []
        self.concurrent_announcers = concurrent_announcers or conf.settings['concurrent_announcers']
        self._manage_lc = task.LoopingCall(self.manage)
        self._manage_lc.clock = self.clock

    def start(self):
        self._manage_lc.start(30)

    def stop(self):
        if self._manage_lc.running:
            self._manage_lc.stop()

    @defer.inlineCallbacks
    def do_store(self, blob_hash):
        storing_node_ids = yield self.dht_node.announceHaveBlob(binascii.unhexlify(blob_hash))
        now = self.clock.seconds()
        if storing_node_ids:
            result = (now, storing_node_ids)
            yield self.storage.update_last_announced_blob(blob_hash, now)
            log.debug("Stored %s to %i peers", blob_hash[:16], len(storing_node_ids))
        else:
            result = (None, [])
        self.hash_queue.remove(blob_hash)
        defer.returnValue(result)

    def _show_announce_progress(self, size, start):
        queue_size = len(self.hash_queue)
        average_blobs_per_second = float(size - queue_size) / (self.clock.seconds() - start)
        log.info("Announced %i/%i blobs, %f blobs per second", size - queue_size, size, average_blobs_per_second)

    @defer.inlineCallbacks
    def immediate_announce(self, blob_hashes):
        blob_hashes = [b for b in blob_hashes if b not in self.hash_queue]
        self.hash_queue.extend(blob_hashes)

        log.info("Announcing %i blobs", len(self.hash_queue))
        start = self.clock.seconds()
        progress_lc = task.LoopingCall(self._show_announce_progress, len(self.hash_queue), start)
        progress_lc.start(60, now=False)
        s = defer.DeferredSemaphore(self.concurrent_announcers)
        results = yield utils.DeferredDict({blob_hash: s.run(self.do_store, blob_hash) for blob_hash in blob_hashes})
        now = self.clock.seconds()

        progress_lc.stop()

        announced_to = [blob_hash for blob_hash in results if results[blob_hash][0]]
        if len(announced_to) != len(results):
            log.debug("Failed to announce %i blobs", len(results) - len(announced_to))
        if announced_to:
            log.info('Took %s seconds to announce %i of %i attempted hashes (%f hashes per second)',
                     now - start, len(blob_hashes), len(announced_to),
                     int(float(len(blob_hashes)) / float(now - start)))
        defer.returnValue(results)

    @defer.inlineCallbacks
    def manage(self):
        need_reannouncement = yield self.storage.get_blobs_to_announce()
        if need_reannouncement:
            yield self.immediate_announce(need_reannouncement)
        else:
            log.debug("Nothing to announce")
