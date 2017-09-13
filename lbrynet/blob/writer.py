import logging
from io import BytesIO
from twisted.python.failure import Failure
from lbrynet.core.Error import DownloadCanceledError, InvalidDataError
from lbrynet.core.cryptoutils import get_lbry_hash_obj

log = logging.getLogger(__name__)


class HashBlobWriter(object):
    def __init__(self, length_getter, finished_cb):
        self.write_handle = BytesIO()
        self.length_getter = length_getter
        self.finished_cb = finished_cb
        self.finished_cb_d = None
        self._hashsum = get_lbry_hash_obj()
        self.len_so_far = 0

    @property
    def blob_hash(self):
        return self._hashsum.hexdigest()

    def write(self, data):
        if self.write_handle is None:
            log.info("writer has already been closed")
            # can this be changed to IOError?
            raise ValueError('I/O operation on closed file')

        self._hashsum.update(data)
        self.len_so_far += len(data)
        if self.len_so_far > self.length_getter():
            self.finished_cb_d = self.finished_cb(
                self,
                Failure(InvalidDataError("Length so far is greater than the expected length."
                                         " %s to %s" % (self.len_so_far,
                                                        self.length_getter()))))
        else:
            self.write_handle.write(data)
            if self.len_so_far == self.length_getter():
                self.finished_cb_d = self.finished_cb(self)

    def close_handle(self):
        if self.write_handle is not None:
            self.write_handle.close()
            self.write_handle = None

    def close(self, reason=None):
        # if we've already called finished_cb because we either finished writing
        # or closed already, do nothing
        if self.finished_cb_d is not None:
            return
        if reason is None:
            reason = Failure(DownloadCanceledError())
        self.finished_cb_d = self.finished_cb(self, reason)
