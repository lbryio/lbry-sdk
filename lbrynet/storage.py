import logging
import os
import sqlite3
import traceback
import typing
from binascii import hexlify, unhexlify
from twisted.internet import defer, task, threads
from twisted.enterprise import adbapi

from lbrynet.extras.wallet.dewies import dewies_to_lbc, lbc_to_dewies
from lbrynet import conf
from lbrynet.schema.claim import ClaimDict
from lbrynet.schema.decode import smart_decode
from lbrynet.blob.blob_info import BlobInfo
from lbrynet.dht.constants import data_expiration

if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_file import BlobFile
    from lbrynet.stream.descriptor import StreamDescriptor

log = logging.getLogger(__name__)

opt_str = typing.Optional[str]
opt_int = typing.Optional[int]


class StoredStreamClaim:
    def __init__(self, stream_hash: str, outpoint: opt_str = None, claim_id: opt_str = None, name: opt_str = None,
                 amount: opt_int = None, height: opt_int = None, serialized: opt_str = None,
                 channel_claim_id: opt_str = None, address: opt_str = None, claim_sequence: opt_int = None,
                 channel_name: opt_str = None):
        self.stream_hash = stream_hash
        self.claim_id = claim_id
        self.outpoint = outpoint
        self.claim_name = name
        self.amount = amount
        self.height = height
        self.claim: typing.Optional[ClaimDict] = None if not serialized else smart_decode(serialized)
        self.claim_address = address
        self.claim_sequence = claim_sequence
        self.channel_claim_id = channel_claim_id
        self.channel_name = channel_name

    @property
    def txid(self) -> typing.Optional[str]:
        return None if not self.outpoint else self.outpoint.split(":")[0]

    @property
    def nout(self) -> typing.Optional[int]:
        return None if not self.outpoint else int(self.outpoint.split(":")[1])

    @property
    def metadata(self) -> typing.Optional[typing.Dict]:
        return None if not self.claim else self.claim.claim_dict['stream']['metadata']

    def as_dict(self) -> typing.Dict:
        return {
            "name": self.claim_name,
            "claim_id": self.claim_id,
            "address": self.claim_address,
            "claim_sequence": self.claim_sequence,
            "value": self.claim,
            "height": self.height,
            "amount": dewies_to_lbc(self.amount),
            "nout": self.nout,
            "txid": self.txid,
            "channel_claim_id": self.channel_claim_id,
            "channel_name": self.channel_name
        }


def get_claims_from_stream_hashes(transaction: adbapi.Transaction,
                                  stream_hashes: typing.List[str]) -> typing.Dict[str, StoredStreamClaim]:
    query = (
        "select content_claim.stream_hash, c.*, case when c.channel_claim_id is not null then "
        "   (select claim_name from claim where claim_id==c.channel_claim_id) "
        "   else null end as channel_name "
        " from content_claim "
        " inner join claim c on c.claim_outpoint=content_claim.claim_outpoint and content_claim.stream_hash in {}"
        " order by c.rowid desc"
    )
    return {
        claim_info.stream_hash: claim_info
        for claim_info in [
            None if not claim_info else StoredStreamClaim(*claim_info)
            for claim_info in _batched_select(transaction, query, stream_hashes)
        ]
    }


def get_content_claim_from_outpoint(transaction: adbapi.Transaction,
                                    outpoint: str) -> typing.Optional[StoredStreamClaim]:
    query = (
        "select content_claim.stream_hash, c.*, case when c.channel_claim_id is not null then "
        "   (select claim_name from claim where claim_id==c.channel_claim_id) "
        "   else null end as channel_name "
        " from content_claim "
        " inner join claim c on c.claim_outpoint=content_claim.claim_outpoint and content_claim.claim_outpoint=?"
    )
    claim_fields = transaction.execute(query, (outpoint, )).fetchone()
    if claim_fields:
        return StoredStreamClaim(*claim_fields)


def calculate_effective_amount(amount: str, supports: typing.Optional[typing.List[typing.Dict]] = None) -> str:
    return dewies_to_lbc(
        lbc_to_dewies(amount) + sum([lbc_to_dewies(support['amount']) for support in supports])
    )


def rerun_if_locked(f):
    max_attempts = 5

    def rerun(err, rerun_count, *args, **kwargs):
        connection = args[0]
        reactor = connection.reactor
        log.debug("Failed to execute (%s): %s", err, args)
        if err.check(sqlite3.OperationalError) and "database is locked" in str(err.value):
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
        super().__init__('sqlite3', db_path, check_same_thread=False)

    @rerun_if_locked
    def runInteraction(self, interaction, *args, **kw):
        return super().runInteraction(interaction, *args, **kw)

    @classmethod
    def set_reactor(cls, reactor):
        cls.reactor = reactor


class SQLiteStorage:

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
    """

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
        self.check_should_announce_lc = None
        if conf.settings and 'reflector' not in conf.settings['components_to_skip']:
            self.check_should_announce_lc = task.LoopingCall(self.verify_will_announce_all_head_and_sd_blobs)

    @defer.inlineCallbacks
    def setup(self):
        def _create_tables(transaction):
            transaction.executescript(self.CREATE_TABLES_QUERY)
        yield self.db.runInteraction(_create_tables)
        # if self.check_should_announce_lc and not self.check_should_announce_lc.running:
        #     self.check_should_announce_lc.start(600)
        defer.returnValue(None)

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
        if self.check_should_announce_lc and self.check_should_announce_lc.running:
            self.check_should_announce_lc.stop()
        self.db.close()
        return defer.succeed(True)

    # # # # # # # # # blob functions # # # # # # # # #

    def add_completed_blob(self, blob_hash):
        return self.db.runOperation("update blob set status='finished' where blob.blob_hash=?", (blob_hash, ))

    def set_should_announce(self, blob_hash, next_announce_time, should_announce):
        return self.db.runOperation(
            "update blob set next_announce_time=?, should_announce=? where blob_hash=?",
            (next_announce_time or 0, int(bool(should_announce)), blob_hash)
        )

    def get_blob_status(self, blob_hash):
        return self.run_and_return_one_or_none(
            "select status from blob where blob_hash=?", blob_hash
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

    @defer.inlineCallbacks
    def get_all_finished_blobs(self):
        blob_hashes = yield self.run_and_return_list(
            "select blob_hash from blob where status='finished'"
        )
        defer.returnValue([unhexlify(blob_hash) for blob_hash in blob_hashes])

    def count_finished_blobs(self):
        return self.run_and_return_one_or_none(
            "select count(*) from blob where status='finished'"
        )

    def update_last_announced_blob(self, blob_hash, last_announced):
        return self.db.runOperation(
                    "update blob set next_announce_time=?, last_announced_time=?, single_announce=0 where blob_hash=?",
                    (int(last_announced + (data_expiration / 2)), int(last_announced), blob_hash)
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
            if conf.settings and conf.settings['announce_head_blobs_only']:
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

    def store_stream(self, sd_blob: 'BlobFile', descriptor: 'StreamDescriptor'):
        def _store_stream(transaction):
            transaction.execute("insert or ignore into blob values (?, ?, ?, ?, ?, ?, ?)",
                                (sd_blob.blob_hash, sd_blob.length, 0, 1, "pending", 0, 0))
            transaction.execute("insert or ignore into blob values (?, ?, ?, ?, ?, ?, ?)",
                                (descriptor.blobs[0].blob_hash, descriptor.blobs[0].length, 0, 1, "pending", 0, 0))
            for blob in descriptor.blobs[1:-1]:
                transaction.execute("insert or ignore into blob values (?, ?, ?, ?, ?, ?, ?)",
                                    (blob.blob_hash, blob.length, 0, 0, "pending", 0, 0))
            transaction.execute("insert or ignore into stream values (?, ?, ?, ?, ?);",
                                 (descriptor.stream_hash, sd_blob.blob_hash, descriptor.key,
                                  hexlify(descriptor.stream_name.encode()).decode(),
                                  hexlify(descriptor.suggested_file_name.encode()).decode()))
            for blob_info in descriptor.blobs:
                transaction.execute("insert or ignore into stream_blob values (?, ?, ?, ?)",
                                    (descriptor.stream_hash, blob_info.blob_hash,
                                     blob_info.blob_num, blob_info.iv))
        return self.db.runInteraction(_store_stream)

    @defer.inlineCallbacks
    def delete_stream(self, descriptor: 'StreamDescriptor'):
        def _delete_stream(transaction):
            transaction.execute("delete from content_claim where stream_hash=? ", (descriptor.stream_hash,))
            transaction.execute("delete from file where stream_hash=? ", (descriptor.stream_hash, ))
            transaction.execute("delete from stream_blob where stream_hash=?", (descriptor.stream_hash, ))
            transaction.execute("delete from stream where stream_hash=? ", (descriptor.stream_hash, ))
            transaction.execute("delete from blob where blob_hash=?", ( descriptor.sd_hash, ))
            for blob_hash in [b.blob_hash for b in descriptor.blobs[:-1]]:
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
        d.addCallback(lambda r: bool(len(r)))
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
                crypt_blob_infos.append(BlobInfo(position, blob_length, iv, blob_hash))
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
        result = yield self.save_published_file(
            stream_hash, hexlify(file_name.encode()), hexlify(download_directory.encode()).decode(), data_payment_rate,
            status="running"
        )
        defer.returnValue(result)

    def save_published_file(self, stream_hash, file_name, download_directory, data_payment_rate, status="stopped"):
        return self.run_and_return_id(
            "insert into file values (?, ?, ?, ?, ?)",
            stream_hash, file_name, download_directory, data_payment_rate, status
        )

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
            file_infos = [
                _lbry_file_dict(*file_info) for file_info in transaction.execute(
                    "select file.rowid, file.*, stream.* "
                    "from file inner join stream on file.stream_hash=stream.stream_hash"
                ).fetchall()
            ]
            stream_hashes = [file_info['stream_hash'] for file_info in file_infos]
            claim_infos = get_claims_from_stream_hashes(transaction, stream_hashes)
            for file_info in file_infos:
                file_info['claim'] = claim_infos[file_info['stream_hash']]
            return file_infos

        d = self.db.runInteraction(_get_all_files)
        return d

    def change_file_status(self, stream_hash: str, new_status: str):
        log.info("update file status %s -> %s", stream_hash, new_status)
        d = self.db.runQuery("update file set status=? where stream_hash=?", (new_status, stream_hash))
        d.addCallback(lambda _: new_status)
        return d

    # # # # # # # # # support functions # # # # # # # # #

    def save_supports(self, claim_id, supports):
        # TODO: add 'address' to support items returned for a claim from lbrycrdd and lbryum-server
        def _save_support(transaction):
            transaction.execute("delete from support where claim_id=?", (claim_id, ))
            for support in supports:
                transaction.execute(
                    "insert into support values (?, ?, ?, ?)",
                    ("%s:%i" % (support['txid'], support['nout']), claim_id, lbc_to_dewies(support['amount']),
                     support.get('address', ""))
                )
        return self.db.runInteraction(_save_support)

    def get_supports(self, *claim_ids):
        def _format_support(outpoint, supported_id, amount, address):
            return {
                "txid": outpoint.split(":")[0],
                "nout": int(outpoint.split(":")[1]),
                "claim_id": supported_id,
                "amount": dewies_to_lbc(amount),
                "address": address,
            }

        def _get_supports(transaction):
            return [
                _format_support(*support_info)
                for support_info in _batched_select(
                    transaction,
                    "select * from support where claim_id in {}",
                    tuple(claim_ids)
                )
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
                amount = lbc_to_dewies(claim_info['amount'])
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
                serialized = claim_info.get('hex') or hexlify(smart_decode(claim_info['value']).serialized)
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

    def save_claims_for_resolve(self, claim_infos):
        to_save = []
        for info in claim_infos:
            if 'value' in info:
                if info['value']:
                    to_save.append(info)
            else:
                if 'certificate' in info and info['certificate']['value']:
                    to_save.append(info['certificate'])
                if 'claim' in info and info['claim']['value']:
                    to_save.append(info['claim'])
        return self.save_claims(to_save)

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
        new_claim_id, claim = claim_info[0], ClaimDict.deserialize(unhexlify(claim_info[1]))

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
        if known_sd_hash[0].encode() != claim.source_hash:
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
                raise Exception(
                    f"mismatching claim ids when updating stream {current_associated_claim_id} vs {new_claim_id}"
                )

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
    def get_content_claim(self, stream_hash: str, include_supports: typing.Optional[bool] = True) -> typing.Dict:
        claims = yield self.db.runInteraction(get_claims_from_stream_hashes, [stream_hash])
        claim = None
        if claims:
            claim = claims[stream_hash].as_dict()
            if include_supports:
                supports = yield self.get_supports(claim['claim_id'])
                claim['supports'] = supports
                claim['effective_amount'] = calculate_effective_amount(claim['amount'], supports)
        defer.returnValue(claim)

    @defer.inlineCallbacks
    def get_claims_from_stream_hashes(self, stream_hashes: typing.List[str],
                                      include_supports: typing.Optional[bool] = True):
        claims = yield self.db.runInteraction(get_claims_from_stream_hashes, stream_hashes)
        return {stream_hash: claim_info.as_dict() for stream_hash, claim_info in claims.items()}

    @defer.inlineCallbacks
    def get_claim(self, claim_outpoint, include_supports=True):
        claim_info = yield self.db.runInteraction(get_content_claim_from_outpoint, claim_outpoint)
        if not claim_info:
            return
        result = claim_info.as_dict()
        if include_supports:
            supports = yield self.get_supports(result['claim_id'])
            result['supports'] = supports
            result['effective_amount'] = calculate_effective_amount(result['amount'], supports)
        return result

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
            for outpoint, height in claim_tx_heights.items():
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


def _batched_select(transaction, query, parameters):
    for start_index in range(0, len(parameters), 900):
        current_batch = parameters[start_index:start_index+900]
        bind = "({})".format(','.join(['?'] * len(current_batch)))
        for result in transaction.execute(query.format(bind), current_batch):
            yield result
