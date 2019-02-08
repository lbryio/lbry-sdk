import logging
import sqlite3
import typing
import asyncio
import binascii
import time
from torba.client.basedatabase import SQLiteMixin
from lbrynet.conf import Config
from lbrynet.extras.wallet.dewies import dewies_to_lbc, lbc_to_dewies
from lbrynet.schema.claim import ClaimDict
from lbrynet.schema.decode import smart_decode
from lbrynet.dht.constants import data_expiration
from lbrynet.blob.blob_info import BlobInfo

if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_file import BlobFile
    from lbrynet.stream.descriptor import StreamDescriptor

log = logging.getLogger(__name__)
opt_str = typing.Optional[str]
opt_int = typing.Optional[int]


def calculate_effective_amount(amount: str, supports: typing.Optional[typing.List[typing.Dict]] = None) -> str:
    return dewies_to_lbc(
        lbc_to_dewies(amount) + sum([lbc_to_dewies(support['amount']) for support in supports])
    )


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


def get_claims_from_stream_hashes(transaction: sqlite3.Connection,
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


def get_content_claim_from_outpoint(transaction: sqlite3.Connection,
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


def _batched_select(transaction, query, parameters):
    for start_index in range(0, len(parameters), 900):
        current_batch = parameters[start_index:start_index+900]
        bind = "({})".format(','.join(['?'] * len(current_batch)))
        for result in transaction.execute(query.format(bind), current_batch):
            yield result


def get_all_lbry_files(transaction: sqlite3.Connection) -> typing.List[typing.Dict]:
    return [
        {
            "row_id": rowid,
            "stream_hash": stream_hash,
            "file_name": file_name,                      # hex
            "download_directory": download_dir,          # hex
            "blob_data_rate": data_rate,
            "status": status,
            "sd_hash": sd_hash,
            "key": stream_key,
            "stream_name": stream_name,                  # hex
            "suggested_file_name": suggested_file_name,  # hex
            "claim": StoredStreamClaim(stream_hash, *claim_args)
        } for (rowid, stream_hash, file_name, download_dir, data_rate, status, _, sd_hash, stream_key,
               stream_name, suggested_file_name, *claim_args) in _batched_select(
            transaction, "select file.rowid, file.*, stream.*, c.*, case when c.channel_claim_id is not null "
                         "  then (select claim_name from claim where claim_id==c.channel_claim_id) "
                         "  else null end as channel_name "
                         "from file inner join stream on file.stream_hash=stream.stream_hash "
                         "inner join content_claim cc on file.stream_hash=cc.stream_hash "
                         "inner join claim c on cc.claim_outpoint=c.claim_outpoint "
                         "where file.stream_hash in {} "
                         "order by c.rowid desc",
            [
                stream_hash
                for (stream_hash,) in transaction.execute("select stream_hash from file")
            ]
        )
    ]





class SQLiteStorage(SQLiteMixin):
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

    def __init__(self, conf: Config, path, loop=None, time_getter: typing.Optional[typing.Callable[[], float]] = None):
        super().__init__(path)
        self.conf = conf
        self.content_claim_callbacks = {}
        self.loop = loop or asyncio.get_event_loop()
        self.time_getter = time_getter or time.time

    async def run_and_return_one_or_none(self, query, *args):
        for row in await self.db.execute_fetchall(query, args):
            if len(row) == 1:
                return row[0]
            return row

    async def run_and_return_list(self, query, *args):
        rows = list(await self.db.execute_fetchall(query, args))
        return [col[0] for col in rows] if rows else []

    # # # # # # # # # blob functions # # # # # # # # #

    def add_completed_blob(self, blob_hash: str):
        log.debug("Adding a completed blob. blob_hash=%s", blob_hash)
        return self.db.execute("update blob set status='finished' where blob.blob_hash=?", (blob_hash, ))

    def get_blob_status(self, blob_hash: str):
        return self.run_and_return_one_or_none(
            "select status from blob where blob_hash=?", blob_hash
        )

    def add_known_blob(self, blob_hash: str, length: int):
        return self.db.execute(
            "insert or ignore into blob values (?, ?, ?, ?, ?, ?, ?)", (blob_hash, length, 0, 0, "pending", 0, 0)
        )

    def should_announce(self, blob_hash: str):
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

    def get_all_finished_blobs(self):
        return self.run_and_return_list(
            "select blob_hash from blob where status='finished'"
        )

    def count_finished_blobs(self):
        return self.run_and_return_one_or_none(
            "select count(*) from blob where status='finished'"
        )

    def update_last_announced_blobs(self, blob_hashes: typing.List[str]):
        def _update_last_announced_blobs(transaction: sqlite3.Connection):
            last_announced = self.time_getter()
            return transaction.executemany(
                "update blob set next_announce_time=?, last_announced_time=?, single_announce=0 "
                "where blob_hash=?",
                [(int(last_announced + (data_expiration / 2)), int(last_announced), blob_hash)
                 for blob_hash in blob_hashes]
            )
        return self.db.run(_update_last_announced_blobs)

    def should_single_announce_blobs(self, blob_hashes, immediate=False):
        def set_single_announce(transaction):
            now = int(self.time_getter())
            for blob_hash in blob_hashes:
                if immediate:
                    transaction.execute(
                        "update blob set single_announce=1, next_announce_time=? "
                        "where blob_hash=? and status='finished'", (int(now), blob_hash)
                    )
                else:
                    transaction.execute(
                        "update blob set single_announce=1 where blob_hash=? and status='finished'", (blob_hash,)
                    )
        return self.db.run(set_single_announce)

    def get_blobs_to_announce(self):
        def get_and_update(transaction):
            timestamp = int(self.time_getter())
            if self.conf.announce_head_and_sd_only:
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
        return self.db.run(get_and_update)

    def delete_blobs_from_db(self, blob_hashes):
        def delete_blobs(transaction):
            transaction.executemany(
                "delete from blob where blob_hash=?;", [(blob_hash,) for blob_hash in blob_hashes]
            )
        return self.db.run(delete_blobs)

    def get_all_blob_hashes(self):
        return self.run_and_return_list("select blob_hash from blob")

    # # # # # # # # # stream functions # # # # # # # # #

    async def stream_exists(self, sd_hash: str) -> bool:
        streams = await self.run_and_return_one_or_none("select stream_hash from stream where sd_hash=?", sd_hash)
        return streams is not None

    async def file_exists(self, sd_hash: str) -> bool:
        streams = await self.run_and_return_one_or_none("select f.stream_hash from file f "
                                                        "inner join stream s on "
                                                        "s.stream_hash=f.stream_hash and s.sd_hash=?", sd_hash)
        return streams is not None

    def store_stream(self, sd_blob: 'BlobFile', descriptor: 'StreamDescriptor'):
        def _store_stream(transaction: sqlite3.Connection):
            # add the head blob and set it to be announced
            transaction.execute(
                "insert or ignore into blob values (?, ?, ?, ?, ?, ?, ?),  (?, ?, ?, ?, ?, ?, ?)",
                (
                    sd_blob.blob_hash, sd_blob.length, 0, 1, "pending", 0, 0,
                    descriptor.blobs[0].blob_hash, descriptor.blobs[0].length, 0, 1, "pending", 0, 0
                )
            )
            # add the rest of the blobs with announcement off
            if len(descriptor.blobs) > 2:
                transaction.executemany(
                    "insert or ignore into blob values (?, ?, ?, ?, ?, ?, ?)",
                    [(blob.blob_hash, blob.length, 0, 0, "pending", 0, 0)
                     for blob in descriptor.blobs[1:-1]]
                )
            # associate the blobs to the stream
            transaction.execute("insert or ignore into stream values (?, ?, ?, ?, ?)",
                                (descriptor.stream_hash, sd_blob.blob_hash, descriptor.key,
                                 binascii.hexlify(descriptor.stream_name.encode()).decode(),
                                 binascii.hexlify(descriptor.suggested_file_name.encode()).decode()))
            # add the stream
            transaction.executemany(
                "insert or ignore into stream_blob values (?, ?, ?, ?)",
                [(descriptor.stream_hash, blob.blob_hash, blob.blob_num, blob.iv)
                 for blob in descriptor.blobs]
            )

        return self.db.run(_store_stream)

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
        return self.db.run(_get_blobs_for_stream)

    def get_sd_blob_hash_for_stream(self, stream_hash):
        return self.run_and_return_one_or_none(
            "select sd_hash from stream where stream_hash=?", stream_hash
        )

    def get_stream_hash_for_sd_hash(self, sd_blob_hash):
        return self.run_and_return_one_or_none(
            "select stream_hash from stream where sd_hash = ?", sd_blob_hash
        )

    def delete_stream(self, descriptor: 'StreamDescriptor'):
        def _delete_stream(transaction: sqlite3.Connection):
            transaction.execute("delete from content_claim where stream_hash=? ", (descriptor.stream_hash,))
            transaction.execute("delete from file where stream_hash=? ", (descriptor.stream_hash, ))
            transaction.execute("delete from stream_blob where stream_hash=?", (descriptor.stream_hash, ))
            transaction.execute("delete from stream where stream_hash=? ", (descriptor.stream_hash, ))
            transaction.execute("delete from blob where blob_hash=?", (descriptor.sd_hash, ))
            transaction.executemany("delete from blob where blob_hash=?",
                                    [(blob.blob_hash, ) for blob in descriptor.blobs[:-1]])
        return self.db.run(_delete_stream)

    # # # # # # # # # file stuff # # # # # # # # #

    def save_downloaded_file(self, stream_hash, file_name, download_directory, data_payment_rate):
        return self.save_published_file(
            stream_hash, file_name, download_directory, data_payment_rate, status="running"
        )

    def save_published_file(self, stream_hash: str, file_name: str, download_directory: str, data_payment_rate: float,
                            status="finished"):
        return self.db.execute(
            "insert into file values (?, ?, ?, ?, ?)",
            (stream_hash, binascii.hexlify(file_name.encode()).decode(),
             binascii.hexlify(download_directory.encode()).decode(), data_payment_rate, status)
        )

    def get_all_lbry_files(self) -> typing.List[typing.Dict]:
        return self.db.run(get_all_lbry_files)

    def change_file_status(self, stream_hash: str, new_status: str):
        log.info("update file status %s -> %s", stream_hash, new_status)
        return self.db.execute("update file set status=? where stream_hash=?", (new_status, stream_hash))

    def change_file_download_dir_and_file_name(self, stream_hash: str, download_dir: str, file_name: str):
        return self.db.execute("update file set download_directory=?, file_name=? where stream_hash=?", (
            binascii.hexlify(download_dir.encode()).decode(), binascii.hexlify(file_name.encode()).decode(),
            stream_hash
        ))

    def get_all_stream_hashes(self):
        return self.run_and_return_list("select stream_hash from stream")

    # # # # # # # # # support functions # # # # # # # # #

    def save_supports(self, claim_id, supports):
        # TODO: add 'address' to support items returned for a claim from lbrycrdd and lbryum-server
        def _save_support(transaction):
            transaction.execute("delete from support where claim_id=?", (claim_id,))
            for support in supports:
                transaction.execute(
                    "insert into support values (?, ?, ?, ?)",
                    ("%s:%i" % (support['txid'], support['nout']), claim_id, lbc_to_dewies(support['amount']),
                     support.get('address', ""))
                )
        return self.db.run(_save_support)

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

        return self.db.run(_get_supports)

    # # # # # # # # # claim functions # # # # # # # # #

    async def save_claims(self, claim_infos):
        support_callbacks = []
        update_file_callbacks = []

        def _save_claims(transaction):
            content_claims_to_update = []
            for claim_info in claim_infos:
                outpoint = "%s:%i" % (claim_info['txid'], claim_info['nout'])
                claim_id = claim_info['claim_id']
                name = claim_info['name']
                amount = lbc_to_dewies(claim_info['amount'])
                height = claim_info['height']
                address = claim_info['address']
                sequence = claim_info['claim_sequence']
                try:
                    certificate_id = claim_info['value'].get('publisherSignature', {}).get('certificateId')
                except AttributeError:
                    certificate_id = None
                try:
                    if claim_info['value'].get('stream', {}).get('source', {}).get('sourceType') == "lbry_sd_hash":
                        source_hash = claim_info['value'].get('stream', {}).get('source', {}).get('source')
                    else:
                        source_hash = None
                except AttributeError:
                    source_hash = None
                serialized = claim_info.get('hex') or binascii.hexlify(
                    smart_decode(claim_info['value']).serialized).decode()
                transaction.execute(
                    "insert or replace into claim values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (outpoint, claim_id, name, amount, height, serialized, certificate_id, address, sequence)
                )
                # if this response doesn't have support info don't overwrite the existing
                # support info
                if 'supports' in claim_info:
                    support_callbacks.append((claim_id, claim_info['supports']))
                if not source_hash:
                    continue
                stream_hash = transaction.execute(
                    "select file.stream_hash from stream "
                    "inner join file on file.stream_hash=stream.stream_hash where sd_hash=?", (source_hash,)
                ).fetchone()
                if not stream_hash:
                    continue
                stream_hash = stream_hash[0]
                known_outpoint = transaction.execute(
                    "select claim_outpoint from content_claim where stream_hash=?", (stream_hash,)
                )
                known_claim_id = transaction.execute(
                    "select claim_id from claim "
                    "inner join content_claim c3 ON claim.claim_outpoint=c3.claim_outpoint "
                    "where c3.stream_hash=?", (stream_hash,)
                )
                if not known_claim_id:
                    content_claims_to_update.append((stream_hash, outpoint))
                elif known_outpoint != outpoint:
                    content_claims_to_update.append((stream_hash, outpoint))
            for stream_hash, outpoint in content_claims_to_update:
                self._save_content_claim(transaction, outpoint, stream_hash)
                if stream_hash in self.content_claim_callbacks:
                    update_file_callbacks.append(self.content_claim_callbacks[stream_hash]())

        await self.db.run(_save_claims)
        if update_file_callbacks:
            await asyncio.wait(update_file_callbacks)
        if support_callbacks:
            await asyncio.wait([
                self.save_supports(*args) for args in support_callbacks
            ])

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

    @staticmethod
    def _save_content_claim(transaction, claim_outpoint, stream_hash):
        # get the claim id and serialized metadata
        claim_info = transaction.execute(
            "select claim_id, serialized_metadata from claim where claim_outpoint=?", (claim_outpoint,)
        ).fetchone()
        if not claim_info:
            raise Exception("claim not found")
        new_claim_id, claim = claim_info[0], ClaimDict.deserialize(binascii.unhexlify(claim_info[1]))

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

    async def save_content_claim(self, stream_hash, claim_outpoint):
        await self.db.run(self._save_content_claim, claim_outpoint, stream_hash)
        # update corresponding ManagedEncryptedFileDownloader object
        if stream_hash in self.content_claim_callbacks:
            await self.content_claim_callbacks[stream_hash]()

    async def get_content_claim(self, stream_hash: str, include_supports: typing.Optional[bool] = True) -> typing.Dict:
        claims = await self.db.run(get_claims_from_stream_hashes, [stream_hash])
        claim = None
        if claims:
            claim = claims[stream_hash].as_dict()
            if include_supports:
                supports = await self.get_supports(claim['claim_id'])
                claim['supports'] = supports
                claim['effective_amount'] = calculate_effective_amount(claim['amount'], supports)
        return claim

    async def get_claims_from_stream_hashes(self, stream_hashes: typing.List[str],
                                            include_supports: typing.Optional[bool] = True):
        claims = await self.db.run(get_claims_from_stream_hashes, stream_hashes)
        return {stream_hash: claim_info.as_dict() for stream_hash, claim_info in claims.items()}

    async def get_claim(self, claim_outpoint, include_supports=True):
        claim_info = await self.db.run(get_content_claim_from_outpoint, claim_outpoint)
        if not claim_info:
            return
        result = claim_info.as_dict()
        if include_supports:
            supports = await self.get_supports(result['claim_id'])
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
        return self.db.run(_get_unknown_certificate_claim_ids)

    async def get_pending_claim_outpoints(self):
        claim_outpoints = await self.run_and_return_list("select claim_outpoint from claim where height=-1")
        results = {}  # {txid: [nout, ...]}
        for outpoint_str in claim_outpoints:
            txid, nout = outpoint_str.split(":")
            outputs = results.get(txid, [])
            outputs.append(int(nout))
            results[txid] = outputs
        if results:
            log.debug("missing transaction heights for %i claims", len(results))
        return results

    def save_claim_tx_heights(self, claim_tx_heights):
        def _save_claim_heights(transaction):
            for outpoint, height in claim_tx_heights.items():
                transaction.execute(
                    "update claim set height=? where claim_outpoint=? and height=-1",
                    (height, outpoint)
                )
        return self.db.run(_save_claim_heights)

    # # # # # # # # # reflector functions # # # # # # # # #

    def update_reflected_stream(self, sd_hash, reflector_address, success=True):
        if success:
            return self.db.execute(
                "insert or replace into reflected_stream values (?, ?, ?)",
                (sd_hash, reflector_address, self.time_getter())
            )
        return self.db.execute(
            "delete from reflected_stream where sd_hash=? and reflector_address=?",
            (sd_hash, reflector_address)
        )

    def get_streams_to_re_reflect(self):
        return self.run_and_return_list(
            "select s.sd_hash from stream s "
            "left outer join reflected_stream r on s.sd_hash=r.sd_hash "
            "where r.timestamp is null or r.timestamp < ?",
            int(self.time_getter()) - 86400
        )
