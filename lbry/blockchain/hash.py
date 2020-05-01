from binascii import hexlify, unhexlify
from lbry.constants import NULL_HASH32


class TXRef:

    __slots__ = '_id', '_hash'

    def __init__(self):
        self._id = None
        self._hash = None

    @property
    def id(self):
        return self._id

    @property
    def hash(self):
        return self._hash

    @property
    def height(self):
        return -1

    @property
    def is_null(self):
        return self.hash == NULL_HASH32


class TXRefImmutable(TXRef):

    __slots__ = ('_height',)

    def __init__(self):
        super().__init__()
        self._height = -1

    @classmethod
    def from_hash(cls, tx_hash: bytes, height: int) -> 'TXRefImmutable':
        ref = cls()
        ref._hash = tx_hash
        ref._id = hexlify(tx_hash[::-1]).decode()
        ref._height = height
        return ref

    @classmethod
    def from_id(cls, tx_id: str, height: int) -> 'TXRefImmutable':
        ref = cls()
        ref._id = tx_id
        ref._hash = unhexlify(tx_id)[::-1]
        ref._height = height
        return ref

    @property
    def height(self):
        return self._height
