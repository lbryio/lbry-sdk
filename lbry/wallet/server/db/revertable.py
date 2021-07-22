import struct
from string import printable
from collections import OrderedDict, defaultdict
from typing import Tuple, List, Iterable, Callable, Optional
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

    @property
    def is_delete(self) -> bool:
        return not self.is_put

    def invert(self) -> 'RevertableOp':
        raise NotImplementedError()

    def pack(self) -> bytes:
        """
        Serialize to bytes
        """
        return struct.pack(
            f'>BHH{len(self.key)}s{len(self.value)}s', int(self.is_put), len(self.key), len(self.value), self.key,
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
        return str(self)

    def __str__(self) -> str:
        from lbry.wallet.server.db.prefixes import auto_decode_item
        k, v = auto_decode_item(self.key, self.value)
        key = ''.join(c if c in printable else '.' for c in str(k))
        val = ''.join(c if c in printable else '.' for c in str(v))
        return f"{'PUT' if self.is_put else 'DELETE'} {DB_PREFIXES(self.key[:1]).name}: {key} | {val}"


class RevertableDelete(RevertableOp):
    def invert(self):
        return RevertablePut(self.key, self.value)


class RevertablePut(RevertableOp):
    is_put = True

    def invert(self):
        return RevertableDelete(self.key, self.value)


class OpStackIntegrity(Exception):
    pass


class RevertableOpStack:
    def __init__(self, get_fn: Callable[[bytes], Optional[bytes]]):
        self._get = get_fn
        self._items = defaultdict(list)

    def append(self, op: RevertableOp):
        inverted = op.invert()
        if self._items[op.key] and inverted == self._items[op.key][-1]:
            self._items[op.key].pop()  # if the new op is the inverse of the last op, we can safely null both
            return
        elif self._items[op.key] and self._items[op.key][-1] == op:  # duplicate of last op
            return  # raise an error?
        stored_val = self._get(op.key)
        has_stored_val = stored_val is not None
        delete_stored_op = None if not has_stored_val else RevertableDelete(op.key, stored_val)
        will_delete_existing_stored = False if delete_stored_op is None else (delete_stored_op in self._items[op.key])
        if op.is_put and has_stored_val and not will_delete_existing_stored:
            raise OpStackIntegrity(
                f"db op tries to add on top of existing key without deleting first: {op}"
            )
        elif op.is_delete and has_stored_val and stored_val != op.value and not will_delete_existing_stored:
            # there is a value and we're not deleting it in this op
            # check that a delete for the stored value is in the stack
            raise OpStackIntegrity(f"delete {op}")
        elif op.is_delete and not has_stored_val:
            raise OpStackIntegrity(f"db op tries to delete nonexistent key: {op}")
        elif op.is_delete and stored_val != op.value:
            raise OpStackIntegrity(f"db op tries to delete with incorrect value: {op}")
        self._items[op.key].append(op)

    def extend(self, ops: Iterable[RevertableOp]):
        for op in ops:
            self.append(op)

    def clear(self):
        self._items.clear()

    def __len__(self):
        return sum(map(len, self._items.values()))

    def __iter__(self):
        for key, ops in self._items.items():
            for op in ops:
                yield op
