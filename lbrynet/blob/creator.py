import os
import logging
from io import BytesIO
from twisted.internet import defer
from twisted.web.client import FileBodyProducer
from lbrynet.core.cryptoutils import get_lbry_hash_obj

log = logging.getLogger(__name__)


class BlobFileCreator(object):
    """
    This class is used to create blobs on the local filesystem
    when we do not know the blob hash beforehand (i.e, when creating
    a new stream)
    """
    def __init__(self, blob_dir):
        self.blob_dir = blob_dir
        self.buffer = BytesIO()
        self._is_open = True
        self._hashsum = get_lbry_hash_obj()
        self.len_so_far = 0
        self.blob_hash = None
        self.length = None

    @defer.inlineCallbacks
    def close(self):
        self.length = self.len_so_far
        self.blob_hash = self._hashsum.hexdigest()
        if self.blob_hash and self._is_open and self.length > 0:
            # do not save 0 length files (empty tail blob in streams)
            # or if its been closed already
            self.buffer.seek(0)
            out_path = os.path.join(self.blob_dir, self.blob_hash)
            producer = FileBodyProducer(self.buffer)
            yield producer.startProducing(open(out_path, 'wb'))
            self._is_open = False
        if self.length > 0:
            defer.returnValue(self.blob_hash)
        else:
            # 0 length files (empty tail blob in streams )
            # must return None as their blob_hash for
            # it to be saved properly by EncryptedFileMetadataManagers
            defer.returnValue(None)

    def write(self, data):
        if not self._is_open:
            raise IOError
        self._hashsum.update(data)
        self.len_so_far += len(data)
        self.buffer.write(data)
