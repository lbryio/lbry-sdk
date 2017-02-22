import os
import logging

from twisted.internet import defer
from twisted.enterprise import adbapi
from lbrynet import conf

log = logging.getLogger(__name__)


class Storage(object):
    def __init__(self, db_dir=None):
        self.db_dir = db_dir
        self._is_open = False

    @property
    def db_path(self):
        return os.path.join(self.db_dir, "lbry.sqlite")

    @property
    def is_open(self):
        return self._is_open is True

    @defer.inlineCallbacks
    def open(self):
        if not self.is_open:
            yield self._open()
        defer.returnValue(None)

    @defer.inlineCallbacks
    def close(self):
        if self.is_open:
            self._is_open = False
            yield self._close()
        defer.returnValue(True)

    @defer.inlineCallbacks
    def query(self, query, args=None):
        result = yield self._query(query, args)
        defer.returnValue(result)

    def _query(self, query, args=None):
        return None

    def _open(self):
        return True

    def _close(self):
        return True


class SqliteStorage(Storage):
    def __init__(self, db_dir=conf.default_data_dir):
        Storage.__init__(self, db_dir)
        self.sqlite_db = None

    @defer.inlineCallbacks
    def _query(self, query, args=None):
        query_str = query.replace("?", "%s")
        if args:
            query_str %= args
        try:
            if args:
                results = yield self.sqlite_db.runQuery(query, args)
            else:
                results = yield self.sqlite_db.runQuery(query)
        except Exception as err:
            err_msg = "%s - %s\n%s" % (err.__class__.__name__, err.message, query_str)
            raise Exception(err_msg)
        defer.returnValue(results)

    @defer.inlineCallbacks
    def _open(self):
        log.info("Opening database: %s", self.db_path)
        self.sqlite_db = adbapi.ConnectionPool("sqlite3", self.db_path, check_same_thread=False)
        create_table_queries = [
            ("CREATE TABLE IF NOT EXISTS claims ("
             "id INTEGER PRIMARY KEY AUTOINCREMENT, "
             "name TEXT NOT NULL, "
             "status TEXT NOT NULL,"
             "txid TEXT NOT NULL, "
             "nout INTEGER, "
             "claim_transaction_id TEXT NOT NULL"
             ")"),

            ("CREATE TABLE IF NOT EXISTS metadata ("
             "id INTEGER PRIMARY KEY AUTOINCREMENT, "
             "value BLOB,"
             "FOREIGN KEY(id) REFERENCES claims(id) "
             "ON DELETE CASCADE ON UPDATE CASCADE "
             ")"),

            ("CREATE TABLE IF NOT EXISTS files ("
             "id INTEGER PRIMARY KEY AUTOINCREMENT, "
             "status TEXT NOT NULL,"
             "blob_data_rate REAL, "
             "stream_hash TEXT UNIQUE, "
             "sd_blob_id INTEGER, "
             "decryption_key TEXT, "
             "published_file_name TEXT, "
             "claim_id INTEGER, "
             "FOREIGN KEY(claim_id) REFERENCES claims(id) "
             "ON DELETE SET NULL ON UPDATE CASCADE "
             "FOREIGN KEY(sd_blob_id) REFERENCES blobs(id) "
             "ON DELETE CASCADE ON UPDATE CASCADE)"),

            ("CREATE TABLE IF NOT EXISTS blobs ("
             "id INTEGER PRIMARY KEY AUTOINCREMENT, "
             "blob_hash TEXT UNIQUE NOT NULL"
             ")"),

            ("CREATE TABLE IF NOT EXISTS managed_blobs ("
             "id INTEGER PRIMARY KEY AUTOINCREMENT, "
             "blob_id INTEGER, "
             "file_id INTEGER, "
             "stream_position INTEGER, "
             "iv TEXT, "
             "blob_length INTEGER, "
             "last_verified_time INTEGER, "
             "last_announced_time INTEGER, "
             "next_announce_time INTEGER, "
             "FOREIGN KEY(file_id) REFERENCES files(id) "
             "ON DELETE set NULL ON UPDATE CASCADE,"
             "FOREIGN KEY(blob_id) REFERENCES blobs(id) "
             "ON DELETE CASCADE ON UPDATE CASCADE"
             ")"),

            ("CREATE TABLE IF NOT EXISTS blob_transfer_history ("
             "id INTEGER PRIMARY KEY AUTOINCREMENT, "
             "blob_id INTEGER NOT NULL, "
             "peer_ip TEXT NOT NULL, "
             "downloaded boolean, "
             "rate REAL NOT NULL,"
             "time INTEGER NOT NULL,"
             "FOREIGN KEY(blob_id) REFERENCES blobs(id) "
             "ON DELETE SET NULL ON UPDATE CASCADE"
             ")")
        ]

        for create_table_query in create_table_queries:
            yield self.sqlite_db.runQuery(create_table_query)
        yield self.sqlite_db.runQuery("pragma foreign_keys=1")
        self._is_open = True
        defer.returnValue(None)

    def _close(self):
        yield self.sqlite_db.close()
