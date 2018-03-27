import sqlite3
import os
import logging
from lbrynet.database.storage import SQLiteStorage

log = logging.getLogger(__name__)


def run_operation(db):
    def _decorate(fn):
        def _wrapper(*args):
            cursor = db.cursor()
            try:
                result = fn(cursor, *args)
                db.commit()
                return result
            except sqlite3.IntegrityError:
                db.rollback()
                raise
        return _wrapper
    return _decorate


def do_migration(db_dir):
    db_path = os.path.join(db_dir, "lbrynet.sqlite")
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()
    cursor.executescript("alter table blob add last_announced_time integer;")
    cursor.execute("update blob set next_announce_time=0")
    connection.commit()
    connection.close()
