import sqlite3
import os
import logging

log = logging.getLogger(__name__)


def do_migration(db_dir):
    log.info("Doing the migration")
    migrate_dbs(db_dir)
    log.info("Migration succeeded")


def get_blob_dict(blob_hash, stream_hash=None, position=None, iv=None, length=None,
                  last_verified=None, next_announce_time=None):
    assert blob_hash is not None and blob_hash is not False
    return {
        blob_hash: {
            'stream_hash': stream_hash,
            'position': position,
            'iv': iv,
            'length': length,
            'last_verified': last_verified,
            'next_announce_time': next_announce_time
        }
    }


def dump_table(cursor, table_name):
    query = "select * from %s" % table_name
    return cursor.execute(query).fetchall()


def get_stream_hash_by_sd(lbry_files, sd_hash):
    for stream_hash in lbry_files:
        if lbry_files[stream_hash].get('sd_hash') == sd_hash:
            return stream_hash
    return False


def migrate_dbs(db_dir):
    # old databases
    blob_db_path = os.path.join(db_dir, "blobs.db")
    blockchainname_path = os.path.join(db_dir, "blockchainname.db")
    lbryfile_info_path = os.path.join(db_dir, "lbryfile_info.db")

    # new database
    lbry_db_path = os.path.join(db_dir, "lbry.sqlite")

    # skip migration on fresh installs
    if not (os.path.isfile(blob_db_path) and os.path.isfile(blockchainname_path) and
                os.path.isfile(lbryfile_info_path)):
        return

    lbry_db = sqlite3.connect(lbry_db_path)
    lbry_cursor = lbry_db.cursor()

    blob_db = sqlite3.connect(blob_db_path)
    blockchainname_db = sqlite3.connect(blockchainname_path)
    lbryfile_info_db = sqlite3.connect(lbryfile_info_path)

    blob_cursor = blob_db.cursor()
    blockchainname_cursor = blockchainname_db.cursor()
    lbryfile_info_cursor = lbryfile_info_db.cursor()

    # make the new tables
    create_table_queries = [
        ("CREATE TABLE IF NOT EXISTS claims ("
         "id INTEGER PRIMARY KEY AUTOINCREMENT, "
         "name TEXT NOT NULL, "
         "status TEXT NOT NULL,"
         "txid TEXT NOT NULL, "
         "nout INTEGER, "
         "amount INTEGER, "
         "height INTEGER, "
         "claim_transaction_id TEXT, "
         "sd_blob_id TEXT, "
         "is_mine BOOLEAN "
         ")"),

        ("CREATE TABLE IF NOT EXISTS winning_claims ("
         "id INTEGER PRIMARY KEY AUTOINCREMENT, "
         "name TEXT NOT NULL UNIQUE, "
         "claim_id INTEGER UNIQUE NOT NULL, "
         "last_checked INTEGER, "
         "FOREIGN KEY(claim_id) REFERENCES claims(id) "
         "ON DELETE SET NULL ON UPDATE SET NULL "
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
         "suggested_file_name TEXT, "
         "claim_id INTEGER, "
         "FOREIGN KEY(claim_id) REFERENCES claims(id) "
         "ON DELETE SET NULL ON UPDATE CASCADE "
         "FOREIGN KEY(sd_blob_id) REFERENCES blobs(id) "
         "ON DELETE CASCADE ON UPDATE CASCADE)"),

        ("CREATE TABLE IF NOT EXISTS stream_terminators ("
         "id INTEGER PRIMARY KEY, "
         "blob_count INTEGER NOT NULL, "
         "iv TEXT, "
         "FOREIGN KEY(id) REFERENCES files(id) "
         "ON DELETE CASCADE ON UPDATE CASCADE)"
         ),

        ("CREATE TABLE IF NOT EXISTS blobs ("
         "id INTEGER PRIMARY KEY AUTOINCREMENT, "
         "blob_hash TEXT UNIQUE NOT NULL"
         ")"),

        ("CREATE TABLE IF NOT EXISTS managed_blobs ("
         "id INTEGER PRIMARY KEY, "
         "file_id INTEGER, "
         "stream_position INTEGER, "
         "iv TEXT, "
         "blob_length INTEGER, "
         "last_verified_time INTEGER, "
         "last_announced_time INTEGER, "
         "next_announce_time INTEGER, "
         "FOREIGN KEY(file_id) REFERENCES files(id) "
         "ON DELETE SET NULL ON UPDATE CASCADE,"
         "FOREIGN KEY(id) REFERENCES blobs(id) "
         "ON DELETE CASCADE ON UPDATE CASCADE"
         ")"),

        ("CREATE TABLE IF NOT EXISTS blob_transfer_history ("
         "id INTEGER PRIMARY KEY AUTOINCREMENT, "
         "blob_id INTEGER, "
         "peer_ip TEXT NOT NULL, "
         "downloaded boolean, "
         "rate REAL NOT NULL,"
         "time INTEGER NOT NULL,"
         "FOREIGN KEY(blob_id) REFERENCES blobs(id) "
         "ON DELETE SET NULL ON UPDATE CASCADE"
         ")")
    ]
    for make_table in create_table_queries:
        lbry_cursor.execute(make_table)

    lbry_db.commit()

    _blobs = dump_table(blob_cursor, "blobs")
    _stream_blobs = dump_table(lbryfile_info_cursor, "lbry_file_blobs")
    _lbry_file_options = dump_table(lbryfile_info_cursor, "lbry_file_options")
    _lbry_files = dump_table(lbryfile_info_cursor, "lbry_files")
    _stream_descriptors = dump_table(lbryfile_info_cursor, "lbry_file_descriptors")
    _claim_metadata = dump_table(blockchainname_cursor, "name_metadata")
    _claims = dump_table(blockchainname_cursor, "claim_ids")

    blobs = {}
    lbry_files = {}

    for blob_hash, stream_hash, position, iv, length in _stream_blobs:
        if blob_hash:
            blobs.update(get_blob_dict(blob_hash, stream_hash=stream_hash, position=position,
                                       iv=iv, length=length))
        if stream_hash not in lbry_files:
            lbry_files[stream_hash] = {
                'blobs': [blob_hash]
            }
        else:
            lbry_files[stream_hash]['blobs'].append(blob_hash)

    for blob_hash, blob_length, last_verified, next_announce in _blobs:
        if blob_hash and blob_hash not in blobs:
            blobs.update(get_blob_dict(blob_hash, length=blob_length, last_verified=last_verified,
                                       next_announce_time=next_announce))
        elif blob_hash:
            blobs[blob_hash]['length'] = length
            blobs[blob_hash]['last_verified'] = last_verified
            blobs[blob_hash]['next_announce_time'] = next_announce

    for data_rate, status, stream_hash in _lbry_file_options:
        lbry_files[stream_hash]['blob_data_rate'] = data_rate or 0.0
        lbry_files[stream_hash]['status'] = status or "pending"

    for stream_hash, decryption_key, stream_name, suggested_file_name in _lbry_files:
        lbry_files[stream_hash]['decryption_key'] = decryption_key
        lbry_files[stream_hash]['published_file_name'] = stream_name
        lbry_files[stream_hash]['suggested_file_name'] = suggested_file_name

    for sd_hash, stream_hash in _stream_descriptors:
        lbry_files[stream_hash]['sd_hash'] = sd_hash

    claim_ids_needed = {}

    for name, txid, nout, sd_hash in _claim_metadata:
        stream_hash = get_stream_hash_by_sd(lbry_files, sd_hash)
        if stream_hash:
            lbry_files[stream_hash]['name'] = name
            lbry_files[stream_hash]['txid'] = txid
            lbry_files[stream_hash]['nout'] = nout
            lbry_files[stream_hash]['sd_hash'] = sd_hash
            claim_ids_needed.update({(txid, nout): stream_hash})

    for claim_id, name, txid, nout in _claims:
        if (txid, nout) in claim_ids_needed:
            stream_hash = claim_ids_needed[(txid, nout)]
            lbry_files[stream_hash]['claim_transaction_id'] = claim_id

    for stream_hash in lbry_files:
        lbry_cursor.execute("INSERT INTO claims VALUES "
                            "(NULL, ?, ?, ?, ?, NULL, NULL, ?, NULL, NULL)",
                            (lbry_files[stream_hash]['name'],
                             "MISSING_METADATA",
                             lbry_files[stream_hash]['txid'],
                             lbry_files[stream_hash]['nout'],
                             lbry_files[stream_hash]['claim_transaction_id']))

        claim_row_id = lbry_cursor.lastrowid
        lbry_cursor.execute("INSERT INTO files VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (lbry_files[stream_hash]['status'],
                             lbry_files[stream_hash]['blob_data_rate'],
                             stream_hash,
                             None,
                             lbry_files[stream_hash]['decryption_key'],
                             lbry_files[stream_hash]['published_file_name'],
                             lbry_files[stream_hash]['suggested_file_name'],
                             claim_row_id))

    for blob_hash in blobs:
        lbry_cursor.execute("INSERT INTO blobs VALUES (NULL, ?)", (blob_hash, ))
        blob_id = lbry_cursor.lastrowid
        file_id = lbry_cursor.execute("SELECT id FROM files WHERE stream_hash=?",
                                      (blobs[blob_hash]['stream_hash'],)).fetchone()
        if file_id:
            file_id = file_id[0]
        else:
            file_id = None

        lbry_cursor.execute("INSERT INTO managed_blobs VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
                            (blob_id, file_id, blobs[blob_hash]['position'], blobs[blob_hash]['iv'],
                             blobs[blob_hash]['length'], blobs[blob_hash]['last_verified'],
                             blobs[blob_hash]['next_announce_time']))

    lbry_db.commit()
    lbry_db.close()

    log.info("Migrated %i blobs to new database", len(blobs))
    log.info("Migrated %i streams to new database", len(lbry_files))
    log.info("It is safe to delete %s", blob_db_path)
    log.info("It is safe to delete %s", blockchainname_path)
    log.info("It is safe to delete %s", lbryfile_info_path)
