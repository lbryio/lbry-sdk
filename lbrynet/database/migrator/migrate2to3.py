import sqlite3
import os
import logging

log = logging.getLogger(__name__)


def do_migration(db_dir):
    log.info("Doing the migration")
    migrate_blockchainname_db(db_dir)
    log.info("Migration succeeded")


def migrate_blockchainname_db(db_dir):
    blockchainname_db = os.path.join(db_dir, "blockchainname.db")
    # skip migration on fresh installs
    if not os.path.isfile(blockchainname_db):
        return

    db_file = sqlite3.connect(blockchainname_db)
    file_cursor = db_file.cursor()

    tables = file_cursor.execute("SELECT tbl_name FROM sqlite_master "
                                 "WHERE type='table'").fetchall()

    if 'tmp_name_metadata_table' in tables and 'name_metadata' not in tables:
        file_cursor.execute("ALTER TABLE tmp_name_metadata_table RENAME TO name_metadata")
    else:
        file_cursor.executescript(
            "CREATE TABLE IF NOT EXISTS tmp_name_metadata_table "
            "    (name TEXT UNIQUE NOT NULL, "
            "     txid TEXT NOT NULL, "
            "     n INTEGER NOT NULL, "
            "     sd_hash TEXT NOT NULL); "
            "INSERT OR IGNORE INTO tmp_name_metadata_table "
            "    (name, txid, n, sd_hash) "
            "    SELECT name, txid, n, sd_hash FROM name_metadata; "
            "DROP TABLE name_metadata; "
            "ALTER TABLE tmp_name_metadata_table RENAME TO name_metadata;"
        )
    db_file.commit()
    db_file.close()
