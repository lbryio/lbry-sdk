import struct
from typing import Tuple, List
from lbry.wallet.server.db import DB_PREFIXES

_OP_STRUCT = struct.Struct('>BHH')


class RevertableOp:
    __slots__ = [
        'key',
        'value',
    ]
    is_put = 0

    def __init__(self, key: bytes, value: bytes):
        self.key = key
        self.value = value

    def invert(self) -> 'RevertableOp':
        raise NotImplementedError()

    def pack(self) -> bytes:
        """
        Serialize to bytes
        """
        return struct.pack(
            f'>BHH{len(self.key)}s{len(self.value)}s', self.is_put, len(self.key), len(self.value), self.key,
            self.value
        )

    @classmethod
    def unpack(cls, packed: bytes) -> Tuple['RevertableOp', bytes]:
        """
        Deserialize from bytes

        :param packed: bytes containing at least one packed revertable op
        :return: tuple of the deserialized op (a put or a delete) and the remaining serialized bytes
        """
        is_put, key_len, val_len = _OP_STRUCT.unpack(packed[:5])
        key = packed[5:5 + key_len]
        value = packed[5 + key_len:5 + key_len + val_len]
        if is_put == 1:
            return RevertablePut(key, value), packed[5 + key_len + val_len:]
        return RevertableDelete(key, value), packed[5 + key_len + val_len:]

    @classmethod
    def unpack_stack(cls, packed: bytes) -> List['RevertableOp']:
        """
        Deserialize multiple from bytes
        """
        ops = []
        while packed:
            op, packed = cls.unpack(packed)
            ops.append(op)
        return ops

    def __eq__(self, other: 'RevertableOp') -> bool:
        return (self.is_put, self.key, self.value) == (other.is_put, other.key, other.value)

    def __repr__(self) -> str:
        return f"{'PUT' if self.is_put else 'DELETE'} {DB_PREFIXES(self.key[:1]).name}: " \
               f"{self.key[1:].hex()} | {self.value.hex()}"


class RevertableDelete(RevertableOp):
    def invert(self):
        return RevertablePut(self.key, self.value)


class RevertablePut(RevertableOp):
    is_put = 1

    def invert(self):
        return RevertableDelete(self.key, self.value)


def delete_prefix(db: 'plyvel.DB', prefix: bytes) -> List['RevertableDelete']:
    return [RevertableDelete(k, v) for k, v in db.iterator(prefix=prefix)]
