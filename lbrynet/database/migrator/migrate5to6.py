import sqlite3
import os
import json
import logging
from lbryschema.decode import smart_decode
from lbrynet import conf
from lbrynet.database.storage import SQLiteStorage

log = logging.getLogger(__name__)

default_download_directory = conf.default_download_dir


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


def verify_sd_blob(sd_hash, blob_dir):
    with open(os.path.join(blob_dir, sd_hash), "r") as sd_file:
        data = sd_file.read()
        sd_length = len(data)
        decoded = json.loads(data)
    assert set(decoded.keys()) == {
        'stream_name', 'blobs', 'stream_type', 'key', 'suggested_file_name', 'stream_hash'
    }, "invalid sd blob"
    for blob in sorted(decoded['blobs'], key=lambda x: int(x['blob_num']), reverse=True):
        if blob['blob_num'] == len(decoded['blobs']) - 1:
            assert {'length', 'blob_num', 'iv'} == set(blob.keys()), 'invalid stream terminator'
            assert blob['length'] == 0, 'non zero length stream terminator'
        else:
            assert {'blob_hash', 'length', 'blob_num', 'iv'} == set(blob.keys()), 'invalid stream blob'
            assert blob['length'] > 0, 'zero length stream blob'
    return decoded, sd_length


def do_migration(db_dir):
    new_db_path = os.path.join(db_dir, "lbrynet.sqlite")
    connection = sqlite3.connect(new_db_path)

    metadata_db = sqlite3.connect(os.path.join(db_dir, "blockchainname.db"))
    lbryfile_db = sqlite3.connect(os.path.join(db_dir, 'lbryfile_info.db'))
    blobs_db = sqlite3.connect(os.path.join(db_dir, 'blobs.db'))

    name_metadata_cursor = metadata_db.cursor()
    lbryfile_cursor = lbryfile_db.cursor()
    blobs_db_cursor = blobs_db.cursor()

    old_rowid_to_outpoint = {
        rowid: (txid, nout) for (rowid, txid, nout) in
        lbryfile_cursor.execute("select * from lbry_file_metadata").fetchall()
    }

    old_sd_hash_to_outpoint = {
        sd_hash: (txid, nout) for (txid, nout, sd_hash) in
        name_metadata_cursor.execute("select txid, n, sd_hash from name_metadata").fetchall()
    }

    sd_hash_to_stream_hash = {
        sd_hash: stream_hash for (sd_hash, stream_hash) in
        lbryfile_cursor.execute("select sd_blob_hash, stream_hash from lbry_file_descriptors").fetchall()
    }

    stream_hash_to_stream_blobs = {}

    for (blob_hash, stream_hash, position, iv, length) in lbryfile_db.execute(
            "select * from lbry_file_blobs").fetchall():
        stream_blobs = stream_hash_to_stream_blobs.get(stream_hash, [])
        stream_blobs.append((blob_hash, length, position, iv))
        stream_hash_to_stream_blobs[stream_hash] = stream_blobs

    claim_outpoint_queries = {}

    for claim_query in metadata_db.execute(
            "select distinct c.txid, c.n, c.claimId, c.name, claim_cache.claim_sequence, claim_cache.claim_address, "
            "claim_cache.height, claim_cache.amount, claim_cache.claim_pb "
            "from claim_cache inner join claim_ids c on claim_cache.claim_id=c.claimId"):
        txid, nout = claim_query[0], claim_query[1]
        if (txid, nout) in claim_outpoint_queries:
            continue
        claim_outpoint_queries[(txid, nout)] = claim_query

    @run_operation(connection)
    def _populate_blobs(transaction, blob_infos):
        transaction.executemany(
            "insert into blob values (?, ?, ?, ?, ?)",
            [(blob_hash, blob_length, int(next_announce_time), should_announce, "finished")
             for (blob_hash, blob_length, _, next_announce_time, should_announce) in blob_infos]
        )

    @run_operation(connection)
    def _import_file(transaction, sd_hash, stream_hash, key, stream_name, suggested_file_name, data_rate,
                     status, stream_blobs):
        try:
            transaction.execute(
                "insert or ignore into stream values (?, ?, ?, ?, ?)",
                (stream_hash, sd_hash, key, stream_name, suggested_file_name)
            )
        except sqlite3.IntegrityError:
            # failed because the sd isn't a known blob, we'll try to read the blob file and recover it
            return sd_hash

        # insert any stream blobs that were missing from the blobs table
        transaction.executemany(
            "insert or ignore into blob values (?, ?, ?, ?, ?)",
            [
                (blob_hash, length, 0, 0, "pending")
                for (blob_hash, length, position, iv) in stream_blobs
            ]
        )

        # insert the stream blobs
        for blob_hash, length, position, iv in stream_blobs:
            transaction.execute(
                "insert or ignore into stream_blob values (?, ?, ?, ?)",
                (stream_hash, blob_hash, position, iv)
            )

        # insert the file
        transaction.execute(
            "insert or ignore into file values (?, ?, ?, ?, ?)",
            (stream_hash, stream_name, default_download_directory.encode('hex'),
             data_rate, status)
        )

    @run_operation(connection)
    def _add_recovered_blobs(transaction, blob_infos, sd_hash, sd_length):
        transaction.execute(
            "insert or replace into blob values (?, ?, ?, ?, ?)", (sd_hash, sd_length, 0, 1, "finished")
        )
        for blob in sorted(blob_infos, key=lambda x: x['blob_num'], reverse=True):
            if blob['blob_num'] < len(blob_infos) - 1:
                transaction.execute(
                    "insert or ignore into blob values (?, ?, ?, ?, ?)",
                    (blob['blob_hash'], blob['length'], 0, 0, "pending")
                )

    @run_operation(connection)
    def _make_db(new_db):
        # create the new tables
        new_db.executescript(SQLiteStorage.CREATE_TABLES_QUERY)

        # first migrate the blobs
        blobs = blobs_db_cursor.execute("select * from blobs").fetchall()
        _populate_blobs(blobs)
        log.info("migrated %i blobs", new_db.execute("select count(*) from blob").fetchone()[0])

        # used to store the query arguments if we need to try re-importing the lbry file later
        file_args = {}  # <sd_hash>: args tuple

        file_outpoints = {}  # <outpoint tuple>: sd_hash

        # get the file and stream queries ready
        for (rowid, sd_hash, stream_hash, key, stream_name, suggested_file_name, data_rate, status) in \
            lbryfile_db.execute(
                "select distinct lbry_files.rowid, d.sd_blob_hash, lbry_files.*, o.blob_data_rate, o.status "
                "from lbry_files "
                "inner join lbry_file_descriptors d on lbry_files.stream_hash=d.stream_hash "
                "inner join lbry_file_options o on lbry_files.stream_hash=o.stream_hash"):

            # this is try to link the file to a content claim after we've imported all the files
            if rowid in old_rowid_to_outpoint:
                file_outpoints[old_rowid_to_outpoint[rowid]] = sd_hash
            elif sd_hash in old_sd_hash_to_outpoint:
                file_outpoints[old_sd_hash_to_outpoint[sd_hash]] = sd_hash

            sd_hash_to_stream_hash[sd_hash] = stream_hash
            if stream_hash in stream_hash_to_stream_blobs:
                file_args[sd_hash] = (
                    sd_hash, stream_hash, key, stream_name,
                    suggested_file_name, data_rate or 0.0,
                    status, stream_hash_to_stream_blobs.pop(stream_hash)
                )

        # used to store the query arguments if we need to try re-importing the claim
        claim_queries = {}  # <sd_hash>: claim query tuple

        # get the claim queries ready, only keep those with associated files
        for outpoint, sd_hash in file_outpoints.iteritems():
            if outpoint in claim_outpoint_queries:
                claim_queries[sd_hash] = claim_outpoint_queries[outpoint]

        # insert the claims
        new_db.executemany(
            "insert or ignore into claim values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "%s:%i" % (claim_arg_tup[0], claim_arg_tup[1]), claim_arg_tup[2], claim_arg_tup[3],
                    claim_arg_tup[7], claim_arg_tup[6], claim_arg_tup[8],
                    smart_decode(claim_arg_tup[8]).certificate_id, claim_arg_tup[5], claim_arg_tup[4]
                )
                for sd_hash, claim_arg_tup in claim_queries.iteritems() if claim_arg_tup
            ]     # sd_hash,  (txid, nout, claim_id, name, sequence, address, height, amount, serialized)
        )

        log.info("migrated %i claims", new_db.execute("select count(*) from claim").fetchone()[0])

        damaged_stream_sds = []
        # import the files and get sd hashes of streams to attempt recovering
        for sd_hash, file_query in file_args.iteritems():
            failed_sd = _import_file(*file_query)
            if failed_sd:
                damaged_stream_sds.append(failed_sd)

        # recover damaged streams
        if damaged_stream_sds:
            blob_dir = os.path.join(db_dir, "blobfiles")
            damaged_sds_on_disk = [] if not os.path.isdir(blob_dir) else list({p for p in os.listdir(blob_dir)
                                                                               if p in damaged_stream_sds})
            for damaged_sd in damaged_sds_on_disk:
                try:
                    decoded, sd_length = verify_sd_blob(damaged_sd, blob_dir)
                    _add_recovered_blobs(decoded['blobs'], damaged_sd, sd_length)
                    _import_file(*file_args[damaged_sd])
                    damaged_stream_sds.remove(damaged_sd)
                except (OSError, ValueError, TypeError, IOError, AssertionError, sqlite3.IntegrityError):
                    continue

        log.info("migrated %i files", new_db.execute("select count(*) from file").fetchone()[0])

        # associate the content claims to their respective files
        for claim_arg_tup in claim_queries.values():
            if claim_arg_tup and (claim_arg_tup[0], claim_arg_tup[1]) in file_outpoints \
                    and file_outpoints[(claim_arg_tup[0], claim_arg_tup[1])] in sd_hash_to_stream_hash:
                try:
                    new_db.execute(
                        "insert or ignore into content_claim values (?, ?)",
                        (
                            sd_hash_to_stream_hash.get(file_outpoints.get((claim_arg_tup[0], claim_arg_tup[1]))),
                            "%s:%i" % (claim_arg_tup[0], claim_arg_tup[1])
                        )
                    )
                except sqlite3.IntegrityError:
                    continue

        log.info("migrated %i content claims", new_db.execute("select count(*) from content_claim").fetchone()[0])

    _make_db()
    connection.close()
    blobs_db.close()
    lbryfile_db.close()
    metadata_db.close()
    os.remove(os.path.join(db_dir, "blockchainname.db"))
    os.remove(os.path.join(db_dir, 'lbryfile_info.db'))
    os.remove(os.path.join(db_dir, 'blobs.db'))
