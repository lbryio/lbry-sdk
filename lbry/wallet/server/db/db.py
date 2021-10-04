import struct
from typing import Optional
from lbry.wallet.server.db import DB_PREFIXES
from lbry.wallet.server.db.revertable import RevertableOpStack


class KeyValueStorage:
    def get(self, key: bytes, fill_cache: bool = True) -> Optional[bytes]:
        raise NotImplemented()

    def iterator(self, reverse=False, start=None, stop=None, include_start=True, include_stop=False, prefix=None,
                 include_key=True, include_value=True, fill_cache=True):
        raise NotImplemented()

    def write_batch(self, transaction: bool = False):
        raise NotImplemented()

    def close(self):
        raise NotImplemented()

    @property
    def closed(self) -> bool:
        raise NotImplemented()


class PrefixDB:
    UNDO_KEY_STRUCT = struct.Struct(b'>Q')

    def __init__(self, db: KeyValueStorage, unsafe_prefixes=None):
        self._db = db
        self._op_stack = RevertableOpStack(db.get, unsafe_prefixes=unsafe_prefixes)

    def unsafe_commit(self):
        """
        Write staged changes to the database without keeping undo information
        Changes written cannot be undone
        """
        try:
            with self._db.write_batch(transaction=True) as batch:
                batch_put = batch.put
                batch_delete = batch.delete
                for staged_change in self._op_stack:
                    if staged_change.is_put:
                        batch_put(staged_change.key, staged_change.value)
                    else:
                        batch_delete(staged_change.key)
        finally:
            self._op_stack.clear()

    def commit(self, height: int):
        """
        Write changes for a block height to the database and keep undo information so that the changes can be reverted
        """
        undo_ops = self._op_stack.get_undo_ops()
        try:
            with self._db.write_batch(transaction=True) as batch:
                batch_put = batch.put
                batch_delete = batch.delete
                for staged_change in self._op_stack:
                    if staged_change.is_put:
                        batch_put(staged_change.key, staged_change.value)
                    else:
                        batch_delete(staged_change.key)
                batch_put(DB_PREFIXES.undo.value + self.UNDO_KEY_STRUCT.pack(height), undo_ops)
        finally:
            self._op_stack.clear()

    def rollback(self, height: int):
        """
        Revert changes for a block height
        """
        undo_key = DB_PREFIXES.undo.value + self.UNDO_KEY_STRUCT.pack(height)
        self._op_stack.apply_packed_undo_ops(self._db.get(undo_key))
        try:
            with self._db.write_batch(transaction=True) as batch:
                batch_put = batch.put
                batch_delete = batch.delete
                for staged_change in self._op_stack:
                    if staged_change.is_put:
                        batch_put(staged_change.key, staged_change.value)
                    else:
                        batch_delete(staged_change.key)
                batch_delete(undo_key)
        finally:
            self._op_stack.clear()

    def get(self, key: bytes, fill_cache: bool = True) -> Optional[bytes]:
        return self._db.get(key, fill_cache=fill_cache)

    def iterator(self, reverse=False, start=None, stop=None, include_start=True, include_stop=False, prefix=None,
                 include_key=True, include_value=True, fill_cache=True):
        return self._db.iterator(
            reverse=reverse, start=start, stop=stop, include_start=include_start, include_stop=include_stop,
            prefix=prefix, include_key=include_key, include_value=include_value, fill_cache=fill_cache
        )

    def close(self):
        if not self._db.closed:
            self._db.close()

    @property
    def closed(self):
        return self._db.closed
