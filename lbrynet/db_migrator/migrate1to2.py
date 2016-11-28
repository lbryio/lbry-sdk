import sqlite3
import os
import logging

log = logging.getLogger(__name__)
UNSET_NOUT = -1

def do_migration(db_dir):
    log.info("Doing the migration")
    migrate_blockchainname_db(db_dir)
    log.info("Migration succeeded")


def migrate_blockchainname_db(db_dir):
    blockchainname_db = os.path.join(db_dir, "blockchainname.db")
    # skip migration on fresh installs
    if not os.path.isfile(blockchainname_db):
        return
    temp_db = sqlite3.connect(":memory:")
    db_file = sqlite3.connect(blockchainname_db)
    file_cursor = db_file.cursor()
    mem_cursor = temp_db.cursor()

    mem_cursor.execute("create table if not exists name_metadata ("
                       "    name text, "
                       "    txid text, "
                       "    n integer, "
                       "    sd_hash text)")
    mem_cursor.execute("create table if not exists claim_ids ("
                       "    claimId text, "
                       "    name text, "
                       "    txid text, "
                       "    n integer)")
    temp_db.commit()

    name_metadata = file_cursor.execute("select * from name_metadata").fetchall()
    claim_metadata = file_cursor.execute("select * from claim_ids").fetchall()

    # fill n as V1_UNSET_NOUT, Wallet.py will be responsible for filling in correct n
    for name, txid, sd_hash in name_metadata:
        mem_cursor.execute(
            "insert into name_metadata values (?, ?, ?, ?) ",
            (name, txid, UNSET_NOUT, sd_hash))

    for claim_id, name, txid in claim_metadata:
        mem_cursor.execute(
            "insert into claim_ids values (?, ?, ?, ?)",
            (claim_id, name, txid, UNSET_NOUT))
    temp_db.commit()

    new_name_metadata = mem_cursor.execute("select * from name_metadata").fetchall()
    new_claim_metadata = mem_cursor.execute("select * from claim_ids").fetchall()

    file_cursor.execute("drop table name_metadata")
    file_cursor.execute("create table name_metadata ("
                        "    name text, "
                        "    txid text, "
                        "    n integer, "
                        "    sd_hash text)")

    for name, txid, n, sd_hash in new_name_metadata:
        file_cursor.execute("insert into name_metadata values (?, ?, ?, ?) ", (name, txid, n, sd_hash))

    file_cursor.execute("drop table claim_ids")
    file_cursor.execute("create table claim_ids ("
                        "    claimId text, "
                        "    name text, "
                        "    txid text, "
                        "    n integer)")

    for claim_id, name, txid, n in new_claim_metadata:
        file_cursor.execute("insert into claim_ids values (?, ?, ?, ?)", (claim_id, name, txid, n))

    db_file.commit()
    db_file.close()
    temp_db.close()
