from random import choice
import logging
from twisted.internet import defer, task
import treq
from lbrynet.core.utils import DeferredDict
from lbrynet.core.Error import DownloadCanceledError

log = logging.getLogger(__name__)


class HTTPBlobDownloader(object):
    '''
    A downloader that is able to get blobs from HTTP mirrors.
    Note that when a blob gets downloaded from a mirror or from a peer, BlobManager will mark it as completed
    and cause any other type of downloader to progress to the next missing blob. Also, BlobFile is naturally able
    to cancel other writers when a writer finishes first. That's why there is no call to cancel/resume/stop between
    different types of downloaders.
    '''
    def __init__(self, blob_manager, blob_hashes=None, servers=None, client=None, sd_hashes=None, retry=True):
        self.blob_manager = blob_manager
        self.servers = servers or []
        self.client = client or treq
        self.blob_hashes = blob_hashes or []
        self.missing_blob_hashes = []
        self.sd_hashes = sd_hashes or []
        self.head_blob_hashes = []
        self.max_failures = 3
        self.running = False
        self.semaphore = defer.DeferredSemaphore(2)
        self.deferreds = []
        self.writers = []
        self.retry = retry
        self.looping_call = task.LoopingCall(self._download_and_retry)
        self.finished_deferred = defer.Deferred()
        self.last_missing = 100000000

    @defer.inlineCallbacks
    def _download_and_retry(self):
        if not self.running and self.blob_hashes and self.servers:
            yield self._download_blobs()
            if self.retry and self.missing_blob_hashes:
                if len(self.missing_blob_hashes) < self.last_missing:
                    self.last_missing = len(self.missing_blob_hashes)
                    log.info("queueing retry of %i blobs", len(self.missing_blob_hashes))
                    while self.missing_blob_hashes:
                        self.blob_hashes.append(self.missing_blob_hashes.pop())
                    defer.returnValue(None)
        if self.looping_call.running:
            self.looping_call.stop()
        if self.retry and self.last_missing and len(self.missing_blob_hashes) == self.last_missing:
            log.info("mirror not making progress, trying less frequently")
            self.looping_call.start(600, now=False)
        elif not self.finished_deferred.called:
            self.finished_deferred.callback(None)
            log.info("mirror finished")

    def start(self):
        if not self.running:
            self.looping_call.start(30)
            self.running = True
        return self.finished_deferred

    def stop(self):
        if self.running:
            for d in reversed(self.deferreds):
                d.cancel()
            while self.writers:
                writer = self.writers.pop()
                writer.close(DownloadCanceledError())
            self.running = False
            self.blob_hashes = []
        if self.looping_call.running:
            self.looping_call.stop()

    @defer.inlineCallbacks
    def _download_blobs(self):
        blobs = yield DeferredDict(
            {blob_hash: self.blob_manager.get_blob(blob_hash) for blob_hash in self.blob_hashes}
        )
        self.deferreds = [self.download_blob(blobs[blob_hash]) for blob_hash in self.blob_hashes]
        yield defer.DeferredList(self.deferreds)

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
                        yield self.blob_manager.blob_completed(blob, should_announce=should_announce)
                break
            except (IOError, Exception, defer.CancelledError) as e:
                if isinstance(e, (DownloadCanceledError, defer.CancelledError)) or 'closed file' in str(e):
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
    return 'http://{}/{}'.format(server, blob_hash)
