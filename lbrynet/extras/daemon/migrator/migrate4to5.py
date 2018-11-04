import sqlite3
import os
import logging

log = logging.getLogger(__name__)


def do_migration(db_dir):
    log.info("Doing the migration")
    add_lbry_file_metadata(db_dir)
    log.info("Migration succeeded")


def add_lbry_file_metadata(db_dir):
    """
    We migrate the blobs.db used in BlobManager to have a "should_announce" column,
    and set this to True for blobs that are sd_hash's or head blobs (first blob in stream)
    """

    name_metadata = os.path.join(db_dir, "blockchainname.db")
    lbryfile_info_db = os.path.join(db_dir, 'lbryfile_info.db')

    if not os.path.isfile(name_metadata) and not os.path.isfile(lbryfile_info_db):
        return

    if not os.path.isfile(lbryfile_info_db):
        log.error(
            "blockchainname.db was not found but lbryfile_info.db was found, skipping migration")
        return

    name_metadata_db = sqlite3.connect(name_metadata)
    lbryfile_db = sqlite3.connect(lbryfile_info_db)
    name_metadata_cursor = name_metadata_db.cursor()
    lbryfile_cursor = lbryfile_db.cursor()

    lbryfile_db.executescript(
        "create table if not exists lbry_file_metadata (" +
        "    lbry_file integer primary key, " +
        "    txid text, " +
        "    n integer, " +
        "    foreign key(lbry_file) references lbry_files(rowid)"
        ")")

    _files = lbryfile_cursor.execute("select rowid, stream_hash from lbry_files").fetchall()

    lbry_files = {x[1]: x[0] for x in _files}
    for (sd_hash, stream_hash) in lbryfile_cursor.execute("select * "
                                                          "from lbry_file_descriptors").fetchall():
        lbry_file_id = lbry_files[stream_hash]
        outpoint = name_metadata_cursor.execute("select txid, n from name_metadata "
                                                "where sd_hash=?",
                                                (sd_hash,)).fetchall()
        if outpoint:
            txid, nout = outpoint[0]
            lbryfile_cursor.execute("insert into lbry_file_metadata values (?, ?, ?)",
                                    (lbry_file_id, txid, nout))
        else:
            lbryfile_cursor.execute("insert into lbry_file_metadata values (?, ?, ?)",
                                    (lbry_file_id, None, None))
    lbryfile_db.commit()

    lbryfile_db.close()
    name_metadata_db.close()
