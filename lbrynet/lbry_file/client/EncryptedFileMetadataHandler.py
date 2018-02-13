import logging
from zope.interface import implements
from twisted.internet import defer
from lbrynet.interfaces import IMetadataHandler


log = logging.getLogger(__name__)


class EncryptedFileMetadataHandler(object):
    implements(IMetadataHandler)

    def __init__(self, stream_hash, storage, download_manager):
        self.stream_hash = stream_hash
        self.storage = storage
        self.download_manager = download_manager
        self._final_blob_num = None

    ######### IMetadataHandler #########

    @defer.inlineCallbacks
    def get_initial_blobs(self):
        blob_infos = yield self.storage.get_blobs_for_stream(self.stream_hash)
        formatted_infos = self._format_initial_blobs_for_download_manager(blob_infos)
        defer.returnValue(formatted_infos)

    def final_blob_num(self):
        return self._final_blob_num

    ######### internal calls #########

    def _format_initial_blobs_for_download_manager(self, blob_infos):
        infos = []
        for i, crypt_blob in enumerate(blob_infos):
            if crypt_blob.blob_hash is not None and crypt_blob.length:
                infos.append(crypt_blob)
            else:
                if i != len(blob_infos) - 1:
                    raise Exception("Invalid stream terminator: %i of %i" %
                                    (i, len(blob_infos) - 1))
                log.debug("Setting _final_blob_num to %s", str(crypt_blob.blob_num - 1))
                self._final_blob_num = crypt_blob.blob_num - 1
        return infos
