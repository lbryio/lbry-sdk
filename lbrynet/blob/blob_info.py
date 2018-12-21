import typing


class BlobInfo:
    def __init__(self, blob_num: int, length: int, iv: str,  blob_hash: typing.Optional[str] = None):
        self.blob_hash = blob_hash
        self.blob_num = blob_num
        self.length = length
        self.iv = iv

    def as_dict(self) -> typing.Dict:
        d = {
            'length': self.length,
            'blob_num': self.blob_num,
            'iv': self.iv,
        }
        if self.blob_hash:  # non-terminator blobs have a blob hash
            d['blob_hash'] = self.blob_hash
        return d
