import sqlite3
import struct
from typing import Union, Tuple, Set, List
from binascii import unhexlify

from torba.server.db import DB
from torba.server.util import class_logger
from torba.client.basedatabase import query, constraints_to_sql
from google.protobuf.message import DecodeError

from lbrynet.wallet.transaction import Transaction, Output


class SQLDB:

    TRENDING_BLOCKS = 300  # number of blocks over which to calculate trending

    PRAGMAS = """
        pragma journal_mode=WAL;
    """

    CREATE_TX_TABLE = """
        create table if not exists tx (
            tx_hash bytes primary key,
            raw bytes not null,
            position integer not null,
            height integer not null
        );
    """

    CREATE_CLAIM_TABLE = """
        create table if not exists claim (
            claim_hash bytes primary key,
            tx_hash bytes not null,
            txo_hash bytes not null,
            height integer not null,
            activation_height integer,
            amount integer not null,
            effective_amount integer not null default 0,
            trending_amount integer not null default 0,
            claim_name text not null,
            channel_hash bytes
        );
        create index if not exists claim_tx_hash_idx on claim (tx_hash);
        create index if not exists claim_txo_hash_idx on claim (txo_hash);
        create index if not exists claim_activation_height_idx on claim (activation_height);
        create index if not exists claim_channel_hash_idx on claim (channel_hash);
        create index if not exists claim_claim_name_idx on claim (claim_name);
    """

    CREATE_SUPPORT_TABLE = """
        create table if not exists support (
            txo_hash bytes primary key,
            tx_hash bytes not null,
            claim_hash bytes not null,
            position integer not null,
            height integer not null,
            amount integer not null,
            is_comment bool not null default false
        );
        create index if not exists support_tx_hash_idx on support (tx_hash);
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
            claim_name text primary key,
            claim_hash bytes not null,
            last_take_over_height integer not null
        );
        create index if not exists claimtrie_claim_hash_idx on claimtrie (claim_hash);
    """

    CREATE_TABLES_QUERY = (
        PRAGMAS +
        CREATE_TX_TABLE +
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

    def insert_txs(self, txs: Set[Transaction]):
        if txs:
            self.db.executemany(
                "INSERT INTO tx (tx_hash, raw, position, height) VALUES (?, ?, ?, ?)",
                [(sqlite3.Binary(tx.hash), sqlite3.Binary(tx.raw), tx.position, tx.height) for tx in txs]
            )

    def _upsertable_claims(self, txos: Set[Output]):
        claims, tags = [], []
        for txo in txos:
            tx = txo.tx_ref.tx
            try:
                assert txo.claim_name
            except (AssertionError, UnicodeDecodeError):
                self.logger.exception(f"Could not decode claim name for {tx.id}:{txo.position}.")
                continue
            try:
                claim = txo.claim
                if claim.is_channel:
                    metadata = claim.channel
                else:
                    metadata = claim.stream
            except DecodeError:
                self.logger.exception(f"Could not parse claim protobuf for {tx.id}:{txo.position}.")
                continue
            txo_hash = sqlite3.Binary(txo.ref.hash)
            channel_hash = sqlite3.Binary(claim.signing_channel_hash) if claim.signing_channel_hash else None
            claims.append({
                'claim_hash': sqlite3.Binary(txo.claim_hash),
                'tx_hash': sqlite3.Binary(tx.hash),
                'txo_hash': txo_hash,
                'channel_hash': channel_hash,
                'amount': txo.amount,
                'claim_name': txo.claim_name,
                'height': tx.height
            })
            for tag in metadata.tags:
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
                "INSERT INTO claim (claim_hash, tx_hash, txo_hash, channel_hash, amount, claim_name, height) "
                "VALUES (:claim_hash, :tx_hash, :txo_hash, :channel_hash, :amount, :claim_name, :height) ",
                claims
            )

    def update_claims(self, txos: Set[Output]):
        claims = self._upsertable_claims(txos)
        if claims:
            self.db.executemany(
                "UPDATE claim SET "
                "    tx_hash=:tx_hash, txo_hash=:txo_hash, channel_hash=:channel_hash, "
                "    amount=:amount, height=:height "
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
                sqlite3.Binary(txo.ref.hash), sqlite3.Binary(tx.hash),
                sqlite3.Binary(txo.claim_hash), tx.position, tx.height,
                txo.amount, False
            ))
        if supports:
            self.db.executemany(
                "INSERT INTO support (txo_hash, tx_hash, claim_hash, position, height, amount, is_comment) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", supports
            )

    def delete_other_txos(self, txo_hashes: Set[bytes]):
        if txo_hashes:
            self.execute(*self._delete_sql(
                'support', {'txo_hash__in': [sqlite3.Binary(txo_hash) for txo_hash in txo_hashes]}
            ))

    def delete_dereferenced_transactions(self):
        self.execute("""
            DELETE FROM tx WHERE (
                (SELECT COUNT(*) FROM claim WHERE claim.tx_hash=tx.tx_hash) +
                (SELECT COUNT(*) FROM support WHERE support.tx_hash=tx.tx_hash)
                ) = 0
        """)

    def _make_claims_without_competition_become_controlling(self, height):
        self.execute(f"""
            INSERT INTO claimtrie (claim_name, claim_hash, last_take_over_height)
            SELECT claim.claim_name, claim.claim_hash, {height} FROM claim
                LEFT JOIN claimtrie USING (claim_name)
                WHERE claimtrie.claim_hash IS NULL
                GROUP BY claim.claim_name HAVING COUNT(*) = 1
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
                     WHERE claimtrie.claim_name=claim.claim_name)
                ) / 32 AS INT))
            WHERE activation_height IS NULL
        """)

    def get_overtakings(self):
        return self.execute(f"""
            SELECT winner.claim_name, winner.claim_hash FROM (
                SELECT claim_name, claim_hash, MAX(effective_amount)
                FROM claim GROUP BY claim_name
            ) AS winner JOIN claimtrie USING (claim_name)
            WHERE claimtrie.claim_hash <> winner.claim_hash
        """)

    def _perform_overtake(self, height):
        for overtake in self.get_overtakings():
            self.execute(
                f"UPDATE claim SET activation_height = {height} WHERE claim_name = ?",
                (overtake['claim_name'],)
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

    def get_transactions(self, tx_hashes):
        cur = self.db.cursor()
        cur.execute(*query("SELECT * FROM tx", tx_hash__in=tx_hashes))
        return cur.fetchall()

    def get_claims(self, cols, **constraints):
        if 'is_winning' in constraints:
            constraints['claimtrie.claim_hash__is_not_null'] = ''
            del constraints['is_winning']
        if 'name' in constraints:
            constraints['claim.claim_name__like'] = constraints.pop('name')
        if 'claim_id' in constraints:
            constraints['claim.claim_hash'] = sqlite3.Binary(
                unhexlify(constraints.pop('claim_id'))[::-1]
            )
        if 'channel_id' in constraints:
            constraints['claim.channel_hash'] = sqlite3.Binary(
                unhexlify(constraints.pop('channel_id'))[::-1]
            )
        if 'txid' in constraints:
            tx_hash = unhexlify(constraints.pop('txid'))[::-1]
            if 'nout' in constraints:
                nout = constraints.pop('nout')
                constraints['claim.txo_hash'] = sqlite3.Binary(
                    tx_hash + struct.pack('<I', nout)
                )
            else:
                constraints['claim.tx_hash'] = sqlite3.Binary(tx_hash)
        cur = self.db.cursor()
        cur.execute(*query(
            f"""
            SELECT {cols} FROM claim
            LEFT JOIN claimtrie USING (claim_hash)
            LEFT JOIN claim as channel ON (claim.channel_hash=channel.claim_hash)
            """, **constraints
        ))
        return cur.fetchall()

    def get_claims_count(self, **constraints):
        constraints.pop('offset', None)
        constraints.pop('limit', None)
        constraints.pop('order_by', None)
        count = self.get_claims('count(*)', **constraints)
        return count[0][0]

    SEARCH_PARAMS = {
        'name', 'claim_id', 'txid', 'nout', 'channel_id', 'is_winning', 'limit', 'offset'
    }

    def claim_search(self, constraints) -> Tuple[List, List, int, int]:
        assert set(constraints).issubset(self.SEARCH_PARAMS), \
            f"Search query contains invalid arguments: {set(constraints).difference(self.SEARCH_PARAMS)}"
        total = self.get_claims_count(**constraints)
        constraints['offset'] = abs(constraints.get('offset', 0))
        constraints['limit'] = min(abs(constraints.get('limit', 10)), 50)
        constraints['order_by'] = ["claim.height DESC", "claim.claim_name ASC"]
        txo_rows = self.get_claims(
            """
            claim.txo_hash, channel.txo_hash as channel_txo_hash,
            claim.activation_height, claimtrie.claim_hash as is_winning,
            claim.effective_amount, claim.trending_amount
            """, **constraints
        )
        tx_hashes = set()
        for claim in txo_rows:
            tx_hashes.add(claim['txo_hash'][:32])
            if claim['channel_txo_hash'] is not None:
                tx_hashes.add(claim['channel_txo_hash'][:32])
        tx_rows = self.get_transactions([sqlite3.Binary(h) for h in tx_hashes])
        return tx_rows, txo_rows, constraints['offset'], total

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
        sql.insert_txs(txs)
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

    async def _open_dbs(self, *args):
        await super()._open_dbs(*args)
        self.sql.open()
