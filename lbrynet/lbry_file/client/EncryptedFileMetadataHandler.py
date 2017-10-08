import logging
from zope.interface import implements
from twisted.internet import defer
from lbrynet.cryptstream.CryptBlob import CryptBlobInfo
from lbrynet.interfaces import IMetadataHandler


log = logging.getLogger(__name__)


class EncryptedFileMetadataHandler(object):
    implements(IMetadataHandler)

    def __init__(self, stream_hash, stream_info_manager, download_manager):
        self.stream_hash = stream_hash
        self.stream_info_manager = stream_info_manager
        self.download_manager = download_manager
        self._final_blob_num = None

    ######### IMetadataHandler #########

    @defer.inlineCallbacks
    def get_initial_blobs(self):
        blob_infos = yield self.stream_info_manager.get_blobs_for_stream(self.stream_hash)
        formatted_infos = self._format_initial_blobs_for_download_manager(blob_infos)
        defer.returnValue(formatted_infos)

    def final_blob_num(self):
        return self._final_blob_num

    ######### internal calls #########

    def _format_initial_blobs_for_download_manager(self, blob_infos):
        infos = []
        for i, (blob_hash, blob_num, iv, length) in enumerate(blob_infos):
            if blob_hash is not None and length:
                infos.append(CryptBlobInfo(blob_hash, blob_num, length, iv))
            else:
                if i != len(blob_infos) - 1:
                    raise Exception("Invalid stream terminator")
                log.debug("Setting _final_blob_num to %s", str(blob_num - 1))
                self._final_blob_num = blob_num - 1
        return infos
