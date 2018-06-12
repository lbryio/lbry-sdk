import logging
import os
import sqlite3
import traceback
from decimal import Decimal
from twisted.internet import defer, task, threads
from twisted.enterprise import adbapi

from lbryschema.claim import ClaimDict
from lbryschema.decode import smart_decode
from lbrynet import conf
from lbrynet.cryptstream.CryptBlob import CryptBlobInfo
from lbrynet.dht.constants import dataExpireTimeout
from lbrynet.wallet.database import SQLiteWalletStorage
from torba.constants import COIN

log = logging.getLogger(__name__)


def _get_next_available_file_name(download_directory, file_name):
    base_name, ext = os.path.splitext(file_name)
    i = 0
    while os.path.isfile(os.path.join(download_directory, file_name)):
        i += 1
        file_name = "%s_%i%s" % (base_name, i, ext)
    return os.path.join(download_directory, file_name)


def _open_file_for_writing(download_directory, suggested_file_name):
    file_path = _get_next_available_file_name(download_directory, suggested_file_name)
    try:
        file_handle = open(file_path, 'wb')
        file_handle.close()
    except IOError:
        log.error(traceback.format_exc())
        raise ValueError(
            "Failed to open %s. Make sure you have permission to save files to that location." % file_path
        )
    return os.path.basename(file_path)


def open_file_for_writing(download_directory, suggested_file_name):
    """
    Used to touch the path of a file to be downloaded

    :param download_directory: (str)
    :param suggested_file_name: (str)
    :return: (str) basename
    """
    return threads.deferToThread(_open_file_for_writing, download_directory, suggested_file_name)


def rerun_if_locked(f):
    max_attempts = 3

    def rerun(err, rerun_count, *args, **kwargs):
        connection = args[0]
        reactor = connection.reactor
        log.debug("Failed to execute (%s): %s", err, args)
        if err.check(sqlite3.OperationalError) and err.value.message == "database is locked":
            log.warning("database was locked. rerunning %s with args %s, kwargs %s",
                        str(f), str(args), str(kwargs))
            if rerun_count < max_attempts:
                delay = 2**rerun_count
                return task.deferLater(reactor, delay, inner_wrapper, rerun_count + 1, *args, **kwargs)
        raise err

    def check_needed_rerun(result, rerun_count):
        if rerun_count:
            log.info("successfully reran database query")
        return result

    def inner_wrapper(rerun_count, *args, **kwargs):
        d = f(*args, **kwargs)
        d.addCallback(check_needed_rerun, rerun_count)
        d.addErrback(rerun, rerun_count, *args, **kwargs)
        return d

    def wrapper(*args, **kwargs):
        return inner_wrapper(0, *args, **kwargs)

    return wrapper


class SqliteConnection(adbapi.ConnectionPool):
    def __init__(self, db_path):
        adbapi.ConnectionPool.__init__(self, 'sqlite3', db_path, check_same_thread=False)

    @rerun_if_locked
    def runInteraction(self, interaction, *args, **kw):
        return adbapi.ConnectionPool.runInteraction(self, interaction, *args, **kw)

    @classmethod
    def set_reactor(cls, reactor):
        cls.reactor = reactor


class SQLiteStorage(SQLiteWalletStorage):

    CREATE_TABLES_QUERY = """
            pragma foreign_keys=on;
            pragma journal_mode=WAL;
    
            create table if not exists blob (
                blob_hash char(96) primary key not null,
                blob_length integer not null,
                next_announce_time integer not null,
                should_announce integer not null default 0,
                status text not null,
                last_announced_time integer,
                single_announce integer
            );
            
            create table if not exists stream (
                stream_hash char(96) not null primary key,
                sd_hash char(96) not null references blob,
                stream_key text not null,
                stream_name text not null,
                suggested_filename text not null
            );
            
            create table if not exists stream_blob (
                stream_hash char(96) not null references stream,
                blob_hash char(96) references blob,
                position integer not null,
                iv char(32) not null,
                primary key (stream_hash, blob_hash)
            );
            
            create table if not exists claim (
                claim_outpoint text not null primary key,
                claim_id char(40) not null,
                claim_name text not null,
                amount integer not null,
                height integer not null,
                serialized_metadata blob not null,
                channel_claim_id text,
                address text not null,
                claim_sequence integer not null
            );

            create table if not exists file (
                stream_hash text primary key not null references stream,
                file_name text not null,
                download_directory text not null,
                blob_data_rate real not null,
                status text not null
            );
            
            create table if not exists content_claim (
                stream_hash text unique not null references file,
                claim_outpoint text not null references claim,
                primary key (stream_hash, claim_outpoint)
            );
            
            create table if not exists support (
                support_outpoint text not null primary key,
                claim_id text not null,
                amount integer not null,
                address text not null
            );
            
            create table if not exists reflected_stream (
                sd_hash text not null,
                reflector_address text not null,
                timestamp integer,
                primary key (sd_hash, reflector_address)
            );
    """ + SQLiteWalletStorage.CREATE_TABLES_QUERY

    def __init__(self, db_dir, reactor=None):
        if not reactor:
            from twisted.internet import reactor
        self.db_dir = db_dir
        self._db_path = os.path.join(db_dir, "lbrynet.sqlite")
        log.info("connecting to database: %s", self._db_path)
        self.db = SqliteConnection(self._db_path)
        self.db.set_reactor(reactor)
        self.clock = reactor

        # used to refresh the claim attributes on a ManagedEncryptedFileDownloader when a
        # change to the associated content claim occurs. these are added by the file manager
        # when it loads each file
        self.content_claim_callbacks = {}  # {<stream_hash>: <callable returning a deferred>}

    def setup(self):
        def _create_tables(transaction):
            transaction.executescript(self.CREATE_TABLES_QUERY)
        return self.db.runInteraction(_create_tables)

    @defer.inlineCallbacks
    def run_and_return_one_or_none(self, query, *args):
        result = yield self.db.runQuery(query, args)
        if result:
            defer.returnValue(result[0][0])
        else:
            defer.returnValue(None)

    @defer.inlineCallbacks
    def run_and_return_list(self, query, *args):
        result = yield self.db.runQuery(query, args)
        if result:
            defer.returnValue([i[0] for i in result])
        else:
            defer.returnValue([])

    def run_and_return_id(self, query, *args):
        def do_save(t):
            t.execute(query, args)
            return t.lastrowid
        return self.db.runInteraction(do_save)

    def stop(self):
        self.db.close()
        return defer.succeed(True)

    # # # # # # # # # blob functions # # # # # # # # #

    def add_completed_blob(self, blob_hash, length, next_announce_time, should_announce, status="finished"):
        log.debug("Adding a completed blob. blob_hash=%s, length=%i", blob_hash, length)
        values = (blob_hash, length, next_announce_time or 0, int(bool(should_announce)), status, 0, 0)
        return self.db.runOperation("insert or replace into blob values (?, ?, ?, ?, ?, ?, ?)", values)

    def set_should_announce(self, blob_hash, next_announce_time, should_announce):
        return self.db.runOperation(
            "update blob set next_announce_time=?, should_announce=? where blob_hash=?",
            (next_announce_time or 0, int(bool(should_announce)), blob_hash)
        )

    def get_blob_status(self, blob_hash):
        return self.run_and_return_one_or_none(
            "select status from blob where blob_hash=?", blob_hash
        )

    @defer.inlineCallbacks
    def add_known_blob(self, blob_hash, length):
        yield self.db.runOperation(
            "insert or ignore into blob values (?, ?, ?, ?, ?, ?, ?)", (blob_hash, length, 0, 0, "pending", 0, 0)
        )

    def should_announce(self, blob_hash):
        return self.run_and_return_one_or_none(
            "select should_announce from blob where blob_hash=?", blob_hash
        )

    def count_should_announce_blobs(self):
        return self.run_and_return_one_or_none(
            "select count(*) from blob where should_announce=1 and status='finished'"
        )

    def get_all_should_announce_blobs(self):
        return self.run_and_return_list(
            "select blob_hash from blob where should_announce=1 and status='finished'"
        )

    def update_last_announced_blob(self, blob_hash, last_announced):
        return self.db.runOperation(
                    "update blob set next_announce_time=?, last_announced_time=?, single_announce=0 where blob_hash=?",
                    (int(last_announced + (dataExpireTimeout / 2)), int(last_announced), blob_hash)
                )

    def should_single_announce_blobs(self, blob_hashes, immediate=False):
        def set_single_announce(transaction):
            now = self.clock.seconds()
            for blob_hash in blob_hashes:
                if immediate:
                    transaction.execute(
                        "update blob set single_announce=1, next_announce_time=? "
                        "where blob_hash=? and status='finished'", (int(now), blob_hash)
                    )
                else:
                    transaction.execute(
                        "update blob set single_announce=1 where blob_hash=? and status='finished'", (blob_hash, )
                    )
        return self.db.runInteraction(set_single_announce)

    def get_blobs_to_announce(self):
        def get_and_update(transaction):
            timestamp = self.clock.seconds()
            if conf.settings['announce_head_blobs_only']:
                r = transaction.execute(
                    "select blob_hash from blob "
                    "where blob_hash is not null and "
                    "(should_announce=1 or single_announce=1) and next_announce_time<? and status='finished'",
                    (timestamp,)
                )
            else:
                r = transaction.execute(
                    "select blob_hash from blob where blob_hash is not null "
                    "and next_announce_time<? and status='finished'", (timestamp,)
                )
            blobs = [b[0] for b in r.fetchall()]
            return blobs
        return self.db.runInteraction(get_and_update)

    def delete_blobs_from_db(self, blob_hashes):
        def delete_blobs(transaction):
            for blob_hash in blob_hashes:
                transaction.execute("delete from blob where blob_hash=?;", (blob_hash,))
        return self.db.runInteraction(delete_blobs)

    def get_all_blob_hashes(self):
        return self.run_and_return_list("select blob_hash from blob")

    # # # # # # # # # stream blob functions # # # # # # # # #

    def add_blobs_to_stream(self, stream_hash, blob_infos):
        def _add_stream_blobs(transaction):
            for blob_info in blob_infos:
                transaction.execute("insert into stream_blob values (?, ?, ?, ?)",
                                    (stream_hash, blob_info.get('blob_hash', None),
                                     blob_info['blob_num'], blob_info['iv']))
        return self.db.runInteraction(_add_stream_blobs)

    @defer.inlineCallbacks
    def add_known_blobs(self, blob_infos):
        for blob_info in blob_infos:
            if blob_info.get('blob_hash') and blob_info['length']:
                yield self.add_known_blob(blob_info['blob_hash'], blob_info['length'])

    def verify_will_announce_head_and_sd_blobs(self, stream_hash):
        # fix should_announce for imported head and sd blobs
        return self.db.runOperation(
            "update blob set should_announce=1 "
            "where should_announce=0 and "
            "blob.blob_hash in "
            "  (select b.blob_hash from blob b inner join stream s on b.blob_hash=s.sd_hash and s.stream_hash=?) "
            "or blob.blob_hash in "
            " (select b.blob_hash from blob b "
            "  inner join stream_blob s2 on b.blob_hash=s2.blob_hash and s2.position=0 and s2.stream_hash=?)",
            (stream_hash, stream_hash)
        )

    def verify_will_announce_all_head_and_sd_blobs(self):
        return self.db.runOperation(
            "update blob set should_announce=1 "
            "where should_announce=0 and "
            "blob.blob_hash in "
            "  (select b.blob_hash from blob b inner join stream s on b.blob_hash=s.sd_hash) "
            "or blob.blob_hash in "
            " (select b.blob_hash from blob b "
            "  inner join stream_blob s2 on b.blob_hash=s2.blob_hash and s2.position=0)"
        )

    # # # # # # # # # stream functions # # # # # # # # #

    def store_stream(self, stream_hash, sd_hash, stream_name, stream_key, suggested_file_name,
                     stream_blob_infos):
        """
        Add a stream to the stream table

        :param stream_hash: hash of the assembled stream
        :param sd_hash: hash of the sd blob
        :param stream_key: blob decryption key
        :param stream_name: the name of the file the stream was generated from
        :param suggested_file_name: (str) suggested file name for stream
        :param stream_blob_infos: (list) of blob info dictionaries
        :return: (defer.Deferred)
        """

        def _store_stream(transaction):
            transaction.execute("insert into stream values (?, ?, ?, ?, ?);",
                                 (stream_hash, sd_hash, stream_key, stream_name,
                                  suggested_file_name))

            for blob_info in stream_blob_infos:
                transaction.execute("insert into stream_blob values (?, ?, ?, ?)",
                                    (stream_hash, blob_info.get('blob_hash', None),
                                     blob_info['blob_num'], blob_info['iv']))

        return self.db.runInteraction(_store_stream)

    @defer.inlineCallbacks
    def delete_stream(self, stream_hash):
        sd_hash = yield self.get_sd_blob_hash_for_stream(stream_hash)
        stream_blobs = yield self.get_blobs_for_stream(stream_hash)
        blob_hashes = [b.blob_hash for b in stream_blobs if b.blob_hash is not None]

        def _delete_stream(transaction):
            transaction.execute("delete from content_claim where stream_hash=? ", (stream_hash,))
            transaction.execute("delete from file where stream_hash=? ", (stream_hash, ))
            transaction.execute("delete from stream_blob where stream_hash=?", (stream_hash, ))
            transaction.execute("delete from stream where stream_hash=? ", (stream_hash, ))
            transaction.execute("delete from blob where blob_hash=?", (sd_hash, ))
            for blob_hash in blob_hashes:
                transaction.execute("delete from blob where blob_hash=?;", (blob_hash, ))
        yield self.db.runInteraction(_delete_stream)

    def get_all_streams(self):
        return self.run_and_return_list("select stream_hash from stream")

    def get_stream_info(self, stream_hash):
        d = self.db.runQuery("select stream_name, stream_key, suggested_filename, sd_hash from stream "
                             "where stream_hash=?", (stream_hash, ))
        d.addCallback(lambda r: None if not r else r[0])
        return d

    def check_if_stream_exists(self, stream_hash):
        d = self.db.runQuery("select stream_hash from stream where stream_hash=?", (stream_hash, ))
        d.addCallback(lambda r: True if len(r) else False)
        return d

    def get_blob_num_by_hash(self, stream_hash, blob_hash):
        return self.run_and_return_one_or_none(
            "select position from stream_blob where stream_hash=? and blob_hash=?",
            stream_hash, blob_hash
        )

    def get_stream_blob_by_position(self, stream_hash, blob_num):
        return self.run_and_return_one_or_none(
            "select blob_hash from stream_blob where stream_hash=? and position=?",
            stream_hash, blob_num
        )

    def get_blobs_for_stream(self, stream_hash, only_completed=False):
        def _get_blobs_for_stream(transaction):
            crypt_blob_infos = []
            stream_blobs = transaction.execute(
                "select blob_hash, position, iv from stream_blob where stream_hash=?", (stream_hash, )
            ).fetchall()
            if only_completed:
                lengths = transaction.execute(
                    "select b.blob_hash, b.blob_length from blob b "
                    "inner join stream_blob s ON b.blob_hash=s.blob_hash and b.status='finished' and s.stream_hash=?",
                    (stream_hash, )
                ).fetchall()
            else:
                lengths = transaction.execute(
                    "select b.blob_hash, b.blob_length from blob b "
                    "inner join stream_blob s ON b.blob_hash=s.blob_hash and s.stream_hash=?",
                    (stream_hash, )
                ).fetchall()

            blob_length_dict = {}
            for blob_hash, length in lengths:
                blob_length_dict[blob_hash] = length

            for blob_hash, position, iv in stream_blobs:
                blob_length = blob_length_dict.get(blob_hash, 0)
                crypt_blob_infos.append(CryptBlobInfo(blob_hash, position, blob_length, iv))
            crypt_blob_infos = sorted(crypt_blob_infos, key=lambda info: info.blob_num)
            return crypt_blob_infos
        return self.db.runInteraction(_get_blobs_for_stream)

    def get_pending_blobs_for_stream(self, stream_hash):
        return self.run_and_return_list(
            "select s.blob_hash from stream_blob s "
            "inner join blob b on b.blob_hash=s.blob_hash and b.status='pending' "
            "where stream_hash=?",
            stream_hash
        )

    def get_stream_of_blob(self, blob_hash):
        return self.run_and_return_one_or_none(
            "select stream_hash from stream_blob where blob_hash=?", blob_hash
        )

    def get_sd_blob_hash_for_stream(self, stream_hash):
        return self.run_and_return_one_or_none(
            "select sd_hash from stream where stream_hash=?", stream_hash
        )

    def get_stream_hash_for_sd_hash(self, sd_blob_hash):
        return self.run_and_return_one_or_none(
            "select stream_hash from stream where sd_hash = ?", sd_blob_hash
        )

    # # # # # # # # # file stuff # # # # # # # # #

    @defer.inlineCallbacks
    def save_downloaded_file(self, stream_hash, file_name, download_directory, data_payment_rate):
        # touch the closest available file to the file name
        file_name = yield open_file_for_writing(download_directory.decode('hex'), file_name.decode('hex'))
        result = yield self.save_published_file(
            stream_hash, file_name.encode('hex'), download_directory, data_payment_rate
        )
        defer.returnValue(result)

    def save_published_file(self, stream_hash, file_name, download_directory, data_payment_rate, status="stopped"):
        return self.run_and_return_id(
            "insert into file values (?, ?, ?, ?, ?)",
            stream_hash, file_name, download_directory, data_payment_rate, status
        )

    def get_filename_for_rowid(self, rowid):
        return self.run_and_return_one_or_none("select file_name from file where rowid=?", rowid)

    def get_all_lbry_files(self):
        def _lbry_file_dict(rowid, stream_hash, file_name, download_dir, data_rate, status, _, sd_hash, stream_key,
                            stream_name, suggested_file_name):
            return {
                "row_id": rowid,
                "stream_hash": stream_hash,
                "file_name": file_name,
                "download_directory": download_dir,
                "blob_data_rate": data_rate,
                "status": status,
                "sd_hash": sd_hash,
                "key": stream_key,
                "stream_name": stream_name,
                "suggested_file_name": suggested_file_name
            }

        def _get_all_files(transaction):
            return [
                _lbry_file_dict(*file_info) for file_info in transaction.execute(
                    "select file.rowid, file.*, stream.* "
                    "from file inner join stream on file.stream_hash=stream.stream_hash"
                ).fetchall()
            ]

        d = self.db.runInteraction(_get_all_files)
        return d

    def change_file_status(self, rowid, new_status):
        d = self.db.runQuery("update file set status=? where rowid=?", (new_status, rowid))
        d.addCallback(lambda _: new_status)
        return d

    def get_lbry_file_status(self, rowid):
        return self.run_and_return_one_or_none(
            "select status from file where rowid = ?", rowid
        )

    def get_rowid_for_stream_hash(self, stream_hash):
        return self.run_and_return_one_or_none(
            "select rowid from file where stream_hash=?", stream_hash
        )

    # # # # # # # # # support functions # # # # # # # # #

    def save_supports(self, claim_id, supports):
        # TODO: add 'address' to support items returned for a claim from lbrycrdd and lbryum-server
        def _save_support(transaction):
            transaction.execute("delete from support where claim_id=?", (claim_id, ))
            for support in supports:
                transaction.execute(
                    "insert into support values (?, ?, ?, ?)",
                    ("%s:%i" % (support['txid'], support['nout']), claim_id, int(support['amount'] * COIN),
                     support.get('address', ""))
                )
        return self.db.runInteraction(_save_support)

    def get_supports(self, *claim_ids):
        def _format_support(outpoint, supported_id, amount, address):
            return {
                "txid": outpoint.split(":")[0],
                "nout": int(outpoint.split(":")[1]),
                "claim_id": supported_id,
                "amount": float(Decimal(amount) / Decimal(COIN)),
                "address": address,
            }

        def _get_supports(transaction):
            if len(claim_ids) == 1:
                bind = "=?"
            else:
                bind = "in ({})".format(','.join('?' for _ in range(len(claim_ids))))
            return [
                _format_support(*support_info)
                for support_info in transaction.execute(
                    "select * from support where claim_id {}".format(bind),
                    tuple(claim_ids)
                ).fetchall()
            ]

        return self.db.runInteraction(_get_supports)

    # # # # # # # # # claim functions # # # # # # # # #

    @defer.inlineCallbacks
    def save_claims(self, claim_infos):
        def _save_claims(transaction):
            content_claims_to_update = []
            support_callbacks = []
            for claim_info in claim_infos:
                outpoint = "%s:%i" % (claim_info['txid'], claim_info['nout'])
                claim_id = claim_info['claim_id']
                name = claim_info['name']
                amount = int(COIN * claim_info['amount'])
                height = claim_info['height']
                address = claim_info['address']
                sequence = claim_info['claim_sequence']
                try:
                    certificate_id = claim_info['value'].get('content_claims_to_update', {}).get('certificateId')
                except AttributeError:
                    certificate_id = None
                try:
                    if claim_info['value'].get('stream', {}).get('source', {}).get('sourceType') == "lbry_sd_hash":
                        source_hash = claim_info['value'].get('stream', {}).get('source', {}).get('source')
                    else:
                        source_hash = None
                except AttributeError:
                    source_hash = None
                serialized = claim_info.get('hex') or smart_decode(claim_info['value']).serialized.encode('hex')
                transaction.execute(
                    "insert or replace into claim values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (outpoint, claim_id, name, amount, height, serialized, certificate_id, address, sequence)
                )
                if 'supports' in claim_info:  # if this response doesn't have support info don't overwrite the existing
                                              # support info
                    support_callbacks.append(self.save_supports(claim_id, claim_info['supports']))
                if not source_hash:
                    continue
                stream_hash = transaction.execute(
                    "select file.stream_hash from stream "
                    "inner join file on file.stream_hash=stream.stream_hash where sd_hash=?", (source_hash, )
                ).fetchone()
                if not stream_hash:
                    continue
                stream_hash = stream_hash[0]
                known_outpoint = transaction.execute(
                    "select claim_outpoint from content_claim where stream_hash=?", (stream_hash, )
                )
                known_claim_id = transaction.execute(
                    "select claim_id from claim "
                    "inner join content_claim c3 ON claim.claim_outpoint=c3.claim_outpoint "
                    "where c3.stream_hash=?", (stream_hash, )
                )
                if not known_claim_id:
                    content_claims_to_update.append((stream_hash, outpoint))
                elif known_outpoint != outpoint:
                    content_claims_to_update.append((stream_hash, outpoint))
            update_file_callbacks = []
            for stream_hash, outpoint in content_claims_to_update:
                self._save_content_claim(transaction, outpoint, stream_hash)
                if stream_hash in self.content_claim_callbacks:
                    update_file_callbacks.append(self.content_claim_callbacks[stream_hash]())
            return update_file_callbacks, support_callbacks

        content_dl, support_dl = yield self.db.runInteraction(_save_claims)
        if content_dl:
            yield defer.DeferredList(content_dl)
        if support_dl:
            yield defer.DeferredList(support_dl)

    def get_old_stream_hashes_for_claim_id(self, claim_id, new_stream_hash):
        return self.run_and_return_list(
            "select f.stream_hash from file f "
            "inner join content_claim cc on f.stream_hash=cc.stream_hash "
            "inner join claim c on c.claim_outpoint=cc.claim_outpoint and c.claim_id=? "
            "where f.stream_hash!=?", claim_id, new_stream_hash
        )

    @staticmethod
    def _save_content_claim(transaction, claim_outpoint, stream_hash):
        # get the claim id and serialized metadata
        claim_info = transaction.execute(
            "select claim_id, serialized_metadata from claim where claim_outpoint=?", (claim_outpoint,)
        ).fetchone()
        if not claim_info:
            raise Exception("claim not found")
        new_claim_id, claim = claim_info[0], ClaimDict.deserialize(claim_info[1].decode('hex'))

        # certificate claims should not be in the content_claim table
        if not claim.is_stream:
            raise Exception("claim does not contain a stream")

        # get the known sd hash for this stream
        known_sd_hash = transaction.execute(
            "select sd_hash from stream where stream_hash=?", (stream_hash,)
        ).fetchone()
        if not known_sd_hash:
            raise Exception("stream not found")
        # check the claim contains the same sd hash
        if known_sd_hash[0] != claim.source_hash:
            raise Exception("stream mismatch")

        # if there is a current claim associated to the file, check that the new claim is an update to it
        current_associated_content = transaction.execute(
            "select claim_outpoint from content_claim where stream_hash=?", (stream_hash,)
        ).fetchone()
        if current_associated_content:
            current_associated_claim_id = transaction.execute(
                "select claim_id from claim where claim_outpoint=?", current_associated_content
            ).fetchone()[0]
            if current_associated_claim_id != new_claim_id:
                raise Exception("invalid stream update")

        # update the claim associated to the file
        transaction.execute("insert or replace into content_claim values (?, ?)", (stream_hash, claim_outpoint))

    @defer.inlineCallbacks
    def save_content_claim(self, stream_hash, claim_outpoint):
        yield self.db.runInteraction(self._save_content_claim, claim_outpoint, stream_hash)
        # update corresponding ManagedEncryptedFileDownloader object
        if stream_hash in self.content_claim_callbacks:
            file_callback = self.content_claim_callbacks[stream_hash]
            yield file_callback()

    @defer.inlineCallbacks
    def get_content_claim(self, stream_hash, include_supports=True):
        def _get_claim_from_stream_hash(transaction):
            claim_info = transaction.execute(
                "select c.*, "
                "case when c.channel_claim_id is not null then "
                "(select claim_name from claim where claim_id==c.channel_claim_id) "
                "else null end as channel_name from content_claim "
                "inner join claim c on c.claim_outpoint=content_claim.claim_outpoint "
                "and content_claim.stream_hash=? order by c.rowid desc", (stream_hash,)
            ).fetchone()
            if not claim_info:
                return None
            channel_name = claim_info[-1]
            result = _format_claim_response(*claim_info[:-1])
            if channel_name:
                result['channel_name'] = channel_name
            return result

        result = yield self.db.runInteraction(_get_claim_from_stream_hash)
        if result and include_supports:
            supports = yield self.get_supports(result['claim_id'])
            result['supports'] = supports
            result['effective_amount'] = float(
                sum([support['amount'] for support in supports]) + result['amount']
            )
        defer.returnValue(result)

    @defer.inlineCallbacks
    def get_claims_from_stream_hashes(self, stream_hashes, include_supports=True):
        def _batch_get_claim(transaction):
            results = {}
            bind = "({})".format(','.join('?' for _ in range(len(stream_hashes))))
            claim_infos = transaction.execute(
                "select content_claim.stream_hash, c.*, "
                "case when c.channel_claim_id is not null then "
                "(select claim_name from claim where claim_id==c.channel_claim_id) "
                "else null end as channel_name from content_claim "
                "inner join claim c on c.claim_outpoint=content_claim.claim_outpoint "
                "and content_claim.stream_hash in {} order by c.rowid desc".format(bind),
                tuple(stream_hashes)
            ).fetchall()
            for claim_info in claim_infos:
                channel_name = claim_info[-1]
                stream_hash = claim_info[0]
                result = _format_claim_response(*claim_info[1:-1])
                if channel_name:
                    result['channel_name'] = channel_name
                results[stream_hash] = result
            return results

        claims = yield self.db.runInteraction(_batch_get_claim)
        if include_supports:
            all_supports = {}
            for support in (yield self.get_supports(*[claim['claim_id'] for claim in claims.values()])):
                all_supports.setdefault(support['claim_id'], []).append(support)
            for stream_hash in claims.keys():
                claim = claims[stream_hash]
                supports = all_supports.get(claim['claim_id'], [])
                claim['supports'] = supports
                claim['effective_amount'] = float(
                    sum([support['amount'] for support in supports]) + claim['amount']
                )
                claims[stream_hash] = claim
        defer.returnValue(claims)

    @defer.inlineCallbacks
    def get_claim(self, claim_outpoint, include_supports=True):
        def _get_claim(transaction):
            claim_info = transaction.execute("select c.*, "
                                             "case when c.channel_claim_id is not null then "
                                             "(select claim_name from claim where claim_id==c.channel_claim_id) "
                                             "else null end as channel_name from claim c where claim_outpoint = ?",
                                             (claim_outpoint,)).fetchone()
            channel_name = claim_info[-1]
            result = _format_claim_response(*claim_info[:-1])
            if channel_name:
                result['channel_name'] = channel_name
            return result

        result = yield self.db.runInteraction(_get_claim)
        if include_supports:
            supports = yield self.get_supports(result['claim_id'])
            result['supports'] = supports
            result['effective_amount'] = float(
                sum([support['amount'] for support in supports]) + result['amount']
            )
        defer.returnValue(result)

    def get_unknown_certificate_ids(self):
        def _get_unknown_certificate_claim_ids(transaction):
            return [
                claim_id for (claim_id,) in transaction.execute(
                    "select distinct c1.channel_claim_id from claim as c1 "
                    "where c1.channel_claim_id!='' "
                    "and c1.channel_claim_id not in "
                    "(select c2.claim_id from claim as c2)"
                ).fetchall()
            ]
        return self.db.runInteraction(_get_unknown_certificate_claim_ids)

    @defer.inlineCallbacks
    def get_pending_claim_outpoints(self):
        claim_outpoints = yield self.run_and_return_list("select claim_outpoint from claim where height=-1")
        results = {}  # {txid: [nout, ...]}
        for outpoint_str in claim_outpoints:
            txid, nout = outpoint_str.split(":")
            outputs = results.get(txid, [])
            outputs.append(int(nout))
            results[txid] = outputs
        if results:
            log.debug("missing transaction heights for %i claims", len(results))
        defer.returnValue(results)

    def save_claim_tx_heights(self, claim_tx_heights):
        def _save_claim_heights(transaction):
            for outpoint, height in claim_tx_heights.iteritems():
                transaction.execute(
                    "update claim set height=? where claim_outpoint=? and height=-1",
                    (height, outpoint)
                )
        return self.db.runInteraction(_save_claim_heights)

    # # # # # # # # # reflector functions # # # # # # # # #

    def update_reflected_stream(self, sd_hash, reflector_address, success=True):
        if success:
            return self.db.runOperation(
                "insert or replace into reflected_stream values (?, ?, ?)",
                (sd_hash, reflector_address, self.clock.seconds())
            )
        return self.db.runOperation(
            "delete from reflected_stream where sd_hash=? and reflector_address=?",
            (sd_hash, reflector_address)
        )

    def get_streams_to_re_reflect(self):
        return self.run_and_return_list(
            "select s.sd_hash from stream s "
            "left outer join reflected_stream r on s.sd_hash=r.sd_hash "
            "where r.timestamp is null or r.timestamp < ?",
            self.clock.seconds() - conf.settings['auto_re_reflect_interval']
        )


# Helper functions
def _format_claim_response(outpoint, claim_id, name, amount, height, serialized, channel_id, address, claim_sequence):
    r = {
        "name": name,
        "claim_id": claim_id,
        "address": address,
        "claim_sequence": claim_sequence,
        "value": ClaimDict.deserialize(serialized.decode('hex')).claim_dict,
        "height": height,
        "amount": float(Decimal(amount) / Decimal(COIN)),
        "nout": int(outpoint.split(":")[1]),
        "txid": outpoint.split(":")[0],
        "channel_claim_id": channel_id,
        "channel_name": None
    }
    return r
