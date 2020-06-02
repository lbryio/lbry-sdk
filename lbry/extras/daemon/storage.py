import os
import logging
import sqlite3
import typing
import asyncio
import binascii
import time
from typing import Optional
from lbry.wallet import SQLiteMixin
from lbry.conf import Config
from lbry.wallet.dewies import dewies_to_lbc, lbc_to_dewies
from lbry.wallet.transaction import Transaction, Output
from lbry.schema.claim import Claim
from lbry.dht.constants import DATA_EXPIRATION
from lbry.blob.blob_info import BlobInfo

if typing.TYPE_CHECKING:
    from lbry.blob.blob_file import BlobFile
    from lbry.stream.descriptor import StreamDescriptor

log = logging.getLogger(__name__)


def calculate_effective_amount(amount: str, supports: typing.Optional[typing.List[typing.Dict]] = None) -> str:
    return dewies_to_lbc(
        lbc_to_dewies(amount) + sum([lbc_to_dewies(support['amount']) for support in supports])
    )


class StoredContentClaim:
    def __init__(self, outpoint: Optional[str] = None, claim_id: Optional[str] = None, name: Optional[str] = None,
                 amount: Optional[int] = None, height: Optional[int] = None, serialized: Optional[str] = None,
                 channel_claim_id: Optional[str] = None, address: Optional[str] = None,
                 claim_sequence: Optional[int] = None, channel_name: Optional[str] = None):
        self.claim_id = claim_id
        self.outpoint = outpoint
        self.claim_name = name
        self.amount = amount
        self.height = height
        self.claim: typing.Optional[Claim] = None if not serialized else Claim.from_bytes(
            binascii.unhexlify(serialized)
        )
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


def _get_content_claims(transaction: sqlite3.Connection, query: str,
                        source_hashes: typing.List[str]) -> typing.Dict[str, StoredContentClaim]:
    claims = {}
    for claim_info in _batched_select(transaction, query, source_hashes):
        claims[claim_info[0]] = StoredContentClaim(*claim_info[1:])
    return claims


def get_claims_from_stream_hashes(transaction: sqlite3.Connection,
                                  stream_hashes: typing.List[str]) -> typing.Dict[str, StoredContentClaim]:
    query = (
        "select content_claim.stream_hash, c.*, case when c.channel_claim_id is not null then "
        "   (select claim_name from claim where claim_id==c.channel_claim_id) "
        "   else null end as channel_name "
        " from content_claim "
        " inner join claim c on c.claim_outpoint=content_claim.claim_outpoint and content_claim.stream_hash in {}"
        " order by c.rowid desc"
    )
    return _get_content_claims(transaction, query, stream_hashes)


def get_claims_from_torrent_info_hashes(transaction: sqlite3.Connection,
                                        info_hashes: typing.List[str]) -> typing.Dict[str, StoredContentClaim]:
    query = (
        "select content_claim.bt_infohash, c.*, case when c.channel_claim_id is not null then "
        "   (select claim_name from claim where claim_id==c.channel_claim_id) "
        "   else null end as channel_name "
        " from content_claim "
        " inner join claim c on c.claim_outpoint=content_claim.claim_outpoint and content_claim.bt_infohash in {}"
        " order by c.rowid desc"
    )
    return _get_content_claims(transaction, query, info_hashes)


def _batched_select(transaction, query, parameters, batch_size=900):
    for start_index in range(0, len(parameters), batch_size):
        current_batch = parameters[start_index:start_index+batch_size]
        bind = "({})".format(','.join(['?'] * len(current_batch)))
        yield from transaction.execute(query.format(bind), current_batch)


def _get_lbry_file_stream_dict(rowid, added_on, stream_hash, file_name, download_dir, data_rate, status,
                               sd_hash, stream_key, stream_name, suggested_file_name, claim, saved_file,
                               raw_content_fee, fully_reflected):
    return {
        "rowid": rowid,
        "added_on": added_on,
        "stream_hash": stream_hash,
        "file_name": file_name,                      # hex
        "download_directory": download_dir,          # hex
        "blob_data_rate": data_rate,
        "status": status,
        "sd_hash": sd_hash,
        "key": stream_key,
        "stream_name": stream_name,                  # hex
        "suggested_file_name": suggested_file_name,  # hex
        "claim": claim,
        "saved_file": bool(saved_file),
        "content_fee": None if not raw_content_fee else Transaction(
            binascii.unhexlify(raw_content_fee)
        ),
        "fully_reflected": fully_reflected
    }


def get_all_lbry_files(transaction: sqlite3.Connection) -> typing.List[typing.Dict]:
    files = []
    signed_claims = {}
    for (rowid, stream_hash, _, file_name, download_dir, data_rate, status, saved_file, raw_content_fee,
         added_on, _, sd_hash, stream_key, stream_name, suggested_file_name, *claim_args) in transaction.execute(
             "select file.rowid, file.*, stream.*, c.*, "
             "  case when (SELECT 1 FROM reflected_stream r WHERE r.sd_hash=stream.sd_hash) "
             "      is null then 0 else 1 end as fully_reflected "
             "from file inner join stream on file.stream_hash=stream.stream_hash "
             "inner join content_claim cc on file.stream_hash=cc.stream_hash "
             "inner join claim c on cc.claim_outpoint=c.claim_outpoint "
             "order by c.rowid desc").fetchall():
        claim_args, fully_reflected = tuple(claim_args[:-1]), claim_args[-1]
        claim = StoredContentClaim(*claim_args)
        if claim.channel_claim_id:
            if claim.channel_claim_id not in signed_claims:
                signed_claims[claim.channel_claim_id] = []
            signed_claims[claim.channel_claim_id].append(claim)
        files.append(
            _get_lbry_file_stream_dict(
                rowid, added_on, stream_hash, file_name, download_dir, data_rate, status,
                sd_hash, stream_key, stream_name, suggested_file_name, claim, saved_file,
                raw_content_fee, fully_reflected
            )
        )
    for claim_name, claim_id in _batched_select(
            transaction, "select c.claim_name, c.claim_id from claim c where c.claim_id in {}",
            tuple(signed_claims.keys())):
        for claim in signed_claims[claim_id]:
            claim.channel_name = claim_name
    return files


def store_stream(transaction: sqlite3.Connection, sd_blob: 'BlobFile', descriptor: 'StreamDescriptor'):
    # add all blobs, except the last one, which is empty
    transaction.executemany(
        "insert or ignore into blob values (?, ?, ?, ?, ?, ?, ?)",
        ((blob.blob_hash, blob.length, 0, 0, "pending", 0, 0)
         for blob in (descriptor.blobs[:-1] if len(descriptor.blobs) > 1 else descriptor.blobs) + [sd_blob])
    ).fetchall()
    # associate the blobs to the stream
    transaction.execute("insert or ignore into stream values (?, ?, ?, ?, ?)",
                        (descriptor.stream_hash, sd_blob.blob_hash, descriptor.key,
                         binascii.hexlify(descriptor.stream_name.encode()).decode(),
                         binascii.hexlify(descriptor.suggested_file_name.encode()).decode())).fetchall()
    # add the stream
    transaction.executemany(
        "insert or ignore into stream_blob values (?, ?, ?, ?)",
        ((descriptor.stream_hash, blob.blob_hash, blob.blob_num, blob.iv)
         for blob in descriptor.blobs)
    ).fetchall()
    # ensure should_announce is set regardless if insert was ignored
    transaction.execute(
        "update blob set should_announce=1 where blob_hash in (?, ?)",
        (sd_blob.blob_hash, descriptor.blobs[0].blob_hash,)
    ).fetchall()


def delete_stream(transaction: sqlite3.Connection, descriptor: 'StreamDescriptor'):
    blob_hashes = [(blob.blob_hash, ) for blob in descriptor.blobs[:-1]]
    blob_hashes.append((descriptor.sd_hash, ))
    transaction.execute("delete from content_claim where stream_hash=? ", (descriptor.stream_hash,)).fetchall()
    transaction.execute("delete from file where stream_hash=? ", (descriptor.stream_hash,)).fetchall()
    transaction.execute("delete from stream_blob where stream_hash=?", (descriptor.stream_hash,)).fetchall()
    transaction.execute("delete from stream where stream_hash=? ", (descriptor.stream_hash,)).fetchall()
    transaction.executemany("delete from blob where blob_hash=?", blob_hashes).fetchall()


def delete_torrent(transaction: sqlite3.Connection, bt_infohash: str):
    transaction.execute("delete from content_claim where bt_infohash=?", (bt_infohash, )).fetchall()
    transaction.execute("delete from torrent_tracker where bt_infohash=?", (bt_infohash,)).fetchall()
    transaction.execute("delete from torrent_node where bt_infohash=?", (bt_infohash,)).fetchall()
    transaction.execute("delete from torrent_http_seed where bt_infohash=?", (bt_infohash,)).fetchall()
    transaction.execute("delete from file where bt_infohash=?", (bt_infohash,)).fetchall()
    transaction.execute("delete from torrent where bt_infohash=?", (bt_infohash,)).fetchall()


def store_file(transaction: sqlite3.Connection, stream_hash: str, file_name: typing.Optional[str],
               download_directory: typing.Optional[str], data_payment_rate: float, status: str,
               content_fee: typing.Optional[Transaction], added_on: typing.Optional[int] = None) -> int:
    if not file_name and not download_directory:
        encoded_file_name, encoded_download_dir = None, None
    else:
        encoded_file_name = binascii.hexlify(file_name.encode()).decode()
        encoded_download_dir = binascii.hexlify(download_directory.encode()).decode()
    time_added = added_on or int(time.time())
    transaction.execute(
        "insert or replace into file values (?, NULL, ?, ?, ?, ?, ?, ?, ?)",
        (stream_hash, encoded_file_name, encoded_download_dir, data_payment_rate, status,
         1 if (file_name and download_directory and os.path.isfile(os.path.join(download_directory, file_name))) else 0,
         None if not content_fee else binascii.hexlify(content_fee.raw).decode(), time_added)
    ).fetchall()

    return transaction.execute("select rowid from file where stream_hash=?", (stream_hash, )).fetchone()[0]


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

            create table if not exists torrent (
                bt_infohash char(20) not null primary key,
                tracker text,
                length integer not null,
                name text not null
            );

            create table if not exists torrent_node ( -- BEP-0005
                bt_infohash char(20) not null references torrent,
                host text not null,
                port integer not null
            );

            create table if not exists torrent_tracker ( -- BEP-0012
                bt_infohash char(20) not null references torrent,
                tracker text not null
            );

            create table if not exists torrent_http_seed ( -- BEP-0017
                bt_infohash char(20) not null references torrent,
                http_seed text not null
            );

            create table if not exists file (
                stream_hash char(96) references stream,
                bt_infohash char(20) references torrent,
                file_name text,
                download_directory text,
                blob_data_rate real not null,
                status text not null,
                saved_file integer not null,
                content_fee text,
                added_on integer not null
            );

            create table if not exists content_claim (
                stream_hash char(96) references stream,
                bt_infohash char(20) references torrent,
                claim_outpoint text unique not null references claim
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

            create table if not exists peer (
                node_id char(96) not null primary key,
                address text not null,
                udp_port integer not null,
                tcp_port integer,
                unique (address, udp_port)
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

    async def add_blobs(self, *blob_hashes_and_lengths: typing.Tuple[str, int], finished=False):
        def _add_blobs(transaction: sqlite3.Connection):
            transaction.executemany(
                "insert or ignore into blob values (?, ?, ?, ?, ?, ?, ?)",
                (
                    (blob_hash, length, 0, 0, "pending" if not finished else "finished", 0, 0)
                    for blob_hash, length in blob_hashes_and_lengths
                )
            ).fetchall()
            if finished:
                transaction.executemany(
                    "update blob set status='finished' where blob.blob_hash=?", (
                        (blob_hash, ) for blob_hash, _ in blob_hashes_and_lengths
                    )
                ).fetchall()
        return await self.db.run(_add_blobs)

    def get_blob_status(self, blob_hash: str):
        return self.run_and_return_one_or_none(
            "select status from blob where blob_hash=?", blob_hash
        )

    def update_last_announced_blobs(self, blob_hashes: typing.List[str]):
        def _update_last_announced_blobs(transaction: sqlite3.Connection):
            last_announced = self.time_getter()
            return transaction.executemany(
                "update blob set next_announce_time=?, last_announced_time=?, single_announce=0 "
                "where blob_hash=?",
                ((int(last_announced + (DATA_EXPIRATION / 2)), int(last_announced), blob_hash)
                 for blob_hash in blob_hashes)
            ).fetchall()
        return self.db.run(_update_last_announced_blobs)

    def should_single_announce_blobs(self, blob_hashes, immediate=False):
        def set_single_announce(transaction):
            now = int(self.time_getter())
            for blob_hash in blob_hashes:
                if immediate:
                    transaction.execute(
                        "update blob set single_announce=1, next_announce_time=? "
                        "where blob_hash=? and status='finished'", (int(now), blob_hash)
                    ).fetchall()
                else:
                    transaction.execute(
                        "update blob set single_announce=1 where blob_hash=? and status='finished'", (blob_hash,)
                    ).fetchall()
        return self.db.run(set_single_announce)

    def get_blobs_to_announce(self):
        def get_and_update(transaction):
            timestamp = int(self.time_getter())
            if self.conf.announce_head_and_sd_only:
                r = transaction.execute(
                    "select blob_hash from blob "
                    "where blob_hash is not null and "
                    "(should_announce=1 or single_announce=1) and next_announce_time<? and status='finished' "
                    "order by next_announce_time asc limit ?",
                    (timestamp, int(self.conf.concurrent_blob_announcers * 10))
                ).fetchall()
            else:
                r = transaction.execute(
                    "select blob_hash from blob where blob_hash is not null "
                    "and next_announce_time<? and status='finished' "
                    "order by next_announce_time asc limit ?",
                    (timestamp, int(self.conf.concurrent_blob_announcers * 10))
                ).fetchall()
            return [b[0] for b in r]
        return self.db.run(get_and_update)

    def delete_blobs_from_db(self, blob_hashes):
        def delete_blobs(transaction):
            transaction.executemany(
                "delete from blob where blob_hash=?;", ((blob_hash,) for blob_hash in blob_hashes)
            ).fetchall()
        return self.db.run_with_foreign_keys_disabled(delete_blobs)

    def get_all_blob_hashes(self):
        return self.run_and_return_list("select blob_hash from blob")

    def sync_missing_blobs(self, blob_files: typing.Set[str]) -> typing.Awaitable[typing.Set[str]]:
        def _sync_blobs(transaction: sqlite3.Connection) -> typing.Set[str]:
            finished_blob_hashes = tuple(
                blob_hash for (blob_hash, ) in transaction.execute(
                    "select blob_hash from blob where status='finished'"
                ).fetchall()
            )
            finished_blobs_set = set(finished_blob_hashes)
            to_update_set = finished_blobs_set.difference(blob_files)
            transaction.executemany(
                "update blob set status='pending' where blob_hash=?",
                ((blob_hash, ) for blob_hash in to_update_set)
            ).fetchall()
            return blob_files.intersection(finished_blobs_set)
        return self.db.run(_sync_blobs)

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
        return self.db.run(store_stream, sd_blob, descriptor)

    def get_blobs_for_stream(self, stream_hash, only_completed=False) -> typing.Awaitable[typing.List[BlobInfo]]:
        def _get_blobs_for_stream(transaction):
            crypt_blob_infos = []
            stream_blobs = transaction.execute(
                "select blob_hash, position, iv from stream_blob where stream_hash=? "
                "order by position asc", (stream_hash, )
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
                if not blob_hash:
                    break
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
        return self.db.run_with_foreign_keys_disabled(delete_stream, descriptor)

    async def delete_torrent(self, bt_infohash: str):
        return await self.db.run(delete_torrent, bt_infohash)

    # # # # # # # # # file stuff # # # # # # # # #

    def save_downloaded_file(self, stream_hash: str, file_name: typing.Optional[str],
                             download_directory: typing.Optional[str], data_payment_rate: float,
                             content_fee: typing.Optional[Transaction] = None,
                             added_on: typing.Optional[int] = None) -> typing.Awaitable[int]:
        return self.save_published_file(
            stream_hash, file_name, download_directory, data_payment_rate, status="running",
            content_fee=content_fee, added_on=added_on
        )

    def save_published_file(self, stream_hash: str, file_name: typing.Optional[str],
                            download_directory: typing.Optional[str], data_payment_rate: float,
                            status: str = "finished",
                            content_fee: typing.Optional[Transaction] = None,
                            added_on: typing.Optional[int] = None) -> typing.Awaitable[int]:
        return self.db.run(store_file, stream_hash, file_name, download_directory, data_payment_rate, status,
                           content_fee, added_on)

    async def update_manually_removed_files_since_last_run(self):
        """
        Update files that have been removed from the downloads directory since the last run
        """
        def update_manually_removed_files(transaction: sqlite3.Connection):
            files = {}
            query = "select stream_hash, download_directory, file_name from file where saved_file=1 " \
                    "and stream_hash is not null"
            for (stream_hash, download_directory, file_name) in transaction.execute(query).fetchall():
                if download_directory and file_name:
                    files[stream_hash] = download_directory, file_name
            return files

        def detect_removed(files):
            return [
                stream_hash for stream_hash, (download_directory, file_name) in files.items()
                if not os.path.isfile(os.path.join(binascii.unhexlify(download_directory).decode(),
                                                   binascii.unhexlify(file_name).decode()))
            ]

        def update_db_removed(transaction: sqlite3.Connection, removed):
            query = "update file set file_name=null, download_directory=null, saved_file=0 where stream_hash in {}"
            for cur in _batched_select(transaction, query, removed):
                cur.fetchall()

        stream_and_file = await self.db.run(update_manually_removed_files)
        removed = await self.loop.run_in_executor(None, detect_removed, stream_and_file)
        if removed:
            await self.db.run(update_db_removed, removed)

    def get_all_lbry_files(self) -> typing.Awaitable[typing.List[typing.Dict]]:
        return self.db.run(get_all_lbry_files)

    def change_file_status(self, stream_hash: str, new_status: str):
        log.debug("update file status %s -> %s", stream_hash, new_status)
        return self.db.execute_fetchall("update file set status=? where stream_hash=?", (new_status, stream_hash))

    async def change_file_download_dir_and_file_name(self, stream_hash: str, download_dir: typing.Optional[str],
                                                     file_name: typing.Optional[str]):
        if not file_name or not download_dir:
            encoded_file_name, encoded_download_dir = None, None
        else:
            encoded_file_name = binascii.hexlify(file_name.encode()).decode()
            encoded_download_dir = binascii.hexlify(download_dir.encode()).decode()
        return await self.db.execute_fetchall("update file set download_directory=?, file_name=? where stream_hash=?", (
            encoded_download_dir, encoded_file_name, stream_hash,
        ))

    async def save_content_fee(self, stream_hash: str, content_fee: Transaction):
        return await self.db.execute_fetchall("update file set content_fee=? where stream_hash=?", (
            binascii.hexlify(content_fee.raw), stream_hash,
        ))

    async def set_saved_file(self, stream_hash: str):
        return await self.db.execute_fetchall("update file set saved_file=1 where stream_hash=?", (
            stream_hash,
        ))

    async def clear_saved_file(self, stream_hash: str):
        return await self.db.execute_fetchall("update file set saved_file=0 where stream_hash=?", (
            stream_hash,
        ))

    async def recover_streams(self, descriptors_and_sds: typing.List[typing.Tuple['StreamDescriptor', 'BlobFile',
                                                                                  typing.Optional[Transaction]]],
                              download_directory: str):
        def _recover(transaction: sqlite3.Connection):
            stream_hashes = [x[0].stream_hash for x in descriptors_and_sds]
            for descriptor, sd_blob, content_fee in descriptors_and_sds:
                content_claim = transaction.execute(
                    "select * from content_claim where stream_hash=?", (descriptor.stream_hash, )
                ).fetchone()
                delete_stream(transaction, descriptor)  # this will also delete the content claim
                store_stream(transaction, sd_blob, descriptor)
                store_file(transaction, descriptor.stream_hash, os.path.basename(descriptor.suggested_file_name),
                           download_directory, 0.0, 'stopped', content_fee=content_fee)
                if content_claim:
                    transaction.execute("insert or ignore into content_claim values (?, ?, ?)", content_claim)
            transaction.executemany(
                "update file set status='stopped' where stream_hash=?",
                ((stream_hash, ) for stream_hash in stream_hashes)
            ).fetchall()
            download_dir = binascii.hexlify(self.conf.download_dir.encode()).decode()
            transaction.executemany(
                f"update file set download_directory=? where stream_hash=?",
                ((download_dir, stream_hash) for stream_hash in stream_hashes)
            ).fetchall()
        await self.db.run_with_foreign_keys_disabled(_recover)

    def get_all_stream_hashes(self):
        return self.run_and_return_list("select stream_hash from stream")

    # # # # # # # # # support functions # # # # # # # # #

    def save_supports(self, claim_id_to_supports: dict):
        # TODO: add 'address' to support items returned for a claim from lbrycrdd and lbryum-server
        def _save_support(transaction):
            bind = "({})".format(','.join(['?'] * len(claim_id_to_supports)))
            transaction.execute(
                f"delete from support where claim_id in {bind}", tuple(claim_id_to_supports.keys())
            ).fetchall()
            for claim_id, supports in claim_id_to_supports.items():
                for support in supports:
                    transaction.execute(
                        "insert into support values (?, ?, ?, ?)",
                        ("%s:%i" % (support['txid'], support['nout']), claim_id, lbc_to_dewies(support['amount']),
                         support.get('address', ""))
                    ).fetchall()
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
                    claim_ids
                )
            ]

        return self.db.run(_get_supports)

    # # # # # # # # # claim functions # # # # # # # # #

    async def save_claims(self, claim_infos):
        claim_id_to_supports = {}
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
                certificate_id = claim_info['value'].signing_channel_id
                try:
                    source_hash = claim_info['value'].stream.source.sd_hash
                except (AttributeError, ValueError):
                    source_hash = None
                serialized = binascii.hexlify(claim_info['value'].to_bytes())
                transaction.execute(
                    "insert or replace into claim values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (outpoint, claim_id, name, amount, height, serialized, certificate_id, address, sequence)
                ).fetchall()
                # if this response doesn't have support info don't overwrite the existing
                # support info
                if 'supports' in claim_info:
                    claim_id_to_supports[claim_id] = claim_info['supports']
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
                ).fetchone()
                known_claim_id = transaction.execute(
                    "select claim_id from claim "
                    "inner join content_claim c3 ON claim.claim_outpoint=c3.claim_outpoint "
                    "where c3.stream_hash=?", (stream_hash,)
                ).fetchone()
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
        if claim_id_to_supports:
            await self.save_supports(claim_id_to_supports)

    def save_claim_from_output(self, ledger, *outputs: Output):
        return self.save_claims([{
            "claim_id": output.claim_id,
            "name": output.claim_name,
            "amount": dewies_to_lbc(output.amount),
            "address": output.get_address(ledger),
            "txid": output.tx_ref.id,
            "nout": output.position,
            "value": output.claim,
            "height": output.tx_ref.height,
            "claim_sequence": -1,
        } for output in outputs])

    def save_claims_for_resolve(self, claim_infos):
        to_save = {}
        for info in claim_infos:
            if 'value' in info:
                if info['value']:
                    to_save[info['claim_id']] = info
            else:
                for key in ('certificate', 'claim'):
                    if info.get(key, {}).get('value'):
                        to_save[info[key]['claim_id']] = info[key]
        return self.save_claims(to_save.values())

    @staticmethod
    def _save_content_claim(transaction, claim_outpoint, stream_hash=None, bt_infohash=None):
        assert stream_hash or bt_infohash
        # get the claim id and serialized metadata
        claim_info = transaction.execute(
            "select claim_id, serialized_metadata from claim where claim_outpoint=?", (claim_outpoint,)
        ).fetchone()
        if not claim_info:
            raise Exception("claim not found")
        new_claim_id, claim = claim_info[0], Claim.from_bytes(binascii.unhexlify(claim_info[1]))

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
        if known_sd_hash[0] != claim.stream.source.sd_hash:
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
        transaction.execute("delete from content_claim where stream_hash=?", (stream_hash, )).fetchall()
        transaction.execute(
            "insert into content_claim values (?, NULL, ?)", (stream_hash, claim_outpoint)
        ).fetchall()

    async def save_content_claim(self, stream_hash, claim_outpoint):
        await self.db.run(self._save_content_claim, claim_outpoint, stream_hash)
        # update corresponding ManagedEncryptedFileDownloader object
        if stream_hash in self.content_claim_callbacks:
            await self.content_claim_callbacks[stream_hash]()

    async def save_torrent_content_claim(self, bt_infohash, claim_outpoint, length, name):
        def _save_torrent(transaction):
            transaction.execute(
                "insert or replace into torrent values (?, NULL, ?, ?)", (bt_infohash, length, name)
            ).fetchall()
            transaction.execute(
                "insert or replace into content_claim values (NULL, ?, ?)", (bt_infohash, claim_outpoint)
            ).fetchall()
        await self.db.run(_save_torrent)
        # update corresponding ManagedEncryptedFileDownloader object
        if bt_infohash in self.content_claim_callbacks:
            await self.content_claim_callbacks[bt_infohash]()

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

    async def get_content_claim_for_torrent(self, bt_infohash):
        claims = await self.db.run(get_claims_from_torrent_info_hashes, [bt_infohash])
        return claims[bt_infohash].as_dict() if claims else None

    # # # # # # # # # reflector functions # # # # # # # # #

    def update_reflected_stream(self, sd_hash, reflector_address, success=True):
        if success:
            return self.db.execute_fetchall(
                "insert or replace into reflected_stream values (?, ?, ?)",
                (sd_hash, reflector_address, self.time_getter())
            )
        return self.db.execute_fetchall(
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

    # # # # # # # # # # dht functions # # # # # # # # # # #
    async def get_persisted_kademlia_peers(self) -> typing.List[typing.Tuple[bytes, str, int, int]]:
        query = 'select node_id, address, udp_port, tcp_port from peer'
        return [(binascii.unhexlify(n), a, u, t) for n, a, u, t in await self.db.execute_fetchall(query)]

    async def save_kademlia_peers(self, peers: typing.List['KademliaPeer']):
        def _save_kademlia_peers(transaction: sqlite3.Connection):
            transaction.execute('delete from peer').fetchall()
            transaction.executemany(
                'insert into peer(node_id, address, udp_port, tcp_port) values (?, ?, ?, ?)',
                tuple([(binascii.hexlify(p.node_id), p.address, p.udp_port, p.tcp_port) for p in peers])
            ).fetchall()
        return await self.db.run(_save_kademlia_peers)
