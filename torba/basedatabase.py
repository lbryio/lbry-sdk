import logging
import os
import sqlite3
from twisted.internet import defer
from twisted.enterprise import adbapi

log = logging.getLogger(__name__)


class BaseSQLiteWalletStorage(object):

    CREATE_TX_TABLE = """
        create table if not exists tx (
            txid blob primary key,
            raw blob not null,
            height integer not null,
            is_confirmed boolean not null,
            is_verified boolean not null
        );
        create table if not exists address_status (
            address blob not null,
            status text not null
        );
    """

    CREATE_TXO_TABLE = """
        create table if not exists txo (
            txoid integer primary key,
            account blob not null,
            address blob not null,
            txid blob references tx,
            pos integer not null,
            amount integer not null,
            script blob not null
        );
    """

    CREATE_TXI_TABLE = """
        create table if not exists txi (
            account blob not null,
            txid blob references tx,
            txoid integer references txo
        );
    """

    CREATE_TABLES_QUERY = (
        CREATE_TX_TABLE +
        CREATE_TXO_TABLE +
        CREATE_TXI_TABLE
    )

    def __init__(self, ledger):
        self._db_path = os.path.join(ledger.path, "blockchain.db")
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

    def add_transaction(self, tx, height, is_confirmed, is_verified):
        return self.run_and_return_id(
            "insert into tx values (?, ?, ?, ?, ?)",
            sqlite3.Binary(tx.id),
            sqlite3.Binary(tx.raw),
            height,
            is_confirmed,
            is_verified
        )

    @defer.inlineCallbacks
    def has_transaction(self, txid):
        result = yield self.db.runQuery(
            "select rowid from tx where txid=?", (txid,)
        )
        defer.returnValue(bool(result))

    def add_tx_output(self, account, txo):
        return self.db.runOperation(
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
        )

    def add_tx_input(self, account, txi):
        def _ops(t):
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
        return self.db.runInteraction(_ops)

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

    def get_used_addresses(self, account):
        return self.db.runQuery(
            """
            SELECT
              txios.address,
              sum(txios.used_count) as total
            FROM
             (SELECT address, count(*) as used_count FROM txo
                  WHERE account=:account GROUP BY address
                UNION
              SELECT address, count(*) as used_count FROM txi NATURAL JOIN txo
                  WHERE account=:account GROUP BY address) AS txios
            GROUP BY txios.address
            ORDER BY total
            """, {'account': sqlite3.Binary(account.public_key.address)}
        )

    @defer.inlineCallbacks
    def get_earliest_block_height_for_address(self, address):
        result = yield self.db.runQuery(
            """
            SELECT
              height
            FROM
             (SELECT DISTINCT height FROM txi NATURAL JOIN txo NATURAL JOIN tx WHERE address=:address
                UNION
              SELECT DISTINCT height FROM txo NATURAL JOIN tx WHERE address=:address) AS txios
            ORDER BY height LIMIT 1
            """, {'address': sqlite3.Binary(address)}
        )
        if result:
            defer.returnValue(result[0][0])
        else:
            defer.returnValue(None)

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

    @defer.inlineCallbacks
    def get_address_status(self, address):
        result = yield self.db.runQuery(
            "select status from address_status where address=?", (address,)
        )
        if result:
            defer.returnValue(result[0][0])
        else:
            defer.returnValue(None)

    def set_address_status(self, address, status):
        return self.db.runOperation(
            "replace into address_status (address, status) values (?, ?)", (address,status)
        )
