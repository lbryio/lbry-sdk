from lbrynet.cryptstream.CryptBlob import CryptStreamBlobMaker, CryptBlobInfo
import binascii


class LiveBlobInfo(CryptBlobInfo):
    def __init__(self, blob_hash, blob_num, length, iv, revision, signature):
        CryptBlobInfo.__init__(self, blob_hash, blob_num, length, iv)
        self.revision = revision
        self.signature = signature


class LiveStreamBlobMaker(CryptStreamBlobMaker):
    def __init__(self, key, iv, blob_num, blob):
        CryptStreamBlobMaker.__init__(self, key, iv, blob_num, blob)
        # The following is a placeholder for a currently unimplemented feature.
        # In the future it may be possible for the live stream creator to overwrite a blob
        # with a newer revision. If that happens, the 0 will be incremented to the
        # actual revision count
        self.revision = 0

    def _return_info(self, blob_hash):
        return LiveBlobInfo(blob_hash, self.blob_num, self.length, binascii.hexlify(self.iv),
                            self.revision, None)