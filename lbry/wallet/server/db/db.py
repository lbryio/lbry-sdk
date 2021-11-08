import struct
import rocksdb
from typing import Optional
from lbry.wallet.server.db import DB_PREFIXES
from lbry.wallet.server.db.revertable import RevertableOpStack, RevertablePut, RevertableDelete


class RocksDBStore:
    def __init__(self, path: str, cache_mb: int, max_open_files: int, secondary_path: str = ''):
        # Use snappy compression (the default)
        self.path = path
        self._max_open_files = max_open_files
        self.db = rocksdb.DB(path, self.get_options(), secondary_name=secondary_path)
        # self.multi_get = self.db.multi_get

    def get_options(self):
        return rocksdb.Options(
            create_if_missing=True, use_fsync=True, target_file_size_base=33554432,
            max_open_files=self._max_open_files
        )

    def get(self, key: bytes, fill_cache: bool = True) -> Optional[bytes]:
        return self.db.get(key, fill_cache=fill_cache)

    def iterator(self, reverse=False, start=None, stop=None, include_start=True, include_stop=False, prefix=None,
                 include_key=True, include_value=True, fill_cache=True):
        return RocksDBIterator(
            self.db, reverse=reverse, start=start, stop=stop, include_start=include_start, include_stop=include_stop,
            prefix=prefix, include_key=include_key, include_value=include_value
        )

    def write_batch(self, disable_wal: bool = False, sync: bool = False):
        return RocksDBWriteBatch(self.db, sync=sync, disable_wal=disable_wal)

    def close(self):
        self.db.close()
        self.db = None

    @property
    def closed(self) -> bool:
        return self.db is None

    def try_catch_up_with_primary(self):
        self.db.try_catch_up_with_primary()


class RocksDBWriteBatch:
    def __init__(self, db: rocksdb.DB, sync: bool = False, disable_wal: bool = False):
        self.batch = rocksdb.WriteBatch()
        self.db = db
        self.sync = sync
        self.disable_wal = disable_wal

    def __enter__(self):
        return self.batch

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not exc_val:
            self.db.write(self.batch, sync=self.sync, disable_wal=self.disable_wal)


class RocksDBIterator:
    """An iterator for RocksDB."""

    __slots__ = [
        'start',
        'prefix',
        'stop',
        'iterator',
        'include_key',
        'include_value',
        'prev_k',
        'reverse',
        'include_start',
        'include_stop'
    ]

    def __init__(self, db: rocksdb.DB, prefix: bytes = None, start: bool = None, stop: bytes = None,
                 include_key: bool = True, include_value: bool = True, reverse: bool = False,
                 include_start: bool = True, include_stop: bool = False):
        assert (start is None and stop is None) or (prefix is None), 'cannot use start/stop and prefix'
        self.start = start
        self.prefix = prefix
        self.stop = stop
        self.iterator = db.iteritems() if not reverse else reversed(db.iteritems())
        if prefix is not None:
            self.iterator.seek(prefix)
        elif start is not None:
            self.iterator.seek(start)
        self.include_key = include_key
        self.include_value = include_value
        self.prev_k = None
        self.reverse = reverse
        self.include_start = include_start
        self.include_stop = include_stop

    def __iter__(self):
        return self

    def _check_stop_iteration(self, key: bytes):
        if self.stop is not None and (key.startswith(self.stop) or self.stop < key[:len(self.stop)]):
            raise StopIteration
        elif self.start is not None and self.start > key[:len(self.start)]:
            raise StopIteration
        elif self.prefix is not None and not key.startswith(self.prefix):
            raise StopIteration

    def __next__(self):
        # TODO: include start/stop on/off
        # check for needing to stop from previous iteration
        if self.prev_k is not None:
            self._check_stop_iteration(self.prev_k)
        k, v = next(self.iterator)
        self._check_stop_iteration(k)
        self.prev_k = k

        if self.include_key and self.include_value:
            return k, v
        elif self.include_key:
            return k
        return v


class PrefixDB:
    UNDO_KEY_STRUCT = struct.Struct(b'>Q')

    def __init__(self, db: RocksDBStore, max_undo_depth: int = 200, unsafe_prefixes=None):
        self._db = db
        self._op_stack = RevertableOpStack(db.get, unsafe_prefixes=unsafe_prefixes)
        self._max_undo_depth = max_undo_depth

    def unsafe_commit(self):
        """
        Write staged changes to the database without keeping undo information
        Changes written cannot be undone
        """
        try:
            with self._db.write_batch(sync=True) as batch:
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
        delete_undos = []
        if height > self._max_undo_depth:
            delete_undos.extend(self._db.iterator(
                start=DB_PREFIXES.undo.value + self.UNDO_KEY_STRUCT.pack(0),
                stop=DB_PREFIXES.undo.value + self.UNDO_KEY_STRUCT.pack(height - self._max_undo_depth),
                include_value=False
            ))
        try:
            with self._db.write_batch(sync=True) as batch:
                batch_put = batch.put
                batch_delete = batch.delete
                for staged_change in self._op_stack:
                    if staged_change.is_put:
                        batch_put(staged_change.key, staged_change.value)
                    else:
                        batch_delete(staged_change.key)
                for undo_to_delete in delete_undos:
                    batch_delete(undo_to_delete)
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
            with self._db.write_batch(sync=True) as batch:
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

    def try_catch_up_with_primary(self):
        self._db.try_catch_up_with_primary()

    @property
    def closed(self):
        return self._db.closed

    def stage_raw_put(self, key: bytes, value: bytes):
        self._op_stack.append_op(RevertablePut(key, value))

    def stage_raw_delete(self, key: bytes, value: bytes):
        self._op_stack.append_op(RevertableDelete(key, value))
