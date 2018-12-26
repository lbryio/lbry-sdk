import logging
import treq
from random import choice
from twisted.internet import defer, task
from twisted.internet.error import ConnectingCancelledError
from twisted.web._newclient import ResponseNeverReceived

from lbrynet.utils import DeferredDict
from lbrynet.error import DownloadCancelledError

log = logging.getLogger(__name__)


class HTTPBlobDownloader:
    '''
    A downloader that is able to get blobs from HTTP mirrors.
    Note that when a blob gets downloaded from a mirror or from a peer, BlobManager will mark it as completed
    and cause any other type of downloader to progress to the next missing blob. Also, BlobFile is naturally able
    to cancel other writers when a writer finishes first. That's why there is no call to cancel/resume/stop between
    different types of downloaders.
    '''
    def __init__(self, blob_manager, blob_hashes=None, servers=None, client=None, sd_hashes=None, retry=True,
                 clock=None):
        if not clock:
            from twisted.internet import reactor
            self.clock = reactor
        else:
            self.clock = clock
        self.blob_manager = blob_manager
        self.servers = servers or []
        self.client = client or treq
        self.blob_hashes = blob_hashes or []
        self.missing_blob_hashes = []
        self.downloaded_blob_hashes = []
        self.sd_hashes = sd_hashes or []
        self.head_blob_hashes = []
        self.max_failures = 3
        self.semaphore = defer.DeferredSemaphore(2)
        self.deferreds = []
        self.writers = []
        self.retry = retry
        self.looping_call = task.LoopingCall(self._download_lc)
        self.looping_call.clock = self.clock
        self.finished_deferred = defer.Deferred()
        self.finished_deferred.addErrback(lambda err: err.trap(defer.CancelledError))
        self.short_delay = 30
        self.long_delay = 600
        self.delay = self.short_delay
        self.last_missing = 10000000
        self.lc_deferred = None

    @defer.inlineCallbacks
    def start(self):
        if not self.looping_call.running:
            self.lc_deferred = self.looping_call.start(self.short_delay, now=True)
            self.lc_deferred.addErrback(lambda err: err.trap(defer.CancelledError))
            yield self.finished_deferred

    def stop(self):
        for d in reversed(self.deferreds):
            d.cancel()
        while self.writers:
            writer = self.writers.pop()
            writer.close(DownloadCancelledError())
        self.blob_hashes = []
        if self.looping_call.running:
            self.looping_call.stop()
        if self.lc_deferred and not self.lc_deferred.called:
            self.lc_deferred.cancel()
        if not self.finished_deferred.called:
            self.finished_deferred.cancel()

    @defer.inlineCallbacks
    def _download_lc(self):
        delay = yield self._download_and_get_retry_delay()
        log.debug("delay: %s, missing: %i, downloaded from mirror: %i", delay, len(self.missing_blob_hashes),
                 len(self.downloaded_blob_hashes))
        while self.missing_blob_hashes:
            self.blob_hashes.append(self.missing_blob_hashes.pop())
        if not delay:
            if self.looping_call.running:
                self.looping_call.stop()
            if not self.finished_deferred.called:
                log.debug("mirror finished")
                self.finished_deferred.callback(None)
        elif delay and delay != self.delay:
            if delay == self.long_delay:
                log.debug("mirror not making progress, trying less frequently")
            elif delay == self.short_delay:
                log.debug("queueing retry of %i blobs", len(self.missing_blob_hashes))
            if self.looping_call.running:
                self.looping_call.stop()
            self.delay = delay
            self.looping_call = task.LoopingCall(self._download_lc)
            self.looping_call.clock = self.clock
            self.lc_deferred = self.looping_call.start(self.delay, now=False)
            self.lc_deferred.addErrback(lambda err: err.trap(defer.CancelledError))
            yield self.finished_deferred

    @defer.inlineCallbacks
    def _download_and_get_retry_delay(self):
        if self.blob_hashes and self.servers:
            if self.sd_hashes:
                log.debug("trying to download stream from mirror (sd %s)", self.sd_hashes[0][:8])
            else:
                log.debug("trying to download %i blobs from mirror", len(self.blob_hashes))
            blobs = yield DeferredDict(
                {blob_hash: self.blob_manager.get_blob(blob_hash) for blob_hash in self.blob_hashes}
            )
            self.deferreds = [self.download_blob(blobs[blob_hash]) for blob_hash in self.blob_hashes]
            yield defer.DeferredList(self.deferreds)
            if self.retry and self.missing_blob_hashes:
                if not self.downloaded_blob_hashes:
                    defer.returnValue(self.long_delay)
                if len(self.missing_blob_hashes) < self.last_missing:
                    self.last_missing = len(self.missing_blob_hashes)
                    defer.returnValue(self.short_delay)
            if self.retry and self.last_missing and len(self.missing_blob_hashes) == self.last_missing:
                defer.returnValue(self.long_delay)
            defer.returnValue(None)

    @defer.inlineCallbacks
    def _download_blob(self, blob):
        for _ in range(self.max_failures):
            writer, finished_deferred = blob.open_for_writing('mirror')
            self.writers.append(writer)
            try:
                downloaded = yield self._write_blob(writer, blob)
                if downloaded:
                    yield finished_deferred  # yield for verification errors, so we log them
                    if blob.verified:
                        log.info('Mirror completed download for %s', blob.blob_hash)
                        should_announce = blob.blob_hash in self.sd_hashes or blob.blob_hash in self.head_blob_hashes
                        yield defer.Deferred.fromFuture(self.blob_manager.blob_completed(blob, should_announce=should_announce))
                        self.downloaded_blob_hashes.append(blob.blob_hash)
                break
            except (IOError, Exception, defer.CancelledError, ConnectingCancelledError, ResponseNeverReceived) as e:
                if isinstance(
                        e, (DownloadCancelledError, defer.CancelledError, ConnectingCancelledError,
                            ResponseNeverReceived)
                ) or 'closed file' in str(e):
                    # some other downloader finished first or it was simply cancelled
                    log.info("Mirror download cancelled: %s", blob.blob_hash)
                    break
                else:
                    log.exception('Mirror failed downloading')
            finally:
                finished_deferred.addBoth(lambda _: None)  # suppress echoed errors
                if 'mirror' in blob.writers:
                    writer.close()
                self.writers.remove(writer)

    def download_blob(self, blob):
        if not blob.verified:
            d = self.semaphore.run(self._download_blob, blob)
            d.addErrback(lambda err: err.trap(defer.TimeoutError, defer.CancelledError))
            return d
        return defer.succeed(None)

    @defer.inlineCallbacks
    def _write_blob(self, writer, blob):
        response = yield self.client.get(url_for(choice(self.servers), blob.blob_hash))
        if response.code != 200:
            log.debug('Missing a blob: %s', blob.blob_hash)
            if blob.blob_hash in self.blob_hashes:
                self.blob_hashes.remove(blob.blob_hash)
            if blob.blob_hash not in self.missing_blob_hashes:
                self.missing_blob_hashes.append(blob.blob_hash)
            defer.returnValue(False)

        log.debug('Download started: %s', blob.blob_hash)
        blob.set_length(response.length)
        yield self.client.collect(response, writer.write)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def download_stream(self, stream_hash, sd_hash):
        stream_crypt_blobs = yield self.blob_manager.storage.get_blobs_for_stream(stream_hash)
        self.blob_hashes.extend([
            b.blob_hash for b in stream_crypt_blobs
            if b.blob_hash and b.blob_hash not in self.blob_hashes
        ])
        if sd_hash not in self.sd_hashes:
            self.sd_hashes.append(sd_hash)
        head_blob_hash = stream_crypt_blobs[0].blob_hash
        if head_blob_hash not in self.head_blob_hashes:
            self.head_blob_hashes.append(head_blob_hash)
        yield self.start()


def url_for(server, blob_hash=''):
    return f'http://{server}/{blob_hash}'
