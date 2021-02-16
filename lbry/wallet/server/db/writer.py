import os
import apsw
from typing import Union, Tuple, Set, List
from itertools import chain
from decimal import Decimal
from collections import namedtuple
from multiprocessing import Manager
from binascii import unhexlify
from lbry.wallet.server.leveldb import LevelDB
from lbry.wallet.server.util import class_logger
from lbry.wallet.database import query, constraints_to_sql

from lbry.schema.tags import clean_tags
from lbry.schema.mime_types import guess_stream_type
from lbry.wallet import Ledger, RegTestLedger
from lbry.wallet.transaction import Transaction, Output
from lbry.wallet.server.db.canonical import register_canonical_functions
from lbry.wallet.server.db.full_text_search import update_full_text_search, CREATE_FULL_TEXT_SEARCH, first_sync_finished
from lbry.wallet.server.db.trending import TRENDING_ALGORITHMS

from .common import CLAIM_TYPES, STREAM_TYPES, COMMON_TAGS, INDEXED_LANGUAGES


ATTRIBUTE_ARRAY_MAX_LENGTH = 100


class SQLDB:

    PRAGMAS = """
        pragma journal_mode=WAL;
    """

    CREATE_CLAIM_TABLE = """
        create table if not exists claim (
            claim_hash bytes primary key,
            claim_id text not null,
            claim_name text not null,
            normalized text not null,
            txo_hash bytes not null,
            tx_position integer not null,
            amount integer not null,
            timestamp integer not null, -- last updated timestamp
            creation_timestamp integer not null,
            height integer not null, -- last updated height
            creation_height integer not null,
            activation_height integer,
            expiration_height integer not null,
            release_time integer not null,

            short_url text not null, -- normalized#shortest-unique-claim_id
            canonical_url text, -- channel's-short_url/normalized#shortest-unique-claim_id-within-channel

            title text,
            author text,
            description text,

            claim_type integer,
            reposted integer default 0,

            -- streams
            stream_type text,
            media_type text,
            fee_amount integer default 0,
            fee_currency text,
            duration integer,

            -- reposts
            reposted_claim_hash bytes,

            -- claims which are channels
            public_key_bytes bytes,
            public_key_hash bytes,
            claims_in_channel integer,

            -- claims which are inside channels
            channel_hash bytes,
            channel_join integer, -- height at which claim got valid signature / joined channel
            signature bytes,
            signature_digest bytes,
            signature_valid bool,

            effective_amount integer not null default 0,
            support_amount integer not null default 0,
            trending_group integer not null default 0,
            trending_mixed integer not null default 0,
            trending_local integer not null default 0,
            trending_global integer not null default 0
        );

        create index if not exists claim_normalized_idx on claim (normalized, activation_height);
        create index if not exists claim_channel_hash_idx on claim (channel_hash, signature, claim_hash);
        create index if not exists claim_claims_in_channel_idx on claim (signature_valid, channel_hash, normalized);
        create index if not exists claim_txo_hash_idx on claim (txo_hash);
        create index if not exists claim_activation_height_idx on claim (activation_height, claim_hash);
        create index if not exists claim_expiration_height_idx on claim (expiration_height);
        create index if not exists claim_reposted_claim_hash_idx on claim (reposted_claim_hash);
    """

    CREATE_SUPPORT_TABLE = """
        create table if not exists support (
            txo_hash bytes primary key,
            tx_position integer not null,
            height integer not null,
            claim_hash bytes not null,
            amount integer not null
        );
        create index if not exists support_claim_hash_idx on support (claim_hash, height);
    """

    CREATE_TAG_TABLE = """
        create table if not exists tag (
            tag text not null,
            claim_hash bytes not null,
            height integer not null
        );
        create unique index if not exists tag_claim_hash_tag_idx on tag (claim_hash, tag);
    """

    CREATE_LANGUAGE_TABLE = """
        create table if not exists language (
            language text not null,
            claim_hash bytes not null,
            height integer not null
        );
        create unique index if not exists language_claim_hash_language_idx on language (claim_hash, language);
    """

    CREATE_CLAIMTRIE_TABLE = """
        create table if not exists claimtrie (
            normalized text primary key,
            claim_hash bytes not null,
            last_take_over_height integer not null
        );
        create index if not exists claimtrie_claim_hash_idx on claimtrie (claim_hash);
    """

    SEARCH_INDEXES = """
        -- used by any tag clouds
        create index if not exists tag_tag_idx on tag (tag, claim_hash);

        -- naked order bys (no filters)
        create unique index if not exists claim_release_idx on claim (release_time, claim_hash);
        create unique index if not exists claim_trending_idx on claim (trending_group, trending_mixed, claim_hash);
        create unique index if not exists claim_effective_amount_idx on claim (effective_amount, claim_hash);

        -- claim_type filter + order by
        create unique index if not exists claim_type_release_idx on claim (release_time, claim_type, claim_hash);
        create unique index if not exists claim_type_trending_idx on claim (trending_group, trending_mixed, claim_type, claim_hash);
        create unique index if not exists claim_type_effective_amount_idx on claim (effective_amount, claim_type, claim_hash);

        -- stream_type filter + order by
        create unique index if not exists stream_type_release_idx on claim (stream_type, release_time, claim_hash);
        create unique index if not exists stream_type_trending_idx on claim (stream_type, trending_group, trending_mixed, claim_hash);
        create unique index if not exists stream_type_effective_amount_idx on claim (stream_type, effective_amount, claim_hash);

        -- channel_hash filter + order by
        create unique index if not exists channel_hash_release_idx on claim (channel_hash, release_time, claim_hash);
        create unique index if not exists channel_hash_trending_idx on claim (channel_hash, trending_group, trending_mixed, claim_hash);
        create unique index if not exists channel_hash_effective_amount_idx on claim (channel_hash, effective_amount, claim_hash);

        -- duration filter + order by
        create unique index if not exists duration_release_idx on claim (duration, release_time, claim_hash);
        create unique index if not exists duration_trending_idx on claim (duration, trending_group, trending_mixed, claim_hash);
        create unique index if not exists duration_effective_amount_idx on claim (duration, effective_amount, claim_hash);

        -- fee_amount + order by
        create unique index if not exists fee_amount_release_idx on claim (fee_amount, release_time, claim_hash);
        create unique index if not exists fee_amount_trending_idx on claim (fee_amount, trending_group, trending_mixed, claim_hash);
        create unique index if not exists fee_amount_effective_amount_idx on claim (fee_amount, effective_amount, claim_hash);

        -- TODO: verify that all indexes below are used
        create index if not exists claim_height_normalized_idx on claim (height, normalized asc);
        create index if not exists claim_resolve_idx on claim (normalized, claim_id);
        create index if not exists claim_id_idx on claim (claim_id, claim_hash);
        create index if not exists claim_timestamp_idx on claim (timestamp);
        create index if not exists claim_public_key_hash_idx on claim (public_key_hash);
        create index if not exists claim_signature_valid_idx on claim (signature_valid);
    """

    TAG_INDEXES = '\n'.join(
        f"create unique index if not exists tag_{tag_key}_idx on tag (tag, claim_hash) WHERE tag='{tag_value}';"
        for tag_value, tag_key in COMMON_TAGS.items()
    )

    LANGUAGE_INDEXES = '\n'.join(
        f"create unique index if not exists language_{language}_idx on language (language, claim_hash) WHERE language='{language}';"
        for language in INDEXED_LANGUAGES
    )

    CREATE_TABLES_QUERY = (
        CREATE_CLAIM_TABLE +
        CREATE_FULL_TEXT_SEARCH +
        CREATE_SUPPORT_TABLE +
        CREATE_CLAIMTRIE_TABLE +
        CREATE_TAG_TABLE +
        CREATE_LANGUAGE_TABLE
    )

    def __init__(
            self, main, path: str, blocking_channels: list, filtering_channels: list, trending: list):
        self.main = main
        self._db_path = path
        self.db = None
        self.logger = class_logger(__name__, self.__class__.__name__)
        self.ledger = Ledger if main.coin.NET == 'mainnet' else RegTestLedger
        self._fts_synced = False
        self.state_manager = None
        self.blocked_streams = None
        self.blocked_channels = None
        self.blocking_channel_hashes = {
            unhexlify(channel_id)[::-1] for channel_id in blocking_channels if channel_id
        }
        self.filtered_streams = None
        self.filtered_channels = None
        self.filtering_channel_hashes = {
            unhexlify(channel_id)[::-1] for channel_id in filtering_channels if channel_id
        }
        self.trending = trending

    def open(self):
        self.db = apsw.Connection(
            self._db_path,
            flags=(
                apsw.SQLITE_OPEN_READWRITE |
                apsw.SQLITE_OPEN_CREATE |
                apsw.SQLITE_OPEN_URI
            )
        )
        def exec_factory(cursor, statement, bindings):
            tpl = namedtuple('row', (d[0] for d in cursor.getdescription()))
            cursor.setrowtrace(lambda cursor, row: tpl(*row))
            return True
        self.db.setexectrace(exec_factory)
        self.execute(self.PRAGMAS)
        self.execute(self.CREATE_TABLES_QUERY)
        register_canonical_functions(self.db)
        self.state_manager = Manager()
        self.blocked_streams = self.state_manager.dict()
        self.blocked_channels = self.state_manager.dict()
        self.filtered_streams = self.state_manager.dict()
        self.filtered_channels = self.state_manager.dict()
        self.update_blocked_and_filtered_claims()
        for algorithm in self.trending:
            algorithm.install(self.db)

    def close(self):
        if self.db is not None:
            self.db.close()
        if self.state_manager is not None:
            self.state_manager.shutdown()

    def update_blocked_and_filtered_claims(self):
        self.update_claims_from_channel_hashes(
            self.blocked_streams, self.blocked_channels, self.blocking_channel_hashes
        )
        self.update_claims_from_channel_hashes(
            self.filtered_streams, self.filtered_channels, self.filtering_channel_hashes
        )
        self.filtered_streams.update(self.blocked_streams)
        self.filtered_channels.update(self.blocked_channels)

    def update_claims_from_channel_hashes(self, shared_streams, shared_channels, channel_hashes):
        streams, channels = {}, {}
        if channel_hashes:
            sql = query(
                "SELECT repost.channel_hash, repost.reposted_claim_hash, target.claim_type "
                "FROM claim as repost JOIN claim AS target ON (target.claim_hash=repost.reposted_claim_hash)", **{
                    'repost.reposted_claim_hash__is_not_null': 1,
                    'repost.channel_hash__in': channel_hashes
                }
            )
            for blocked_claim in self.execute(*sql):
                if blocked_claim.claim_type == CLAIM_TYPES['stream']:
                    streams[blocked_claim.reposted_claim_hash] = blocked_claim.channel_hash
                elif blocked_claim.claim_type == CLAIM_TYPES['channel']:
                    channels[blocked_claim.reposted_claim_hash] = blocked_claim.channel_hash
        shared_streams.clear()
        shared_streams.update(streams)
        shared_channels.clear()
        shared_channels.update(channels)

    @staticmethod
    def _insert_sql(table: str, data: dict) -> Tuple[str, list]:
        columns, values = [], []
        for column, value in data.items():
            columns.append(column)
            values.append(value)
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) "
            f"VALUES ({', '.join(['?'] * len(values))})"
        )
        return sql, values

    @staticmethod
    def _update_sql(table: str, data: dict, where: str,
                    constraints: Union[list, tuple]) -> Tuple[str, list]:
        columns, values = [], []
        for column, value in data.items():
            columns.append(f"{column} = ?")
            values.append(value)
        values.extend(constraints)
        return f"UPDATE {table} SET {', '.join(columns)} WHERE {where}", values

    @staticmethod
    def _delete_sql(table: str, constraints: dict) -> Tuple[str, dict]:
        where, values = constraints_to_sql(constraints)
        return f"DELETE FROM {table} WHERE {where}", values

    def execute(self, *args):
        return self.db.cursor().execute(*args)

    def executemany(self, *args):
        return self.db.cursor().executemany(*args)

    def begin(self):
        self.execute('begin;')

    def commit(self):
        self.execute('commit;')

    def _upsertable_claims(self, txos: List[Output], header, clear_first=False):
        claim_hashes, claims, tags, languages = set(), [], {}, {}
        for txo in txos:
            tx = txo.tx_ref.tx

            try:
                assert txo.claim_name
                assert txo.normalized_name
            except:
                #self.logger.exception(f"Could not decode claim name for {tx.id}:{txo.position}.")
                continue

            language = 'none'
            try:
                if txo.claim.is_stream and txo.claim.stream.languages:
                    language = txo.claim.stream.languages[0].language
            except:
                pass

            claim_hash = txo.claim_hash
            claim_hashes.add(claim_hash)
            claim_record = {
                'claim_hash': claim_hash,
                'claim_id': txo.claim_id,
                'claim_name': txo.claim_name,
                'normalized': txo.normalized_name,
                'txo_hash': txo.ref.hash,
                'tx_position': tx.position,
                'amount': txo.amount,
                'timestamp': header['timestamp'],
                'height': tx.height,
                'title': None,
                'description': None,
                'author': None,
                'duration': None,
                'claim_type': None,
                'stream_type': None,
                'media_type': None,
                'release_time': None,
                'fee_currency': None,
                'fee_amount': 0,
                'reposted_claim_hash': None
            }
            claims.append(claim_record)

            try:
                claim = txo.claim
            except:
                #self.logger.exception(f"Could not parse claim protobuf for {tx.id}:{txo.position}.")
                continue

            if claim.is_stream:
                claim_record['claim_type'] = CLAIM_TYPES['stream']
                claim_record['media_type'] = claim.stream.source.media_type
                claim_record['stream_type'] = STREAM_TYPES[guess_stream_type(claim_record['media_type'])]
                claim_record['title'] = claim.stream.title
                claim_record['description'] = claim.stream.description
                claim_record['author'] = claim.stream.author
                if claim.stream.video and claim.stream.video.duration:
                    claim_record['duration'] = claim.stream.video.duration
                if claim.stream.audio and claim.stream.audio.duration:
                    claim_record['duration'] = claim.stream.audio.duration
                if claim.stream.release_time:
                    claim_record['release_time'] = claim.stream.release_time
                if claim.stream.has_fee:
                    fee = claim.stream.fee
                    if isinstance(fee.currency, str):
                        claim_record['fee_currency'] = fee.currency.lower()
                    if isinstance(fee.amount, Decimal):
                        claim_record['fee_amount'] = int(fee.amount*1000)
            elif claim.is_repost:
                claim_record['claim_type'] = CLAIM_TYPES['repost']
                claim_record['reposted_claim_hash'] = claim.repost.reference.claim_hash
            elif claim.is_channel:
                claim_record['claim_type'] = CLAIM_TYPES['channel']
            elif claim.is_collection:
                claim_record['claim_type'] = CLAIM_TYPES['collection']

            languages[(language, claim_hash)] = (language, claim_hash, tx.height)

            for tag in clean_tags(claim.message.tags):
                tags[(tag, claim_hash)] = (tag, claim_hash, tx.height)

        if clear_first:
            self._clear_claim_metadata(claim_hashes)

        if tags:
            self.executemany(
                "INSERT OR IGNORE INTO tag (tag, claim_hash, height) VALUES (?, ?, ?)", tags.values()
            )
        if languages:
            self.executemany(
                "INSERT OR IGNORE INTO language (language, claim_hash, height) VALUES (?, ?, ?)", languages.values()
            )

        return claims

    def insert_claims(self, txos: List[Output], header):
        claims = self._upsertable_claims(txos, header)
        if claims:
            self.executemany("""
                INSERT OR IGNORE INTO claim (
                    claim_hash, claim_id, claim_name, normalized, txo_hash, tx_position, amount,
                    claim_type, media_type, stream_type, timestamp, creation_timestamp,
                    fee_currency, fee_amount, title, description, author, duration, height, reposted_claim_hash,
                    creation_height, release_time, activation_height, expiration_height, short_url)
                VALUES (
                    :claim_hash, :claim_id, :claim_name, :normalized, :txo_hash, :tx_position, :amount,
                    :claim_type, :media_type, :stream_type, :timestamp, :timestamp,
                    :fee_currency, :fee_amount, :title, :description, :author, :duration, :height, :reposted_claim_hash, :height,
                    CASE WHEN :release_time IS NOT NULL THEN :release_time ELSE :timestamp END,
                    CASE WHEN :normalized NOT IN (SELECT normalized FROM claimtrie) THEN :height END,
                    CASE WHEN :height >= 137181 THEN :height+2102400 ELSE :height+262974 END,
                    :claim_name||COALESCE(
                        (SELECT shortest_id(claim_id, :claim_id) FROM claim WHERE normalized = :normalized),
                        '#'||substr(:claim_id, 1, 1)
                    )
                )""", claims)

    def update_claims(self, txos: List[Output], header):
        claims = self._upsertable_claims(txos, header, clear_first=True)
        if claims:
            self.executemany("""
                UPDATE claim SET
                    txo_hash=:txo_hash, tx_position=:tx_position, amount=:amount, height=:height,
                    claim_type=:claim_type, media_type=:media_type, stream_type=:stream_type,
                    timestamp=:timestamp, fee_amount=:fee_amount, fee_currency=:fee_currency,
                    title=:title, duration=:duration, description=:description, author=:author, reposted_claim_hash=:reposted_claim_hash,
                    release_time=CASE WHEN :release_time IS NOT NULL THEN :release_time ELSE release_time END
                WHERE claim_hash=:claim_hash;
                """, claims)

    def delete_claims(self, claim_hashes: Set[bytes]):
        """ Deletes claim supports and from claimtrie in case of an abandon. """
        if claim_hashes:
            affected_channels = self.execute(*query(
                "SELECT channel_hash FROM claim", channel_hash__is_not_null=1, claim_hash__in=claim_hashes
            )).fetchall()
            for table in ('claim', 'support', 'claimtrie'):
                self.execute(*self._delete_sql(table, {'claim_hash__in': claim_hashes}))
            self._clear_claim_metadata(claim_hashes)
            return {r.channel_hash for r in affected_channels}
        return set()

    def delete_claims_above_height(self, height: int):
        claim_hashes = [x[0] for x in self.execute(
            "SELECT claim_hash FROM claim WHERE height>?", (height, )
        ).fetchall()]
        while claim_hashes:
            batch = set(claim_hashes[:500])
            claim_hashes = claim_hashes[500:]
            self.delete_claims(batch)

    def _clear_claim_metadata(self, claim_hashes: Set[bytes]):
        if claim_hashes:
            for table in ('tag',):  # 'language', 'location', etc
                self.execute(*self._delete_sql(table, {'claim_hash__in': claim_hashes}))

    def split_inputs_into_claims_supports_and_other(self, txis):
        txo_hashes = {txi.txo_ref.hash for txi in txis}
        claims = self.execute(*query(
            "SELECT txo_hash, claim_hash, normalized FROM claim", txo_hash__in=txo_hashes
        )).fetchall()
        txo_hashes -= {r.txo_hash for r in claims}
        supports = {}
        if txo_hashes:
            supports = self.execute(*query(
                "SELECT txo_hash, claim_hash FROM support", txo_hash__in=txo_hashes
            )).fetchall()
            txo_hashes -= {r.txo_hash for r in supports}
        return claims, supports, txo_hashes

    def insert_supports(self, txos: List[Output]):
        supports = []
        for txo in txos:
            tx = txo.tx_ref.tx
            supports.append((
                txo.ref.hash, tx.position, tx.height,
                txo.claim_hash, txo.amount
            ))
        if supports:
            self.executemany(
                "INSERT OR IGNORE INTO support ("
                "   txo_hash, tx_position, height, claim_hash, amount"
                ") "
                "VALUES (?, ?, ?, ?, ?)", supports
            )

    def delete_supports(self, txo_hashes: Set[bytes]):
        if txo_hashes:
            self.execute(*self._delete_sql('support', {'txo_hash__in': txo_hashes}))

    def calculate_reposts(self, txos: List[Output]):
        targets = set()
        for txo in txos:
            try:
                claim = txo.claim
            except:
                continue
            if claim.is_repost:
                targets.add((claim.repost.reference.claim_hash,))
        if targets:
            self.executemany(
                """
                UPDATE claim SET reposted = (
                    SELECT count(*) FROM claim AS repost WHERE repost.reposted_claim_hash = claim.claim_hash
                )
                WHERE claim_hash = ?
                """, targets
            )

    def validate_channel_signatures(self, height, new_claims, updated_claims, spent_claims, affected_channels, timer):
        if not new_claims and not updated_claims and not spent_claims:
            return

        sub_timer = timer.add_timer('segregate channels and signables')
        sub_timer.start()
        channels, new_channel_keys, signables = {}, {}, {}
        for txo in chain(new_claims, updated_claims):
            try:
                claim = txo.claim
            except:
                continue
            if claim.is_channel:
                channels[txo.claim_hash] = txo
                new_channel_keys[txo.claim_hash] = claim.channel.public_key_bytes
            else:
                signables[txo.claim_hash] = txo
        sub_timer.stop()

        sub_timer = timer.add_timer('make list of channels we need to lookup')
        sub_timer.start()
        missing_channel_keys = set()
        for txo in signables.values():
            claim = txo.claim
            if claim.is_signed and claim.signing_channel_hash not in new_channel_keys:
                missing_channel_keys.add(claim.signing_channel_hash)
        sub_timer.stop()

        sub_timer = timer.add_timer('lookup missing channels')
        sub_timer.start()
        all_channel_keys = {}
        if new_channel_keys or missing_channel_keys or affected_channels:
            all_channel_keys = dict(self.execute(*query(
                "SELECT claim_hash, public_key_bytes FROM claim",
                claim_hash__in=set(new_channel_keys) | missing_channel_keys | affected_channels
            )))
        sub_timer.stop()

        sub_timer = timer.add_timer('prepare for updating claims')
        sub_timer.start()
        changed_channel_keys = {}
        for claim_hash, new_key in new_channel_keys.items():
            if claim_hash not in all_channel_keys or all_channel_keys[claim_hash] != new_key:
                all_channel_keys[claim_hash] = new_key
                changed_channel_keys[claim_hash] = new_key

        claim_updates = []

        for claim_hash, txo in signables.items():
            claim = txo.claim
            update = {
                'claim_hash': claim_hash,
                'channel_hash': None,
                'signature': None,
                'signature_digest': None,
                'signature_valid': None
            }
            if claim.is_signed:
                update.update({
                    'channel_hash': claim.signing_channel_hash,
                    'signature': txo.get_encoded_signature(),
                    'signature_digest': txo.get_signature_digest(self.ledger),
                    'signature_valid': 0
                })
            claim_updates.append(update)
        sub_timer.stop()

        sub_timer = timer.add_timer('find claims affected by a change in channel key')
        sub_timer.start()
        if changed_channel_keys:
            sql = f"""
            SELECT * FROM claim WHERE
                channel_hash IN ({','.join('?' for _ in changed_channel_keys)}) AND
                signature IS NOT NULL
            """
            for affected_claim in self.execute(sql, changed_channel_keys.keys()):
                if affected_claim.claim_hash not in signables:
                    claim_updates.append({
                        'claim_hash': affected_claim.claim_hash,
                        'channel_hash': affected_claim.channel_hash,
                        'signature': affected_claim.signature,
                        'signature_digest': affected_claim.signature_digest,
                        'signature_valid': 0
                    })
        sub_timer.stop()

        sub_timer = timer.add_timer('verify signatures')
        sub_timer.start()
        for update in claim_updates:
            channel_pub_key = all_channel_keys.get(update['channel_hash'])
            if channel_pub_key and update['signature']:
                update['signature_valid'] = Output.is_signature_valid(
                    bytes(update['signature']), bytes(update['signature_digest']), channel_pub_key
                )
        sub_timer.stop()

        sub_timer = timer.add_timer('update claims')
        sub_timer.start()
        if claim_updates:
            self.executemany(f"""
                UPDATE claim SET 
                    channel_hash=:channel_hash, signature=:signature, signature_digest=:signature_digest,
                    signature_valid=:signature_valid,
                    channel_join=CASE
                        WHEN signature_valid=1 AND :signature_valid=1 AND channel_hash=:channel_hash THEN channel_join
                        WHEN :signature_valid=1 THEN {height}
                    END,
                    canonical_url=CASE
                        WHEN signature_valid=1 AND :signature_valid=1 AND channel_hash=:channel_hash THEN canonical_url
                        WHEN :signature_valid=1 THEN
                            (SELECT short_url FROM claim WHERE claim_hash=:channel_hash)||'/'||
                            claim_name||COALESCE(
                                (SELECT shortest_id(other_claim.claim_id, claim.claim_id) FROM claim AS other_claim
                                 WHERE other_claim.signature_valid = 1 AND
                                       other_claim.channel_hash = :channel_hash AND
                                       other_claim.normalized = claim.normalized),
                                '#'||substr(claim_id, 1, 1)
                            )
                    END
                WHERE claim_hash=:claim_hash;
                """, claim_updates)
        sub_timer.stop()

        sub_timer = timer.add_timer('update claims affected by spent channels')
        sub_timer.start()
        if spent_claims:
            self.execute(
                f"""
                UPDATE claim SET
                    signature_valid=CASE WHEN signature IS NOT NULL THEN 0 END,
                    channel_join=NULL, canonical_url=NULL
                WHERE channel_hash IN ({','.join('?' for _ in spent_claims)})
                """, spent_claims
            )
        sub_timer.stop()

        sub_timer = timer.add_timer('update channels')
        sub_timer.start()
        if channels:
            self.executemany(
                """
                UPDATE claim SET
                    public_key_bytes=:public_key_bytes,
                    public_key_hash=:public_key_hash
                WHERE claim_hash=:claim_hash""", [{
                    'claim_hash': claim_hash,
                    'public_key_bytes': txo.claim.channel.public_key_bytes,
                    'public_key_hash': self.ledger.address_to_hash160(
                            self.ledger.public_key_to_address(txo.claim.channel.public_key_bytes)
                    )
                } for claim_hash, txo in channels.items()]
            )
        sub_timer.stop()

        sub_timer = timer.add_timer('update claims_in_channel counts')
        sub_timer.start()
        if all_channel_keys:
            self.executemany(f"""
                UPDATE claim SET
                    claims_in_channel=(
                        SELECT COUNT(*) FROM claim AS claim_in_channel
                        WHERE claim_in_channel.signature_valid=1 AND
                              claim_in_channel.channel_hash=claim.claim_hash
                    )
                WHERE claim_hash = ?
            """, [(channel_hash,) for channel_hash in all_channel_keys.keys()])
        sub_timer.stop()

        sub_timer = timer.add_timer('update blocked claims list')
        sub_timer.start()
        if (self.blocking_channel_hashes.intersection(all_channel_keys) or
                self.filtering_channel_hashes.intersection(all_channel_keys)):
            self.update_blocked_and_filtered_claims()
        sub_timer.stop()

    def _update_support_amount(self, claim_hashes):
        if claim_hashes:
            self.execute(f"""
                UPDATE claim SET
                    support_amount = COALESCE(
                        (SELECT SUM(amount) FROM support WHERE support.claim_hash=claim.claim_hash), 0
                    )
                WHERE claim_hash IN ({','.join('?' for _ in claim_hashes)})
            """, claim_hashes)

    def _update_effective_amount(self, height, claim_hashes=None):
        self.execute(
            f"UPDATE claim SET effective_amount = amount + support_amount "
            f"WHERE activation_height = {height}"
        )
        if claim_hashes:
            self.execute(
                f"UPDATE claim SET effective_amount = amount + support_amount "
                f"WHERE activation_height < {height} "
                f"  AND claim_hash IN ({','.join('?' for _ in claim_hashes)})",
                claim_hashes
            )

    def _calculate_activation_height(self, height):
        last_take_over_height = f"""COALESCE(
            (SELECT last_take_over_height FROM claimtrie
            WHERE claimtrie.normalized=claim.normalized),
            {height}
        )
        """
        self.execute(f"""
            UPDATE claim SET activation_height = 
                {height} + min(4032, cast(({height} - {last_take_over_height}) / 32 AS INT))
            WHERE activation_height IS NULL
        """)

    def _perform_overtake(self, height, changed_claim_hashes, deleted_names):
        deleted_names_sql = claim_hashes_sql = ""
        if changed_claim_hashes:
            claim_hashes_sql = f"OR claim_hash IN ({','.join('?' for _ in changed_claim_hashes)})"
        if deleted_names:
            deleted_names_sql = f"OR normalized IN ({','.join('?' for _ in deleted_names)})"
        overtakes = self.execute(f"""
            SELECT winner.normalized, winner.claim_hash,
                   claimtrie.claim_hash AS current_winner,
                   MAX(winner.effective_amount) AS max_winner_effective_amount
            FROM (
                SELECT normalized, claim_hash, effective_amount FROM claim
                WHERE normalized IN (
                    SELECT normalized FROM claim WHERE activation_height={height} {claim_hashes_sql}
                ) {deleted_names_sql}
                ORDER BY effective_amount DESC, height ASC, tx_position ASC
            ) AS winner LEFT JOIN claimtrie USING (normalized)
            GROUP BY winner.normalized
            HAVING current_winner IS NULL OR current_winner <> winner.claim_hash
        """, list(changed_claim_hashes)+deleted_names)
        for overtake in overtakes:
            if overtake.current_winner:
                self.execute(
                    f"UPDATE claimtrie SET claim_hash = ?, last_take_over_height = {height} "
                    f"WHERE normalized = ?",
                    (overtake.claim_hash, overtake.normalized)
                )
            else:
                self.execute(
                    f"INSERT INTO claimtrie (claim_hash, normalized, last_take_over_height) "
                    f"VALUES (?, ?, {height})",
                    (overtake.claim_hash, overtake.normalized)
                )
            self.execute(
                f"UPDATE claim SET activation_height = {height} WHERE normalized = ? "
                f"AND (activation_height IS NULL OR activation_height > {height})",
                (overtake.normalized,)
            )

    def _copy(self, height):
        if height > 50:
            self.execute(f"DROP TABLE claimtrie{height-50}")
        self.execute(f"CREATE TABLE claimtrie{height} AS SELECT * FROM claimtrie")

    def update_claimtrie(self, height, changed_claim_hashes, deleted_names, timer):
        r = timer.run

        r(self._calculate_activation_height, height)
        r(self._update_support_amount, changed_claim_hashes)

        r(self._update_effective_amount, height, changed_claim_hashes)
        r(self._perform_overtake, height, changed_claim_hashes, list(deleted_names))

        r(self._update_effective_amount, height)
        r(self._perform_overtake, height, [], [])

    def get_expiring(self, height):
        return self.execute(
            f"SELECT claim_hash, normalized FROM claim WHERE expiration_height = {height}"
        )

    def advance_txs(self, height, all_txs, header, daemon_height, timer):
        insert_claims = []
        update_claims = []
        update_claim_hashes = set()
        delete_claim_hashes = set()
        insert_supports = []
        delete_support_txo_hashes = set()
        recalculate_claim_hashes = set()  # added/deleted supports, added/updated claim
        deleted_claim_names = set()
        delete_others = set()
        body_timer = timer.add_timer('body')
        for position, (etx, txid) in enumerate(all_txs):
            tx = timer.run(
                Transaction, etx.raw, height=height, position=position
            )
            # Inputs
            spent_claims, spent_supports, spent_others = timer.run(
                self.split_inputs_into_claims_supports_and_other, tx.inputs
            )
            body_timer.start()
            delete_claim_hashes.update({r.claim_hash for r in spent_claims})
            deleted_claim_names.update({r.normalized for r in spent_claims})
            delete_support_txo_hashes.update({r.txo_hash for r in spent_supports})
            recalculate_claim_hashes.update({r.claim_hash for r in spent_supports})
            delete_others.update(spent_others)
            # Outputs
            for output in tx.outputs:
                if output.is_support:
                    insert_supports.append(output)
                    recalculate_claim_hashes.add(output.claim_hash)
                elif output.script.is_claim_name:
                    insert_claims.append(output)
                    recalculate_claim_hashes.add(output.claim_hash)
                elif output.script.is_update_claim:
                    claim_hash = output.claim_hash
                    update_claims.append(output)
                    recalculate_claim_hashes.add(claim_hash)
            body_timer.stop()

        skip_update_claim_timer = timer.add_timer('skip update of abandoned claims')
        skip_update_claim_timer.start()
        for updated_claim in list(update_claims):
            if updated_claim.ref.hash in delete_others:
                update_claims.remove(updated_claim)
        for updated_claim in update_claims:
            claim_hash = updated_claim.claim_hash
            delete_claim_hashes.discard(claim_hash)
            update_claim_hashes.add(claim_hash)
        skip_update_claim_timer.stop()

        skip_insert_claim_timer = timer.add_timer('skip insertion of abandoned claims')
        skip_insert_claim_timer.start()
        for new_claim in list(insert_claims):
            if new_claim.ref.hash in delete_others:
                if new_claim.claim_hash not in update_claim_hashes:
                    insert_claims.remove(new_claim)
        skip_insert_claim_timer.stop()

        skip_insert_support_timer = timer.add_timer('skip insertion of abandoned supports')
        skip_insert_support_timer.start()
        for new_support in list(insert_supports):
            if new_support.ref.hash in delete_others:
                insert_supports.remove(new_support)
        skip_insert_support_timer.stop()

        expire_timer = timer.add_timer('recording expired claims')
        expire_timer.start()
        for expired in self.get_expiring(height):
            delete_claim_hashes.add(expired.claim_hash)
            deleted_claim_names.add(expired.normalized)
        expire_timer.stop()

        r = timer.run
        r(update_full_text_search, 'before-delete',
          delete_claim_hashes, self.db.cursor(), self.main.first_sync)
        affected_channels = r(self.delete_claims, delete_claim_hashes)
        r(self.delete_supports, delete_support_txo_hashes)
        r(self.insert_claims, insert_claims, header)
        r(self.calculate_reposts, insert_claims)
        r(update_full_text_search, 'after-insert',
          [txo.claim_hash for txo in insert_claims], self.db.cursor(), self.main.first_sync)
        r(update_full_text_search, 'before-update',
          [txo.claim_hash for txo in update_claims], self.db.cursor(), self.main.first_sync)
        r(self.update_claims, update_claims, header)
        r(update_full_text_search, 'after-update',
          [txo.claim_hash for txo in update_claims], self.db.cursor(), self.main.first_sync)
        r(self.validate_channel_signatures, height, insert_claims,
          update_claims, delete_claim_hashes, affected_channels, forward_timer=True)
        r(self.insert_supports, insert_supports)
        r(self.update_claimtrie, height, recalculate_claim_hashes, deleted_claim_names, forward_timer=True)
        for algorithm in self.trending:
            r(algorithm.run, self.db.cursor(), height, daemon_height, recalculate_claim_hashes)
        if not self._fts_synced and self.main.first_sync and height == daemon_height:
            r(first_sync_finished, self.db.cursor())
            self._fts_synced = True


class LBRYLevelDB(LevelDB):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        path = os.path.join(self.env.db_dir, 'claims.db')
        trending = []
        for algorithm_name in self.env.trending_algorithms:
            if algorithm_name in TRENDING_ALGORITHMS:
                trending.append(TRENDING_ALGORITHMS[algorithm_name])
        self.sql = SQLDB(
            self, path,
            self.env.default('BLOCKING_CHANNEL_IDS', '').split(' '),
            self.env.default('FILTERING_CHANNEL_IDS', '').split(' '),
            trending
        )

    def close(self):
        super().close()
        self.sql.close()

    async def _open_dbs(self, *args, **kwargs):
        await super()._open_dbs(*args, **kwargs)
        self.sql.open()
