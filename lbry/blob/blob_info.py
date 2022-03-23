import typing


class BlobInfo:
    __slots__ = [
        'blob_hash',
        'blob_num',
        'length',
        'iv',
        'added_on',
        'is_mine'
    ]

    def __init__(
            self, blob_num: int, length: int, iv: str, added_on,
             blob_hash: typing.Optional[str] = None, is_mine=False):
        self.blob_hash = blob_hash
        self.blob_num = blob_num
        self.length = length
        self.iv = iv
        self.added_on = added_on
        self.is_mine = is_mine

    def as_dict(self) -> typing.Dict:
        d = {
            'length': self.length,
            'blob_num': self.blob_num,
            'iv': self.iv,
        }
        if self.blob_hash:  # non-terminator blobs have a blob hash
            d['blob_hash'] = self.blob_hash
        return d
