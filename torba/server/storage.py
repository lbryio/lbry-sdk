# Copyright (c) 2016-2017, the ElectrumX authors
#
# All rights reserved.
#
# See the file "LICENCE" for information about the copyright
# and warranty status of this software.

'''Backend database abstraction.'''

import os
from functools import partial

from torba.server import util


def db_class(name):
    '''Returns a DB engine class.'''
    for db_class in util.subclasses(Storage):
        if db_class.__name__.lower() == name.lower():
            db_class.import_module()
            return db_class
    raise RuntimeError('unrecognised DB engine "{}"'.format(name))


class Storage:
    '''Abstract base class of the DB backend abstraction.'''

    def __init__(self, name, for_sync):
        self.is_new = not os.path.exists(name)
        self.for_sync = for_sync or self.is_new
        self.open(name, create=self.is_new)

    @classmethod
    def import_module(cls):
        '''Import the DB engine module.'''
        raise NotImplementedError

    def open(self, name, create):
        '''Open an existing database or create a new one.'''
        raise NotImplementedError

    def close(self):
        '''Close an existing database.'''
        raise NotImplementedError

    def get(self, key):
        raise NotImplementedError

    def put(self, key, value):
        raise NotImplementedError

    def write_batch(self):
        '''Return a context manager that provides `put` and `delete`.

        Changes should only be committed when the context manager
        closes without an exception.
        '''
        raise NotImplementedError

    def iterator(self, prefix=b'', reverse=False):
        '''Return an iterator that yields (key, value) pairs from the
        database sorted by key.

        If `prefix` is set, only keys starting with `prefix` will be
        included.  If `reverse` is True the items are returned in
        reverse order.
        '''
        raise NotImplementedError


class LevelDB(Storage):
    '''LevelDB database engine.'''

    @classmethod
    def import_module(cls):
        import plyvel
        cls.module = plyvel

    def open(self, name, create):
        mof = 512 if self.for_sync else 128
        # Use snappy compression (the default)
        self.db = self.module.DB(name, create_if_missing=create,
                                 max_open_files=mof)
        self.close = self.db.close
        self.get = self.db.get
        self.put = self.db.put
        self.iterator = self.db.iterator
        self.write_batch = partial(self.db.write_batch, transaction=True,
                                   sync=True)


class RocksDB(Storage):
    '''RocksDB database engine.'''

    @classmethod
    def import_module(cls):
        import rocksdb
        cls.module = rocksdb

    def open(self, name, create):
        mof = 512 if self.for_sync else 128
        # Use snappy compression (the default)
        options = self.module.Options(create_if_missing=create,
                                      use_fsync=True,
                                      target_file_size_base=33554432,
                                      max_open_files=mof)
        self.db = self.module.DB(name, options)
        self.get = self.db.get
        self.put = self.db.put

    def close(self):
        # PyRocksDB doesn't provide a close method; hopefully this is enough
        self.db = self.get = self.put = None
        import gc
        gc.collect()

    def write_batch(self):
        return RocksDBWriteBatch(self.db)

    def iterator(self, prefix=b'', reverse=False):
        return RocksDBIterator(self.db, prefix, reverse)


class RocksDBWriteBatch:
    '''A write batch for RocksDB.'''

    def __init__(self, db):
        self.batch = RocksDB.module.WriteBatch()
        self.db = db

    def __enter__(self):
        return self.batch

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not exc_val:
            self.db.write(self.batch)


class RocksDBIterator:
    '''An iterator for RocksDB.'''

    def __init__(self, db, prefix, reverse):
        self.prefix = prefix
        if reverse:
            self.iterator = reversed(db.iteritems())
            nxt_prefix = util.increment_byte_string(prefix)
            if nxt_prefix:
                self.iterator.seek(nxt_prefix)
                try:
                    next(self.iterator)
                except StopIteration:
                    self.iterator.seek(nxt_prefix)
            else:
                self.iterator.seek_to_last()
        else:
            self.iterator = db.iteritems()
            self.iterator.seek(prefix)

    def __iter__(self):
        return self

    def __next__(self):
        k, v = next(self.iterator)
        if not k.startswith(self.prefix):
            raise StopIteration
        return k, v
