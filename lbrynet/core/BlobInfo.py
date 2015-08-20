class BlobInfo(object):
    """
    This structure is used to represent the metadata of a blob.

    @ivar blob_hash: The sha384 hashsum of the blob's data.
    @type blob_hash: string, hex-encoded

    @ivar blob_num: For streams, the position of the blob in the stream.
    @type blob_num: integer

    @ivar length: The length of the blob in bytes.
    @type length: integer
    """

    def __init__(self, blob_hash, blob_num, length):
        self.blob_hash = blob_hash
        self.blob_num = blob_num
        self.length = length