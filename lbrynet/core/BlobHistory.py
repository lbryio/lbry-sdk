import os
from twisted.enterprise import adbapi
import time


class BlobHistoryManager(object):
    """
    Class to archive historical blob upload and download information

    This class creates two tables in lbry data folder/blob_history.db, 'download' and 'upload'
    The tables store information about what blob was uploaded or downloaded, to or from which peer,
    at what price, and when.
    """

    def __init__(self, db_dir):
        self.db = None
        self.db_dir = db_dir

    def _open_db(self):
        self.db = adbapi.ConnectionPool('sqlite3', os.path.join(self.db_dir, "blob_history.db"),
                                        check_same_thread=False)

        def create_tables(transaction):
            transaction.execute("create table if not exists download (" +
                                "    id integer primary key autoincrement, " +
                                "    blob text, " +
                                "    host text, " +
                                "    rate float, " +
                                "    ts integer)")

            transaction.execute("create table if not exists upload (" +
                                "    id integer primary key autoincrement, " +
                                "    blob text, " +
                                "    host text, " +
                                "    rate float, " +
                                "    ts integer)")

        return self.db.runInteraction(create_tables)

    def add_transaction(self, blob_hash, host, rate, upload=False):
        ts = int(time.time())
        if upload:
            d = self.db.runQuery("insert into upload values (null, ?, ?, ?, ?) ", (blob_hash, str(host), float(rate), ts))
        else:
            d = self.db.runQuery("insert into download values (null, ?, ?, ?, ?) ", (blob_hash, str(host), float(rate), ts))
        return d

    def start(self):
        d = self._open_db()
        return d


