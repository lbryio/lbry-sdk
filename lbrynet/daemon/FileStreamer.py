import logging
import os
import sys
import mimetypes

from appdirs import user_data_dir
from zope.interface import implements
from twisted.internet import defer, error, interfaces, abstract, task, reactor


# TODO: omg, this code is essentially duplicated in Daemon
if sys.platform != "darwin":
    data_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
else:
    data_dir = user_data_dir("LBRY")
if not os.path.isdir(data_dir):
    os.mkdir(data_dir)

log = logging.getLogger(__name__)
STATUS_FINISHED = 'finished'

class EncryptedFileStreamer(object):
    """
    Writes LBRY stream to request; will pause to wait for new data if the file
    is downloading.

    No support for range requests (some browser players can't handle it when
    the full video data isn't available on request).
    """
    implements(interfaces.IPushProducer)

    bufferSize = abstract.FileDescriptor.bufferSize


    # How long to wait between sending blocks (needed because some
    # video players freeze up if you try to send data too fast)
    stream_interval = 0.005

    # How long to wait before checking if new data has been appended to the file
    new_data_check_interval = 0.25


    def __init__(self, request, path, stream, file_manager):
        def _set_content_length_header(length):
            self._request.setHeader('content-length', length)
            return defer.succeed(None)

        self._request = request
        self._file = open(path, 'rb')
        self._stream = stream
        self._file_manager = file_manager
        self._headers_sent = False

        self._running = True

        self._request.setResponseCode(200)
        self._request.setHeader('accept-ranges', 'none')
        self._request.setHeader('content-type', mimetypes.guess_type(path)[0])
        self._request.setHeader("Content-Security-Policy", "sandbox")

        self._deferred = stream.get_total_bytes()
        self._deferred.addCallback(_set_content_length_header)
        self._deferred.addCallback(lambda _: self.resumeProducing())

    def _check_for_new_data(self):
        def _recurse_or_stop(stream_status):
            if not self._running:
                return

            if stream_status != STATUS_FINISHED:
                self._deferred.addCallback(
                    lambda _: task.deferLater(
                        reactor, self.new_data_check_interval, self._check_for_new_data))
            else:
                self.stopProducing()

        if not self._running:
            return

        # Clear the file's EOF indicator by seeking to current position
        self._file.seek(self._file.tell())

        data = self._file.read(self.bufferSize)
        if data:
            self._request.write(data)
            if self._running:  # .write() can trigger a pause
                self._deferred.addCallback(
                    lambda _: task.deferLater(
                        reactor, self.stream_interval, self._check_for_new_data))
        else:
            self._deferred.addCallback(
                lambda _: self._file_manager.get_lbry_file_status(self._stream))
            self._deferred.addCallback(_recurse_or_stop)

    def pauseProducing(self):
        self._running = False

    def resumeProducing(self):
        self._running = True
        self._check_for_new_data()

    def stopProducing(self):
        self._running = False
        self._file.close()
        self._deferred.addErrback(lambda err: err.trap(defer.CancelledError))
        self._deferred.addErrback(lambda err: err.trap(error.ConnectionDone))
        self._deferred.cancel()
        self._request.unregisterProducer()
        self._request.finish()
