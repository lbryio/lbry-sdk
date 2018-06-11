import logging
import sqlite3
from twisted.internet import defer
from twisted.enterprise import adbapi

log = logging.getLogger(__name__)


class SQLiteMixin(object):

    CREATE_TABLES_QUERY = None

    def __init__(self, path):
        self._db_path = path
        self.db = None

    def start(self):
        log.info("connecting to database: %s", self._db_path)
        self.db = adbapi.ConnectionPool(
            'sqlite3', self._db_path, cp_min=1, cp_max=1, check_same_thread=False
        )
        return self.db.runInteraction(
            lambda t: t.executescript(self.CREATE_TABLES_QUERY)
        )

    def stop(self):
        self.db.close()
        return defer.succeed(True)

    def _debug_sql(self, sql):
        """ For use during debugging to execute arbitrary SQL queries without waiting on reactor. """
        conn = self.db.connectionFactory(self.db)
        trans = self.db.transactionFactory(self, conn)
        return trans.execute(sql).fetchall()

    def _insert_sql(self, table, data):
        columns, values = [], []
        for column, value in data.items():
            columns.append(column)
            values.append(value)
        sql = "REPLACE INTO %s (%s) VALUES (%s)".format(
            table, ', '.join(columns), ', '.join(['?'] * len(values))
        )
        return sql, values

    @defer.inlineCallbacks
    def query_one_value_list(self, query, params):
        result = yield self.db.runQuery(query, params)
        if result:
            defer.returnValue([i[0] for i in result])
        else:
            defer.returnValue([])

    @defer.inlineCallbacks
    def query_one_value(self, query, params=None, default=None):
        result = yield self.db.runQuery(query, params)
        if result:
            defer.returnValue(result[0][0])
        else:
            defer.returnValue(default)

    @defer.inlineCallbacks
    def query_dict_value_list(self, query, fields, params=None):
        result = yield self.db.runQuery(query.format(', '.join(fields)), params)
        if result:
            defer.returnValue([dict(zip(fields, r)) for r in result])
        else:
            defer.returnValue([])

    @defer.inlineCallbacks
    def query_dict_value(self, query, fields, params=None, default=None):
        result = yield self.query_dict_value_list(query, fields, params)
        if result:
            defer.returnValue(result[0])
        else:
            defer.returnValue(default)

    def query_count(self, sql, params):
        return self.query_one_value(
            "SELECT count(*) FROM ({})".format(sql), params
        )

    def insert_and_return_id(self, table, data):
        def do_insert(t):
            t.execute(*self._insert_sql(table, data))
            return t.lastrowid
        return self.db.runInteraction(do_insert)


class BaseDatabase(SQLiteMixin):

    CREATE_TX_TABLE = """
        create table if not exists tx (
            txid blob primary key,
            raw blob not null,
            height integer not null,
            is_confirmed boolean not null,
            is_verified boolean not null
        );
    """

    CREATE_PUBKEY_ADDRESS_TABLE = """
        create table if not exists pubkey_address (
            address blob primary key,
            account blob not null,
            chain integer not null,
            position integer not null,
            pubkey blob not null,
            history text,
            used_times integer default 0
        );
    """

    CREATE_TXO_TABLE = """
        create table if not exists txo (
            txoid integer primary key,
            txid blob references tx,
            address blob references pubkey_address,
            position integer not null,
            amount integer not null,
            script blob not null
        );
    """

    CREATE_TXI_TABLE = """
        create table if not exists txi (
            txid blob references tx,
            address blob references pubkey_address,
            txoid integer references txo
        );
    """

    CREATE_TABLES_QUERY = (
        CREATE_TX_TABLE +
        CREATE_PUBKEY_ADDRESS_TABLE +
        CREATE_TXO_TABLE +
        CREATE_TXI_TABLE
    )

    def get_missing_transactions(self, address, txids):
        def _steps(t):
            missing = []
            chunk_size = 100
            for i in range(0, len(txids), chunk_size):
                chunk = txids[i:i + chunk_size]
                t.execute(
                    "SELECT 1 FROM tx WHERE txid=?",
                    (sqlite3.Binary(txid) for txid in chunk)
                )
            if not t.execute("SELECT 1 FROM tx WHERE txid=?", (sqlite3.Binary(tx.id),)).fetchone():
                t.execute(*self._insert_sql('tx', {
                    'txid': sqlite3.Binary(tx.id),
                    'raw': sqlite3.Binary(tx.raw),
                    'height': height,
                    'is_confirmed': is_confirmed,
                    'is_verified': is_verified
                }))
        return self.db.runInteraction(_steps)

    def add_transaction(self, address, tx, height, is_confirmed, is_verified):
        def _steps(t):
            if not t.execute("SELECT 1 FROM tx WHERE txid=?", (sqlite3.Binary(tx.id),)).fetchone():
                t.execute(*self._insert_sql('tx', {
                    'txid': sqlite3.Binary(tx.id),
                    'raw': sqlite3.Binary(tx.raw),
                    'height': height,
                    'is_confirmed': is_confirmed,
                    'is_verified': is_verified
                }))
            t.execute(*self._insert_sql(
                "insert into txo values (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                    sqlite3.Binary(account.public_key.address),
                    sqlite3.Binary(txo.script.values['pubkey_hash']),
                    sqlite3.Binary(txo.txid),
                    txo.index,
                    txo.amount,
                    sqlite3.Binary(txo.script.source),
                    txo.script.is_claim_name,
                    txo.script.is_support_claim,
                    txo.script.is_update_claim
                )

            ))
            txoid = t.execute(
                "select rowid from txo where txid=? and pos=?", (
                    sqlite3.Binary(txi.output_txid), txi.output_index
                )
            ).fetchone()[0]
            t.execute(
                "insert into txi values (?, ?, ?)", (
                    sqlite3.Binary(account.public_key.address),
                    sqlite3.Binary(txi.txid),
                    txoid
                )
            )

        return self.db.runInteraction(_steps)

    @defer.inlineCallbacks
    def has_transaction(self, txid):
        result = yield self.db.runQuery(
            "select rowid from tx where txid=?", (txid,)
        )
        defer.returnValue(bool(result))

    @defer.inlineCallbacks
    def get_balance_for_account(self, account):
        result = yield self.db.runQuery(
            "select sum(amount) from txo where account=:account and rowid not in (select txo from txi where account=:account)",
            {'account': sqlite3.Binary(account.public_key.address)}
        )
        if result:
            defer.returnValue(result[0][0] or 0)
        else:
            defer.returnValue(0)

    @defer.inlineCallbacks
    def get_utxos(self, account, output_class):
        utxos = yield self.db.runQuery(
            """
            SELECT
              amount, script, txid
            FROM txo
            WHERE
              account=:account AND
              txoid NOT IN (SELECT txoid FROM txi WHERE account=:account)
            """,
            {'account': sqlite3.Binary(account.public_key.address)}
        )
        defer.returnValue([
            output_class(
                values[0],
                output_class.script_class(values[1]),
                values[2]
            ) for values in utxos
        ])

    def add_keys(self, account, chain, keys):
        sql = (
            "insert into pubkey_address "
            "(address, account, chain, position, pubkey) "
            "values "
        ) + ', '.join(['(?, ?, ?, ?, ?)'] * len(keys))
        values = []
        for position, pubkey in keys:
            values.append(sqlite3.Binary(pubkey.address))
            values.append(sqlite3.Binary(account.public_key.address))
            values.append(chain)
            values.append(position)
            values.append(sqlite3.Binary(pubkey.pubkey_bytes))
        return self.db.runOperation(sql, values)

    def get_keys(self, account, chain):
        return self.query_one_value_list(
            "SELECT pubkey FROM pubkey_address WHERE account = ? AND chain = ?",
            (sqlite3.Binary(account.public_key.address), chain)
        )

    def get_address_details(self, address):
        return self.query_dict_value(
            "SELECT {} FROM pubkey_address WHERE address = ?",
            ('account', 'chain', 'position'), (sqlite3.Binary(address),)
        )

    def get_addresses(self, account, chain):
        return self.query_one_value_list(
            "SELECT address FROM pubkey_address WHERE account = ? AND chain = ?",
            (sqlite3.Binary(account.public_key.address), chain)
        )

    def get_last_address_index(self, account, chain):
        return self.query_one_value(
            """
            SELECT position FROM pubkey_address 
            WHERE account = ? AND chain = ?
            ORDER BY position DESC LIMIT 1""",
            (sqlite3.Binary(account.public_key.address), chain),
            default=0
        )

    def _usable_address_sql(self, account, chain, exclude_used_times):
        return """
            SELECT address FROM pubkey_address 
            WHERE
              account = :account AND
              chain = :chain AND 
              used_times <= :exclude_used_times
        """, {
            'account': sqlite3.Binary(account.public_key.address),
            'chain': chain,
            'exclude_used_times': exclude_used_times
        }

    def get_usable_addresses(self, account, chain, exclude_used_times=2):
        return self.query_one_value_list(*self._usable_address_sql(
            account, chain, exclude_used_times
        ))

    def get_usable_address_count(self, account, chain, exclude_used_times=2):
        return self.query_count(*self._usable_address_sql(
            account, chain, exclude_used_times
        ))

    def get_address_history(self, address):
        return self.query_one_value(
            "SELECT history FROM pubkey_address WHERE address = ?", (sqlite3.Binary(address),)
        )

    def set_address_status(self, address, status):
        return self.db.runOperation(
            "replace into address_status (address, status) values (?, ?)", (address,status)
        )

