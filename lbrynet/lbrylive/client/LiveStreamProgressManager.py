import logging
from lbrynet.core.client.StreamProgressManager import StreamProgressManager
from twisted.internet import defer


class LiveStreamProgressManager(StreamProgressManager):
    def __init__(self, finished_callback, blob_manager, download_manager, delete_blob_after_finished=False,
                 download_whole=True, max_before_skip_ahead=5):
        self.download_whole = download_whole
        self.max_before_skip_ahead = max_before_skip_ahead
        StreamProgressManager.__init__(self, finished_callback, blob_manager, download_manager,
                                       delete_blob_after_finished)

    ######### IProgressManager #########

    def stream_position(self):
        blobs = self.download_manager.blobs
        if not blobs:
            return 0
        else:
            newest_known_blobnum = max(blobs.iterkeys())
            position = newest_known_blobnum
            oldest_relevant_blob_num = (max(0, newest_known_blobnum - self.max_before_skip_ahead + 1))
            for i in xrange(newest_known_blobnum, oldest_relevant_blob_num - 1, -1):
                if i in blobs and (not blobs[i].is_validated() and not i in self.provided_blob_nums):
                    position = i
            return position

    def needed_blobs(self):
        blobs = self.download_manager.blobs
        stream_position = self.stream_position()
        if blobs:
            newest_known_blobnum = max(blobs.iterkeys())
        else:
            newest_known_blobnum = -1
        blobs_needed = []
        for i in xrange(stream_position, newest_known_blobnum + 1):
            if i in blobs and not blobs[i].is_validated() and not i in self.provided_blob_nums:
                blobs_needed.append(blobs[i])
        return blobs_needed

    ######### internal #########

    def _output_loop(self):

        from twisted.internet import reactor

        if self.stopped is True:
            if self.outputting_d is not None:
                self.outputting_d.callback(True)
                self.outputting_d = None
            return

        blobs = self.download_manager.blobs
        logging.info("In _output_loop. last_blob_outputted: %s", str(self.last_blob_outputted))
        if blobs:
            logging.debug("Newest blob number: %s", str(max(blobs.iterkeys())))
        if self.outputting_d is None:
            self.outputting_d = defer.Deferred()

        current_blob_num = self.last_blob_outputted + 1

        def finished_outputting_blob():
            self.last_blob_outputted += 1
            final_blob_num = self.download_manager.final_blob_num()
            if final_blob_num is not None and final_blob_num == self.last_blob_outputted:
                self._finished_outputting()
                self.outputting_d.callback(True)
                self.outputting_d = None
            else:
                reactor.callLater(0, self._output_loop)

        if current_blob_num in blobs and blobs[current_blob_num].is_validated():
            logging.info("Outputting blob %s", str(current_blob_num))
            self.provided_blob_nums.append(current_blob_num)
            d = self.download_manager.handle_blob(current_blob_num)
            d.addCallback(lambda _: finished_outputting_blob())
            d.addCallback(lambda _: self._finished_with_blob(current_blob_num))
        elif blobs and max(blobs.iterkeys()) > self.last_blob_outputted + self.max_before_skip_ahead - 1:
            self.last_blob_outputted += 1
            logging.info("Skipping blob number %s due to knowing about blob number %s",
                         str(self.last_blob_outputted), str(max(blobs.iterkeys())))
            self._finished_with_blob(current_blob_num)
            reactor.callLater(0, self._output_loop)
        else:
            self.outputting_d.callback(True)
            self.outputting_d = None