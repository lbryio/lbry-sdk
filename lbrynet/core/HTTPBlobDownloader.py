from random import choice
import logging

from twisted.internet import defer
import treq

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
    def __init__(self, blob_manager, blob_hashes=None, servers=None, client=None, sd_hashes=None):
        self.blob_manager = blob_manager
        self.servers = servers or []
        self.client = client or treq
        self.blob_hashes = blob_hashes or []
        self.sd_hashes = sd_hashes or []
        self.head_blob_hashes = []
        self.max_failures = 3
        self.running = False
        self.semaphore = defer.DeferredSemaphore(2)
        self.deferreds = []
        self.writers = []

    def start(self):
        if not self.running and self.blob_hashes and self.servers:
            return self._start()
        defer.succeed(None)

    def stop(self):
        if self.running:
            for d in reversed(self.deferreds):
                d.cancel()
            for writer in self.writers:
                writer.close(DownloadCanceledError())
            self.running = False
            self.blob_hashes = []

    @defer.inlineCallbacks
    def _start(self):
        self.running = True
        dl = []
        for blob_hash in self.blob_hashes:
            blob = yield self.blob_manager.get_blob(blob_hash)
            if not blob.verified:
                d = self.semaphore.run(self.download_blob, blob)
                d.addErrback(lambda err: err.check(defer.TimeoutError, defer.CancelledError))
                dl.append(d)
        self.deferreds = dl
        yield defer.DeferredList(dl)

    @defer.inlineCallbacks
    def download_blob(self, blob):
        for _ in range(self.max_failures):
            writer, finished_deferred = blob.open_for_writing('mirror')
            self.writers.append(writer)
            try:
                downloaded = yield self._write_blob(writer, blob)
                if downloaded:
                    yield finished_deferred  # yield for verification errors, so we log them
                    if blob.verified:
                        log.info('Mirror completed download for %s', blob.blob_hash)
                        b_h = blob.blob_hash
                        if b_h in self.sd_hashes or b_h in self.head_blob_hashes:
                            should_announce = True
                        else:
                            should_announce = False
                        yield self.blob_manager.blob_completed(blob, should_announce=should_announce)
                break
            except (IOError, Exception) as e:
                if isinstance(e, DownloadCanceledError) or 'closed file' in str(e):
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

    @defer.inlineCallbacks
    def _write_blob(self, writer, blob):
        response = yield self.client.get(url_for(choice(self.servers), blob.blob_hash))
        if response.code != 200:
            log.debug('Missing a blob: %s', blob.blob_hash)
            if blob.blob_hash in self.blob_hashes:
                self.blob_hashes.remove(blob.blob_hash)
            defer.returnValue(False)

        log.debug('Download started: %s', blob.blob_hash)
        blob.set_length(response.length)
        yield self.client.collect(response, writer.write)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def download_stream(self, stream_hash, sd_hash):
        blobs = yield self.blob_manager.storage.get_blobs_for_stream(stream_hash)
        blob_hashes = [
            b.blob_hash for b in blobs if b.blob_hash is not None and b.blob_hash not in self.blob_hashes
        ]
        self.blob_hashes.extend(blob_hashes)
        if sd_hash not in self.sd_hashes:
            self.sd_hashes.append(sd_hash)
        if blob_hashes[0] not in self.head_blob_hashes:
            self.head_blob_hashes.append(blob_hashes[0])
        yield self.start()


def url_for(server, blob_hash=''):
    return 'http://{}/{}'.format(server, blob_hash)
