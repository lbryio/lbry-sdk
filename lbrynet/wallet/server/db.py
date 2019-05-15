import sqlite3
import struct
from typing import Union, Tuple, Set, List
from binascii import unhexlify

from torba.server.db import DB
from torba.server.util import class_logger
from torba.client.basedatabase import query, constraints_to_sql

from lbrynet.schema.url import URL, normalize_name
from lbrynet.wallet.transaction import Transaction, Output


ATTRIBUTE_ARRAY_MAX_LENGTH = 100


def _apply_constraints_for_array_attributes(constraints, attr):
    any_items = constraints.pop(f'any_{attr}s', [])[:ATTRIBUTE_ARRAY_MAX_LENGTH]
    if any_items:
        constraints.update({
            f'$any_{attr}{i}': item for i, item in enumerate(any_items)
        })
        values = ', '.join(
            f':$any_{attr}{i}' for i in range(len(any_items))
        )
        constraints[f'claim.txo_hash__in#_any_{attr}'] = f"""
            SELECT DISTINCT txo_hash FROM {attr} WHERE {attr} IN ({values})
        """

    all_items = constraints.pop(f'all_{attr}s', [])[:ATTRIBUTE_ARRAY_MAX_LENGTH]
    if all_items:
        constraints[f'$all_{attr}_count'] = len(all_items)
        constraints.update({
            f'$all_{attr}{i}': item for i, item in enumerate(all_items)
        })
        values = ', '.join(
            f':$all_{attr}{i}' for i in range(len(all_items))
        )
        constraints[f'claim.txo_hash__in#_all_{attr}'] = f"""
            SELECT txo_hash FROM {attr} WHERE {attr} IN ({values})
            GROUP BY txo_hash HAVING COUNT({attr}) = :$all_{attr}_count
        """

    not_items = constraints.pop(f'not_{attr}s', [])[:ATTRIBUTE_ARRAY_MAX_LENGTH]
    if not_items:
        constraints.update({
            f'$not_{attr}{i}': item for i, item in enumerate(not_items)
        })
        values = ', '.join(
            f':$not_{attr}{i}' for i in range(len(not_items))
        )
        constraints[f'claim.txo_hash__not_in#_not_{attr}'] = f"""
            SELECT DISTINCT txo_hash FROM {attr} WHERE {attr} IN ({values})
        """


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
            support_amount integer not null default 0,
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
            claim_hash bytes not null,
            height integer not null
        );
        create index if not exists tag_tag_idx on tag (tag);
        create index if not exists tag_claim_hash_idx on tag (claim_hash);
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

    def __init__(self, main, path):
        self.main = main
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

    def _upsertable_claims(self, txos: Set[Output], clear_first=False):
        claim_hashes, claims, tags = [], [], []
        for txo in txos:
            tx = txo.tx_ref.tx

            try:
                assert txo.claim_name
                assert txo.normalized_name
            except:
                #self.logger.exception(f"Could not decode claim name for {tx.id}:{txo.position}.")
                continue

            claim_hash = sqlite3.Binary(txo.claim_hash)
            claim_hashes.append(claim_hash)
            claim_record = {
                'claim_hash': claim_hash,
                'normalized': txo.normalized_name,
                'claim_name': txo.claim_name,
                'is_channel': False,
                'txo_hash': sqlite3.Binary(txo.ref.hash),
                'tx_position': tx.position,
                'height': tx.height,
                'amount': txo.amount,
                'channel_hash': None,
            }
            claims.append(claim_record)

            try:
                claim = txo.claim
            except:
                #self.logger.exception(f"Could not parse claim protobuf for {tx.id}:{txo.position}.")
                continue

            claim_record['is_channel'] = claim.is_channel
            if claim.signing_channel_hash:
                claim_record['channel_hash'] = sqlite3.Binary(claim.signing_channel_hash)
            for tag in claim.message.tags:
                tags.append((tag, claim_hash, tx.height))

        if clear_first:
            self._clear_claim_metadata(claim_hashes)

        if tags:
            self.db.executemany(
                "INSERT INTO tag (tag, claim_hash, height) VALUES (?, ?, ?)", tags
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
        claims = self._upsertable_claims(txos, clear_first=True)
        if claims:
            self.db.executemany(
                "UPDATE claim SET "
                "   is_channel=:is_channel, txo_hash=:txo_hash, tx_position=:tx_position,"
                "   height=:height, amount=:amount, channel_hash=:channel_hash "
                "WHERE claim_hash=:claim_hash;",
                claims
            )

    def delete_claims(self, claim_hashes: Set[bytes]):
        """ Deletes claim supports and from claimtrie in case of an abandon. """
        if claim_hashes:
            binary_claim_hashes = [sqlite3.Binary(claim_hash) for claim_hash in claim_hashes]
            for table in ('claim', 'support', 'claimtrie'):
                self.execute(*self._delete_sql(table, {'claim_hash__in': binary_claim_hashes}))
            self._clear_claim_metadata(binary_claim_hashes)

    def _clear_claim_metadata(self, binary_claim_hashes: List[sqlite3.Binary]):
        if binary_claim_hashes:
            for table in ('tag',):  # 'language', 'location', etc
                self.execute(*self._delete_sql(table, {'claim_hash__in': binary_claim_hashes}))

    def split_inputs_into_claims_supports_and_other(self, txis):
        txo_hashes = set(txi.txo_ref.hash for txi in txis)
        claims = dict(self.execute(*query(
            "SELECT txo_hash, claim_hash FROM claim",
            txo_hash__in=[sqlite3.Binary(txo_hash) for txo_hash in txo_hashes]
        )))
        txo_hashes -= set(claims)
        supports = {}
        if txo_hashes:
            supports = dict(self.execute(*query(
                "SELECT txo_hash, claim_hash FROM support",
                txo_hash__in=[sqlite3.Binary(txo_hash) for txo_hash in txo_hashes]
            )))
            txo_hashes -= set(supports)
        return claims, supports, txo_hashes

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

    def delete_supports(self, txo_hashes: Set[bytes]):
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

    def _update_trending_amount(self, height):
        self.execute(f"""
            UPDATE claim SET
                trending_amount = COALESCE(
                    (SELECT SUM(amount) FROM support WHERE support.claim_hash=claim.claim_hash
                     AND support.height > {height-self.TRENDING_BLOCKS}), 0
                )
        """)

    def _update_support_amount(self, claim_hashes):
        if claim_hashes:
            self.execute(f"""
                UPDATE claim SET
                    support_amount = COALESCE(
                        (SELECT SUM(amount) FROM support WHERE support.claim_hash=claim.claim_hash), 0
                    )
                WHERE claim_hash IN ({','.join('?' for _ in claim_hashes)})
            """, [sqlite3.Binary(claim_hash) for claim_hash in claim_hashes])

    def _update_effective_amount(self, height, claim_hashes=None):
        sql = f"""
        UPDATE claim SET effective_amount = claim.amount + claim.support_amount
        WHERE activation_height = {height}
        """
        if claim_hashes:
            self.execute(
                f"{sql} OR (claim_hash IN ({','.join('?' for _ in claim_hashes)}) AND activation_height <= {height})",
                [sqlite3.Binary(claim_hash) for claim_hash in claim_hashes]
            )
        else:
            self.execute(sql)

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
                f"UPDATE claimtrie SET claim_hash = ?, last_take_over_height = {height} WHERE normalized = ?",
                (sqlite3.Binary(overtake['claim_hash']), overtake['normalized'])
            )

    def _copy(self, height):
        if height > 50:
            self.execute(f"DROP TABLE claimtrie{height-50}")
        self.execute(f"CREATE TABLE claimtrie{height} AS SELECT * FROM claimtrie")

    def update_claimtrie(self, height, removed_claims, new_claims, recalc_claims, timer):
        r = timer.run
        r(self._make_claims_without_competition_become_controlling, height)
        r(self._update_support_amount, recalc_claims)
        r(self._update_effective_amount, height, recalc_claims)
        if not self.main.first_sync:
            r(self._update_trending_amount, height)
        r(self._perform_overtake, height)
        r(self._update_effective_amount, height)
        r(self._perform_overtake, height)
        #r(self._copy, height)

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

        _apply_constraints_for_array_attributes(constraints, 'tag')
        _apply_constraints_for_array_attributes(constraints, 'language')
        _apply_constraints_for_array_attributes(constraints, 'location')

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
        'any_tags', 'all_tags', 'not_tags',
        'any_locations', 'all_locations', 'not_locations',
        'any_languages', 'all_languages', 'not_languages',
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

    def advance_txs(self, height, all_txs, timer):
        body_timer = timer.add_timer('body')
        body_timer.start()
        insert_claims = set()
        update_claims = set()
        delete_claims = set()
        recalc_claims = set()
        insert_supports = set()
        delete_supports = set()
        body_timer.stop()
        for position, (etx, txid) in enumerate(all_txs):
            tx = timer.run(
                Transaction, etx.serialize(), height=height, position=position
            )
            spent_claims, spent_supports, spent_other = timer.run(
                self.split_inputs_into_claims_supports_and_other, tx.inputs
            )
            body_timer.start()
            delete_claims.update(spent_claims.values())
            recalc_claims.update(spent_supports.values())
            delete_supports.update(spent_supports)
            for output in tx.outputs:
                if output.is_support:
                    insert_supports.add(output)
                    recalc_claims.add(output.claim_hash)
                elif output.script.is_claim_name:
                    insert_claims.add(output)
                    recalc_claims.add(output.claim_hash)
                elif output.script.is_update_claim:
                    claim_hash = output.claim_hash
                    if claim_hash in delete_claims:
                        delete_claims.remove(claim_hash)
                    update_claims.add(output)
                    recalc_claims.add(claim_hash)
            body_timer.stop()
        r = timer.run
        r(self.delete_claims, delete_claims)
        r(self.delete_supports, delete_supports)
        r(self.insert_claims, insert_claims)
        r(self.update_claims, update_claims)
        r(self.insert_supports, insert_supports)
        r(self.update_claimtrie, height, delete_claims, insert_claims, recalc_claims, forward_timer=True)


class LBRYDB(DB):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sql = SQLDB(self, 'claims.db')

    def close(self):
        super().close()
        self.sql.close()

    async def _open_dbs(self, *args, **kwargs):
        await super()._open_dbs(*args, **kwargs)
        self.sql.open()
