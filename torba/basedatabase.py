import logging
from typing import List, Union
from operator import itemgetter

import sqlite3
from twisted.internet import defer
from twisted.enterprise import adbapi

import torba.baseaccount

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
        # type: (str, dict) -> tuple[str, List]
        columns, values = [], []
        for column, value in data.items():
            columns.append(column)
            values.append(value)
        sql = "INSERT INTO {} ({}) VALUES ({})".format(
            table, ', '.join(columns), ', '.join(['?'] * len(values))
        )
        return sql, values

    def _update_sql(self, table, data, where, constraints):
        # type: (str, dict) -> tuple[str, List]
        columns, values = [], []
        for column, value in data.items():
            columns.append("{} = ?".format(column))
            values.append(value)
        values.extend(constraints)
        sql = "UPDATE {} SET {} WHERE {}".format(
            table, ', '.join(columns), where
        )
        return sql, values

    @defer.inlineCallbacks
    def query_one_value_list(self, query, params):
        # type: (str, Union[dict,tuple]) -> defer.Deferred[List]
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

    CREATE_PUBKEY_ADDRESS_TABLE = """
        create table if not exists pubkey_address (
            address text primary key,
            account text not null,
            chain integer not null,
            position integer not null,
            pubkey text not null,
            history text,
            used_times integer not null default 0
        );
    """

    CREATE_TX_TABLE = """
        create table if not exists tx (
            txid text primary key,
            raw blob not null,
            height integer not null,
            is_verified boolean not null default 0
        );
    """

    CREATE_TXO_TABLE = """
        create table if not exists txo (
            txoid text primary key,
            txid text references tx,
            address text references pubkey_address,
            position integer not null,
            amount integer not null,
            script blob not null,
            is_reserved boolean not null default 0
        );
    """

    CREATE_TXI_TABLE = """
        create table if not exists txi (
            txid text references tx,
            txoid text references txo,
            address text references pubkey_address
        );
    """

    CREATE_TABLES_QUERY = (
        CREATE_TX_TABLE +
        CREATE_PUBKEY_ADDRESS_TABLE +
        CREATE_TXO_TABLE +
        CREATE_TXI_TABLE
    )

    def txo_to_row(self, tx, address, txo):
        return {
            'txid': sqlite3.Binary(tx.hash),
            'address': sqlite3.Binary(address),
            'position': txo.position,
            'amount': txo.amount,
            'script': sqlite3.Binary(txo.script.source)
        }

    def save_transaction_io(self, save_tx, tx, height, is_verified, address, hash, history):

        def _steps(t):
            if save_tx == 'insert':
                t.execute(*self._insert_sql('tx', {
                    'txhash': sqlite3.Binary(tx.hash),
                    'raw': sqlite3.Binary(tx.raw),
                    'height': height,
                    'is_verified': is_verified
                }))
            elif save_tx == 'update':
                t.execute(*self._update_sql("tx", {
                        'height': height, 'is_verified': is_verified
                    }, 'txhash = ?', (sqlite3.Binary(tx.hash),)
                ))

            existing_txos = list(map(itemgetter(0), t.execute(
                "SELECT position FROM txo WHERE txhash = ?",
                (sqlite3.Binary(tx.hash),)
            ).fetchall()))

            for txo in tx.outputs:
                if txo.index in existing_txos:
                    continue
                if txo.script.is_pay_pubkey_hash and txo.script.values['pubkey_hash'] == hash:
                    t.execute(*self._insert_sql("txo", self.txo_to_row(tx, address, txo)))
                elif txo.script.is_pay_script_hash:
                    # TODO: implement script hash payments
                    print('Database.save_transaction_io: pay script hash is not implemented!')

            existing_txis = [txi[0] for txi in t.execute(
                "SELECT txoid FROM txi WHERE txhash = ? AND address = ?",
                (sqlite3.Binary(tx.hash), sqlite3.Binary(address))).fetchall()]

            for txi in tx.inputs:
                txoid = t.execute(
                    "SELECT txoid FROM txo WHERE txhash = ? AND position = ?",
                    (sqlite3.Binary(txi.output_txhash), txi.output_index)
                ).fetchone()
                if txoid is not None and txoid[0] not in existing_txis:
                    t.execute(*self._insert_sql("txi", {
                        'txhash': sqlite3.Binary(tx.hash),
                        'address': sqlite3.Binary(address),
                        'txoid': txoid[0],
                    }))

            self._set_address_history(t, address, history)

        return self.db.runInteraction(_steps)

    def reserve_spent_outputs(self, txoids, is_reserved=True):
        return self.db.runOperation(
            "UPDATE txo SET is_reserved = ? WHERE txoid IN ({})".format(
                ', '.join(['?']*len(txoids))
            ), [is_reserved]+txoids
        )

    def release_reserved_outputs(self, txoids):
        return self.reserve_spent_outputs(txoids, is_reserved=False)

    def get_txoid_for_txo(self, txo):
        return self.query_one_value(
            "SELECT txoid FROM txo WHERE txhash = ? AND position = ?",
            (sqlite3.Binary(txo.transaction.hash), txo.index)
        )

    @defer.inlineCallbacks
    def get_transaction(self, txhash):
        result = yield self.db.runQuery(
            "SELECT raw, height, is_verified FROM tx WHERE txhash = ?", (sqlite3.Binary(txhash),)
        )
        if result:
            defer.returnValue(result[0])
        else:
            defer.returnValue((None, None, False))

    @defer.inlineCallbacks
    def get_balance_for_account(self, account, **constraints):
        extra_sql = ""
        if constraints:
            extras = []
            for key in constraints.keys():
                col, op = key, '='
                if key.endswith('__not'):
                    col, op = key[:-len('__not')], '!='
                elif key.endswith('__lte'):
                    col, op = key[:-len('__lte')], '<='
                extras.append('{} {} :{}'.format(col, op, key))
            extra_sql = ' AND ' + ' AND '.join(extras)
        values = {'account': sqlite3.Binary(account.public_key.address)}
        values.update(constraints)
        result = yield self.db.runQuery(
            """
            SELECT SUM(amount)
            FROM txo
                JOIN tx ON tx.txhash=txo.txhash
                JOIN pubkey_address ON pubkey_address.address=txo.address
            WHERE
              pubkey_address.account=:account AND
              txoid NOT IN (SELECT txoid FROM txi)
            """+extra_sql, values
        )
        if result:
            defer.returnValue(result[0][0] or 0)
        else:
            defer.returnValue(0)

    @defer.inlineCallbacks
    def get_utxos_for_account(self, account, **constraints):
        extra_sql = ""
        if constraints:
            extra_sql = ' AND ' + ' AND '.join(
                '{} = :{}'.format(c, c) for c in constraints.keys()
            )
        values = {'account': sqlite3.Binary(account.public_key.address)}
        values.update(constraints)
        utxos = yield self.db.runQuery(
            """
            SELECT amount, script, txhash, txo.position, txoid
            FROM txo JOIN pubkey_address ON pubkey_address.address=txo.address
            WHERE account=:account AND txo.is_reserved=0 AND txoid NOT IN (SELECT txoid FROM txi)
            """+extra_sql, values
        )
        output_class = account.ledger.transaction_class.output_class
        defer.returnValue([
            output_class(
                values[0],
                output_class.script_class(values[1]),
                values[2],
                index=values[3],
                txoid=values[4]
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

    @staticmethod
    def _set_address_history(t, address, history):
        t.execute(
            "UPDATE pubkey_address SET history = ?, used_times = ? WHERE address = ?",
            (history, history.count(':')//2, sqlite3.Binary(address))
        )

    def set_address_history(self, address, history):
        return self.db.runInteraction(lambda t: self._set_address_history(t, address, history))

    def get_addresses(self, account, chain, limit=None, max_used_times=None, order_by=None):
        columns = ['account', 'chain', 'position', 'address', 'used_times']
        sql = ["SELECT {} FROM pubkey_address"]

        where = []
        params = {}
        if account is not None:
            params["account"] = account.public_key.address
            where.append("account = :account")
            columns.remove("account")
        if chain is not None:
            params["chain"] = chain
            where.append("chain = :chain")
            columns.remove("chain")
        if max_used_times is not None:
            params["used_times"] = max_used_times
            where.append("used_times <= :used_times")

        if where:
            sql.append("WHERE")
            sql.append(" AND ".join(where))

        if order_by:
            sql.append("ORDER BY {}".format(order_by))

        if limit is not None:
            sql.append("LIMIT {}".format(limit))

        return self.query_dict_value_list(" ".join(sql), columns, params)

    def get_address(self, address):
        return self.query_dict_value(
            "SELECT {} FROM pubkey_address WHERE address = :address",
            ('address', 'account', 'chain', 'position', 'pubkey', 'history', 'used_times'),
            {'address': address}
        )
