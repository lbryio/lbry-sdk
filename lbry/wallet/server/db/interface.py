import struct
import typing

import rocksdb
from typing import Optional
from lbry.wallet.server.db import DB_PREFIXES
from lbry.wallet.server.db.revertable import RevertableOpStack, RevertablePut, RevertableDelete


class PrefixDB:
    """
    Base class for a revertable rocksdb database (a rocksdb db where each set of applied changes can be undone)
    """
    UNDO_KEY_STRUCT = struct.Struct(b'>Q32s')
    PARTIAL_UNDO_KEY_STRUCT = struct.Struct(b'>Q')

    def __init__(self, path, max_open_files=64, secondary_path='', max_undo_depth: int = 200, unsafe_prefixes=None):
        column_family_options = {
                prefix.value: rocksdb.ColumnFamilyOptions() for prefix in DB_PREFIXES
        } if secondary_path else {}
        self.column_families: typing.Dict[bytes, 'rocksdb.ColumnFamilyHandle'] = {}
        self._db = rocksdb.DB(
            path, rocksdb.Options(
                create_if_missing=True, use_fsync=True, target_file_size_base=33554432,
                max_open_files=max_open_files if not secondary_path else -1
            ), secondary_name=secondary_path, column_families=column_family_options
        )
        for prefix in DB_PREFIXES:
            cf = self._db.get_column_family(prefix.value)
            if cf is None and not secondary_path:
                self._db.create_column_family(prefix.value, rocksdb.ColumnFamilyOptions())
                cf = self._db.get_column_family(prefix.value)
            self.column_families[prefix.value] = cf

        self._op_stack = RevertableOpStack(self.get, unsafe_prefixes=unsafe_prefixes)
        self._max_undo_depth = max_undo_depth

    def unsafe_commit(self):
        """
        Write staged changes to the database without keeping undo information
        Changes written cannot be undone
        """
        try:
            if not len(self._op_stack):
                return
            with self._db.write_batch(sync=True) as batch:
                batch_put = batch.put
                batch_delete = batch.delete
                get_column_family = self.column_families.__getitem__
                for staged_change in self._op_stack:
                    column_family = get_column_family(DB_PREFIXES(staged_change.key[:1]).value)
                    if staged_change.is_put:
                        batch_put((column_family, staged_change.key), staged_change.value)
                    else:
                        batch_delete((column_family, staged_change.key))
        finally:
            self._op_stack.clear()

    def commit(self, height: int, block_hash: bytes):
        """
        Write changes for a block height to the database and keep undo information so that the changes can be reverted
        """
        undo_ops = self._op_stack.get_undo_ops()
        delete_undos = []
        if height > self._max_undo_depth:
            delete_undos.extend(self._db.iterator(
                start=DB_PREFIXES.undo.value + self.PARTIAL_UNDO_KEY_STRUCT.pack(0),
                iterate_upper_bound=DB_PREFIXES.undo.value + self.PARTIAL_UNDO_KEY_STRUCT.pack(height - self._max_undo_depth),
                include_value=False
            ))
        try:
            undo_c_f = self.column_families[DB_PREFIXES.undo.value]
            with self._db.write_batch(sync=True) as batch:
                batch_put = batch.put
                batch_delete = batch.delete
                get_column_family = self.column_families.__getitem__
                for staged_change in self._op_stack:
                    column_family = get_column_family(DB_PREFIXES(staged_change.key[:1]).value)
                    if staged_change.is_put:
                        batch_put((column_family, staged_change.key), staged_change.value)
                    else:
                        batch_delete((column_family, staged_change.key))
                for undo_to_delete in delete_undos:
                    batch_delete((undo_c_f, undo_to_delete))
                batch_put((undo_c_f, DB_PREFIXES.undo.value + self.UNDO_KEY_STRUCT.pack(height, block_hash)), undo_ops)
        finally:
            self._op_stack.clear()

    def rollback(self, height: int, block_hash: bytes):
        """
        Revert changes for a block height
        """
        undo_key = DB_PREFIXES.undo.value + self.UNDO_KEY_STRUCT.pack(height, block_hash)
        undo_c_f = self.column_families[DB_PREFIXES.undo.value]
        undo_info = self._db.get((undo_c_f, undo_key))
        self._op_stack.apply_packed_undo_ops(undo_info)
        try:
            with self._db.write_batch(sync=True) as batch:
                batch_put = batch.put
                batch_delete = batch.delete
                get_column_family = self.column_families.__getitem__
                for staged_change in self._op_stack:
                    column_family = get_column_family(DB_PREFIXES(staged_change.key[:1]).value)
                    if staged_change.is_put:
                        batch_put((column_family, staged_change.key), staged_change.value)
                    else:
                        batch_delete((column_family, staged_change.key))
                # batch_delete(undo_key)
        finally:
            self._op_stack.clear()

    def get(self, key: bytes, fill_cache: bool = True) -> Optional[bytes]:
        cf = self.column_families[key[:1]]
        return self._db.get((cf, key), fill_cache=fill_cache)

    def iterator(self, start: bytes, column_family: 'rocksdb.ColumnFamilyHandle' = None,
                 iterate_lower_bound: bytes = None, iterate_upper_bound: bytes = None,
                 reverse: bool = False, include_key: bool = True, include_value: bool = True,
                 fill_cache: bool = True, prefix_same_as_start: bool = True, auto_prefix_mode: bool = True):
        return self._db.iterator(
            start=start, column_family=column_family, iterate_lower_bound=iterate_lower_bound,
            iterate_upper_bound=iterate_upper_bound, reverse=reverse, include_key=include_key,
            include_value=include_value, fill_cache=fill_cache, prefix_same_as_start=prefix_same_as_start,
            auto_prefix_mode=auto_prefix_mode
        )

    def close(self):
        self._db.close()

    def try_catch_up_with_primary(self):
        self._db.try_catch_up_with_primary()

    @property
    def closed(self) -> bool:
        return self._db.is_closed

    def stage_raw_put(self, key: bytes, value: bytes):
        self._op_stack.append_op(RevertablePut(key, value))

    def stage_raw_delete(self, key: bytes, value: bytes):
        self._op_stack.append_op(RevertableDelete(key, value))
