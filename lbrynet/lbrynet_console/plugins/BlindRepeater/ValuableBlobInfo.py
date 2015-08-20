from lbrynet.core.BlobInfo import BlobInfo


class ValuableBlobInfo(BlobInfo):
    def __init__(self, blob_hash, length, reference, peer, peer_score):
        BlobInfo.__init__(self, blob_hash, blob_hash, length)
        self.reference = reference
        self.peer = peer
        self.peer_score = peer_score
