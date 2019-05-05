import sqlite3
import struct
from typing import Union, Tuple, Set, List
from binascii import unhexlify

from torba.server.db import DB
from torba.server.util import class_logger
from torba.client.basedatabase import query, constraints_to_sql
from google.protobuf.message import DecodeError

from lbrynet.schema.url import URL, normalize_name
from lbrynet.wallet.transaction import Transaction, Output


class SQLDB:

    TRENDING_BLOCKS = 300  # number of blocks over which to calculate trending

    PRAGMAS = """
        pragma journal_mode=WAL;
    """

    CREATE_CLAIM_TABLE = """
        create table if not exists claim (
            claim_hash bytes primary key,
            normalized text not null,
            claim_name text not null,
            is_channel bool not null,
            txo_hash bytes not null,
            tx_position integer not null,
            height integer not null,
            amount integer not null,
            channel_hash bytes,
            activation_height integer,
            effective_amount integer not null default 0,
            trending_amount integer not null default 0
        );
        create index if not exists claim_normalized_idx on claim (normalized);
        create index if not exists claim_txo_hash_idx on claim (txo_hash);
        create index if not exists claim_channel_hash_idx on claim (channel_hash);
        create index if not exists claim_activation_height_idx on claim (activation_height);
    """

    CREATE_SUPPORT_TABLE = """
        create table if not exists support (
            txo_hash bytes primary key,
            tx_position integer not null,
            height integer not null,
            claim_hash bytes not null,
            amount integer not null
        );
        create index if not exists support_txo_hash_idx on support (txo_hash);
        create index if not exists support_claim_hash_idx on support (claim_hash, height);
    """

    CREATE_TAG_TABLE = """
        create table if not exists tag (
            tag text not null,
            txo_hash bytes not null,
            height integer not null
        );
        create index if not exists tag_tag_idx on tag (tag);
        create index if not exists tag_txo_hash_idx on tag (txo_hash);
        create index if not exists tag_height_idx on tag (height);
    """

    CREATE_CLAIMTRIE_TABLE = """
        create table if not exists claimtrie (
            normalized text primary key,
            claim_hash bytes not null,
            last_take_over_height integer not null
        );
        create index if not exists claimtrie_claim_hash_idx on claimtrie (claim_hash);
    """

    CREATE_TABLES_QUERY = (
        PRAGMAS +
        CREATE_CLAIM_TABLE +
        CREATE_SUPPORT_TABLE +
        CREATE_CLAIMTRIE_TABLE +
        CREATE_TAG_TABLE
    )

    def __init__(self, path):
        self._db_path = path
        self.db = None
        self.logger = class_logger(__name__, self.__class__.__name__)

    def open(self):
        self.db = sqlite3.connect(self._db_path, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(self.CREATE_TABLES_QUERY)

    def close(self):
        self.db.close()

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
            columns.append("{} = ?".format(column))
            values.append(value)
        values.extend(constraints)
        return f"UPDATE {table} SET {', '.join(columns)} WHERE {where}", values

    @staticmethod
    def _delete_sql(table: str, constraints: dict) -> Tuple[str, dict]:
        where, values = constraints_to_sql(constraints)
        return f"DELETE FROM {table} WHERE {where}", values

    def execute(self, *args):
        return self.db.execute(*args)

    def begin(self):
        self.execute('begin;')

    def commit(self):
        self.execute('commit;')

    def _upsertable_claims(self, txos: Set[Output]):
        claims, tags = [], []
        for txo in txos:
            tx = txo.tx_ref.tx

            try:
                assert txo.claim_name
                assert txo.normalized_name
            except (AssertionError, UnicodeDecodeError):
                self.logger.exception(f"Could not decode claim name for {tx.id}:{txo.position}.")
                continue

            txo_hash = sqlite3.Binary(txo.ref.hash)
            claim_record = {
                'claim_hash': sqlite3.Binary(txo.claim_hash),
                'normalized': txo.normalized_name,
                'claim_name': txo.claim_name,
                'is_channel': False,
                'txo_hash': txo_hash,
                'tx_position': tx.position,
                'height': tx.height,
                'amount': txo.amount,
                'channel_hash': None,
            }
            claims.append(claim_record)

            try:
                claim = txo.claim
            except DecodeError:
                self.logger.exception(f"Could not parse claim protobuf for {tx.id}:{txo.position}.")
                continue

            claim_record['is_channel'] = claim.is_channel
            if claim.signing_channel_hash:
                claim_record['channel_hash'] = sqlite3.Binary(claim.signing_channel_hash)
            for tag in claim.message.tags:
                tags.append((tag, txo_hash, tx.height))

        if tags:
            self.db.executemany(
                "INSERT INTO tag (tag, txo_hash, height) VALUES (?, ?, ?)", tags
            )

        return claims

    def insert_claims(self, txos: Set[Output]):
        claims = self._upsertable_claims(txos)
        if claims:
            self.db.executemany(
                "INSERT INTO claim ("
                "   claim_hash, normalized, claim_name, is_channel, txo_hash,"
                "   tx_position, height, amount, channel_hash) "
                "VALUES ("
                "   :claim_hash, :normalized, :claim_name, :is_channel, :txo_hash,"
                "   :tx_position, :height, :amount, :channel_hash) ",
                claims
            )

    def update_claims(self, txos: Set[Output]):
        claims = self._upsertable_claims(txos)
        if claims:
            self.db.executemany(
                "UPDATE claim SET "
                "   is_channel=:is_channel, txo_hash=:txo_hash, tx_position=:tx_position,"
                "   height=:height, amount=:amount, channel_hash=:channel_hash "
                "WHERE claim_hash=:claim_hash;",
                claims
            )

    def clear_claim_metadata(self, txo_hashes: Set[bytes]):
        """ Deletes metadata associated with claim in case of an update or an abandon. """
        if txo_hashes:
            binary_txo_hashes = [sqlite3.Binary(txo_hash) for txo_hash in txo_hashes]
            for table in ('tag',):  # 'language', 'location', etc
                self.execute(*self._delete_sql(table, {'txo_hash__in': binary_txo_hashes}))

    def abandon_claims(self, claim_hashes: Set[bytes]):
        """ Deletes claim supports and from claimtrie in case of an abandon. """
        if claim_hashes:
            binary_claim_hashes = [sqlite3.Binary(claim_hash) for claim_hash in claim_hashes]
            for table in ('claim', 'support', 'claimtrie'):
                self.execute(*self._delete_sql(table, {'claim_hash__in': binary_claim_hashes}))

    def split_inputs_into_claims_and_other(self, txis):
        all = set(txi.txo_ref.hash for txi in txis)
        claims = dict(self.execute(*query(
            "SELECT txo_hash, claim_hash FROM claim",
            txo_hash__in=[sqlite3.Binary(txo_hash) for txo_hash in all]
        )))
        return claims, all-set(claims)

    def insert_supports(self, txos: Set[Output]):
        supports = []
        for txo in txos:
            tx = txo.tx_ref.tx
            supports.append((
                sqlite3.Binary(txo.ref.hash), tx.position, tx.height,
                sqlite3.Binary(txo.claim_hash), txo.amount
            ))
        if supports:
            self.db.executemany(
                "INSERT INTO support ("
                "   txo_hash, tx_position, height, claim_hash, amount"
                ") "
                "VALUES (?, ?, ?, ?, ?)", supports
            )

    def delete_other_txos(self, txo_hashes: Set[bytes]):
        if txo_hashes:
            self.execute(*self._delete_sql(
                'support', {'txo_hash__in': [sqlite3.Binary(txo_hash) for txo_hash in txo_hashes]}
            ))

    def _make_claims_without_competition_become_controlling(self, height):
        self.execute(f"""
            INSERT INTO claimtrie (normalized, claim_hash, last_take_over_height)
            SELECT claim.normalized, claim.claim_hash, {height} FROM claim
                LEFT JOIN claimtrie USING (normalized)
                WHERE claimtrie.claim_hash IS NULL
                GROUP BY claim.normalized HAVING COUNT(*) = 1
        """)
        self.execute(f"""
            UPDATE claim SET activation_height = {height}
            WHERE activation_height IS NULL AND claim_hash IN (
                SELECT claim_hash FROM claimtrie
            )
        """)

    def _update_trending_amount(self, height):
        self.execute(f"""
            UPDATE claim SET
                trending_amount = COALESCE(
                    (SELECT SUM(amount) FROM support WHERE support.claim_hash=claim.claim_hash
                     AND support.height > {height-self.TRENDING_BLOCKS}), 0
                )
        """)

    def _update_effective_amount(self, height):
        self.execute(f"""
            UPDATE claim SET
                effective_amount = claim.amount + COALESCE(
                    (SELECT SUM(amount) FROM support WHERE support.claim_hash=claim.claim_hash), 0
                )
            WHERE activation_height <= {height}
        """)

    def _set_activation_height(self, height):
        self.execute(f"""
            UPDATE claim SET
                activation_height = {height} + min(4032, cast(
                (
                    {height} -
                    (SELECT last_take_over_height FROM claimtrie
                     WHERE claimtrie.normalized=claim.normalized)
                ) / 32 AS INT))
            WHERE activation_height IS NULL
        """)

    def get_overtakings(self):
        return self.execute(f"""
            SELECT winner.normalized, winner.claim_hash FROM (
                SELECT normalized, claim_hash, MAX(effective_amount)
                FROM claim GROUP BY normalized
            ) AS winner JOIN claimtrie USING (normalized)
            WHERE claimtrie.claim_hash <> winner.claim_hash
        """)

    def _perform_overtake(self, height):
        for overtake in self.get_overtakings():
            self.execute(
                f"UPDATE claim SET activation_height = {height} WHERE normalized = ? "
                f"AND (activation_height IS NULL OR activation_height > {height})",
                (overtake['normalized'],)
            )
            self.execute(
                f"UPDATE claimtrie SET claim_hash = ?, last_take_over_height = {height}",
                (sqlite3.Binary(overtake['claim_hash']),)
            )

    def update_claimtrie(self, height):
        self._make_claims_without_competition_become_controlling(height)
        self._update_trending_amount(height)
        self._update_effective_amount(height)
        self._set_activation_height(height)
        self._perform_overtake(height)
        self._update_effective_amount(height)
        self._perform_overtake(height)

    def get_claims(self, cols, **constraints):
        if 'is_controlling' in constraints:
            if {'sequence', 'amount_order'}.isdisjoint(constraints):
                constraints['claimtrie.claim_hash__is_not_null'] = ''
            del constraints['is_controlling']
        if 'sequence' in constraints:
            constraints['order_by'] = 'claim.activation_height ASC'
            constraints['offset'] = int(constraints.pop('sequence')) - 1
            constraints['limit'] = 1
        if 'amount_order' in constraints:
            constraints['order_by'] = 'claim.effective_amount DESC'
            constraints['offset'] = int(constraints.pop('amount_order')) - 1
            constraints['limit'] = 1

        if 'claim_id' in constraints:
            constraints['claim.claim_hash'] = sqlite3.Binary(
                unhexlify(constraints.pop('claim_id'))[::-1]
            )
        if 'name' in constraints:
            constraints['claim.normalized'] = normalize_name(constraints.pop('name'))

        if 'channel' in constraints:
            url = URL.parse(constraints.pop('channel'))
            if url.channel.claim_id:
                constraints['channel_id'] = url.channel.claim_id
            else:
                constraints['channel_name'] = url.channel.name
        if 'channel_id' in constraints:
            constraints['channel_hash'] = unhexlify(constraints.pop('channel_id'))[::-1]
        if 'channel_hash' in constraints:
            constraints['channel.claim_hash'] = sqlite3.Binary(constraints.pop('channel_hash'))
        if 'channel_name' in constraints:
            constraints['channel.normalized'] = normalize_name(constraints.pop('channel_name'))

        if 'txid' in constraints:
            tx_hash = unhexlify(constraints.pop('txid'))[::-1]
            nout = constraints.pop('nout', 0)
            constraints['claim.txo_hash'] = sqlite3.Binary(
                tx_hash + struct.pack('<I', nout)
            )
        return self.db.execute(*query(
            f"""
            SELECT {cols} FROM claim
            LEFT JOIN claimtrie USING (claim_hash)
            LEFT JOIN claim as channel ON (claim.channel_hash=channel.claim_hash)
            """, **constraints
        )).fetchall()

    def get_claims_count(self, **constraints):
        constraints.pop('offset', None)
        constraints.pop('limit', None)
        constraints.pop('order_by', None)
        count = self.get_claims('count(*)', **constraints)
        return count[0][0]

    def _search(self, **constraints):
        return self.get_claims(
            """
            claimtrie.claim_hash as is_controlling,
            claim.claim_hash, claim.txo_hash, claim.height,
            claim.activation_height, claim.effective_amount, claim.trending_amount,
            channel.txo_hash as channel_txo_hash, channel.height as channel_height,
            channel.activation_height as channel_activation_height,
            channel.effective_amount as channel_effective_amount,
            channel.trending_amount as channel_trending_amount,
            CASE WHEN claim.is_channel=1 THEN (
                SELECT COUNT(*) FROM claim as claim_in_channel
                WHERE claim_in_channel.channel_hash=claim.claim_hash
             ) ELSE 0 END AS claims_in_channel
            """, **constraints
        )

    SEARCH_PARAMS = {
        'name', 'claim_id', 'txid', 'nout',
        'channel', 'channel_id', 'channel_name',
        'is_controlling', 'limit', 'offset'
    }

    def search(self, constraints) -> Tuple[List, int, int]:
        assert set(constraints).issubset(self.SEARCH_PARAMS), \
            f"Search query contains invalid arguments: {set(constraints).difference(self.SEARCH_PARAMS)}"
        total = self.get_claims_count(**constraints)
        constraints['offset'] = abs(constraints.get('offset', 0))
        constraints['limit'] = min(abs(constraints.get('limit', 10)), 50)
        constraints['order_by'] = ["claim.height DESC", "claim.normalized ASC"]
        txo_rows = self._search(**constraints)
        return txo_rows, constraints['offset'], total

    def resolve(self, urls) -> List:
        result = []
        for raw_url in urls:
            try:
                url = URL.parse(raw_url)
            except ValueError as e:
                result.append(e)
                continue
            channel = None
            if url.has_channel:
                matches = self._search(is_controlling=True, **url.channel.to_dict())
                if matches:
                    channel = matches[0]
                else:
                    result.append(LookupError(f'Could not find channel in "{raw_url}".'))
                    continue
            if url.has_stream:
                query = url.stream.to_dict()
                if channel is not None:
                    query['channel_hash'] = channel['claim_hash']
                matches = self._search(is_controlling=True, **query)
                if matches:
                    result.append(matches[0])
                else:
                    result.append(LookupError(f'Could not find stream in "{raw_url}".'))
                    continue
            else:
                result.append(channel)
        return result

    def advance_txs(self, height, all_txs):
        sql, txs = self, set()
        abandon_claim_hashes, stale_claim_metadata_txo_hashes = set(), set()
        insert_claims, update_claims = set(), set()
        delete_txo_hashes, insert_supports = set(), set()
        for position, (etx, txid) in enumerate(all_txs):
            tx = Transaction(etx.serialize(), height=height, position=position)
            claim_abandon_map, delete_txo_hashes = sql.split_inputs_into_claims_and_other(tx.inputs)
            stale_claim_metadata_txo_hashes.update(claim_abandon_map)
            for output in tx.outputs:
                if output.is_support:
                    txs.add(tx)
                    insert_supports.add(output)
                elif output.script.is_claim_name:
                    txs.add(tx)
                    insert_claims.add(output)
                elif output.script.is_update_claim:
                    txs.add(tx)
                    update_claims.add(output)
                    # don't abandon update claims (removes supports & removes from claimtrie)
                    for txo_hash, input_claim_hash in claim_abandon_map.items():
                        if output.claim_hash == input_claim_hash:
                            del claim_abandon_map[txo_hash]
                            break
            abandon_claim_hashes.update(claim_abandon_map.values())
        sql.abandon_claims(abandon_claim_hashes)
        sql.clear_claim_metadata(stale_claim_metadata_txo_hashes)
        sql.delete_other_txos(delete_txo_hashes)
        sql.insert_claims(insert_claims)
        sql.update_claims(update_claims)
        sql.insert_supports(insert_supports)
        sql.update_claimtrie(height)


class LBRYDB(DB):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sql = SQLDB('claims.db')

    def close(self):
        super().close()
        self.sql.close()

    async def _open_dbs(self, *args, **kwargs):
        await super()._open_dbs(*args, **kwargs)
        self.sql.open()
