import logging
from zope.interface import implements
from lbrynet.cryptstream.CryptBlob import CryptBlobInfo
from lbrynet.interfaces import IMetadataHandler


class LBRYFileMetadataHandler(object):
    implements(IMetadataHandler)

    def __init__(self, stream_hash, stream_info_manager, download_manager):
        self.stream_hash = stream_hash
        self.stream_info_manager = stream_info_manager
        self.download_manager = download_manager
        self._final_blob_num = None

    ######### IMetadataHandler #########

    def get_initial_blobs(self):
        d = self.stream_info_manager.get_blobs_for_stream(self.stream_hash)
        d.addCallback(self._format_initial_blobs_for_download_manager)
        return d

    def final_blob_num(self):
        return self._final_blob_num

    ######### internal calls #########

    def _format_initial_blobs_for_download_manager(self, blob_infos):
        infos = []
        for blob_hash, blob_num, iv, length in blob_infos:
            if blob_hash is not None:
                infos.append(CryptBlobInfo(blob_hash, blob_num, length, iv))
            else:
                logging.debug("Setting _final_blob_num to %s", str(blob_num - 1))
                self._final_blob_num = blob_num - 1
        return infos