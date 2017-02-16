import logging
from twisted.internet import defer
from twisted.python import failure
from zope.interface import implements
from lbrynet import interfaces


log = logging.getLogger(__name__)


class DownloadManager(object):
    implements(interfaces.IDownloadManager)

    def __init__(self, blob_manager):
        self.blob_manager = blob_manager
        self.blob_info_finder = None
        self.progress_manager = None
        self.blob_handler = None
        self.connection_manager = None
        self.blobs = {}
        self.blob_infos = {}

    ######### IDownloadManager #########

    def start_downloading(self):
        d = self.blob_info_finder.get_initial_blobs()
        log.debug("Requested the initial blobs from the info finder")
        d.addCallback(self.add_blobs_to_download)
        d.addCallback(lambda _: self.resume_downloading())
        return d

    def resume_downloading(self):

        def check_start(result, manager):
            if isinstance(result, failure.Failure):
                log.error("Failed to start the %s: %s", manager, result.getErrorMessage())
                return False
            return True

        d1 = self.progress_manager.start()
        d1.addBoth(check_start, "progress manager")
        d2 = self.connection_manager.start()
        d2.addBoth(check_start, "connection manager")
        dl = defer.DeferredList([d1, d2])
        dl.addCallback(lambda xs: False not in xs)
        return dl

    def stop_downloading(self):

        def check_stop(result, manager):
            if isinstance(result, failure.Failure):
                log.error("Failed to stop the %s: %s", manager, result.getErrorMessage())
                return False
            return True

        d1 = self.progress_manager.stop()
        d1.addBoth(check_stop, "progress manager")
        d2 = self.connection_manager.stop()
        d2.addBoth(check_stop, "connection manager")
        dl = defer.DeferredList([d1, d2], consumeErrors=True)
        dl.addCallback(lambda results: all([success for success, val in results]))
        return dl

    def add_blobs_to_download(self, blob_infos):

        log.debug("Adding %s blobs to blobs", len(blob_infos))

        def add_blob_to_list(blob, blob_num):
            self.blobs[blob_num] = blob
            log.debug(
                "Added blob (hash: %s, number %s) to the list", blob.blob_hash, blob_num)

        def error_during_add(err):
            log.warning(
                "An error occurred adding the blob to blobs. Error:%s", err.getErrorMessage())
            return err

        ds = []
        for blob_info in blob_infos:
            if not blob_info.blob_num in self.blobs:
                self.blob_infos[blob_info.blob_num] = blob_info
                log.debug(
                    "Trying to get the blob associated with blob hash %s", blob_info.blob_hash)
                d = self.blob_manager.get_blob(blob_info.blob_hash, blob_info.length)
                d.addCallback(add_blob_to_list, blob_info.blob_num)
                d.addErrback(error_during_add)
                ds.append(d)

        dl = defer.DeferredList(ds)
        return dl

    def stream_position(self):
        return self.progress_manager.stream_position()

    def needed_blobs(self):
        return self.progress_manager.needed_blobs()

    def final_blob_num(self):
        return self.blob_info_finder.final_blob_num()

    def handle_blob(self, blob_num):
        return self.blob_handler.handle_blob(self.blobs[blob_num], self.blob_infos[blob_num])

    def calculate_total_bytes(self):
        return sum([bi.length for bi in self.blob_infos.itervalues()])

    def calculate_bytes_left_to_output(self):
        if not self.blobs:
            return self.calculate_total_bytes()
        else:
            to_be_outputted = [
                b for n, b in self.blobs.iteritems()
                if n >= self.progress_manager.last_blob_outputted
            ]
            return sum([b.length for b in to_be_outputted if b.length is not None])

    def calculate_bytes_left_to_download(self):
        if not self.blobs:
            return self.calculate_total_bytes()
        else:
            return sum([b.length for b in self.needed_blobs() if b.length is not None])
