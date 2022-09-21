import sys
import os
import unittest
import sqlite3
import tempfile
import asyncio
from concurrent.futures.thread import ThreadPoolExecutor

from lbry.wallet import (
    Wallet, Account, Ledger, Database, Headers, Transaction, Input
)
from lbry.wallet.constants import COIN
from lbry.wallet.database import query, interpolate, constraints_to_sql, AIOSQLite
from lbry.crypto.hash import sha256
from lbry.testcase import AsyncioTestCase

from tests.unit.wallet.test_transaction import get_output, NULL_HASH


class TestAIOSQLite(AsyncioTestCase):
    async def asyncSetUp(self):
        self.db = await AIOSQLite.connect(':memory:')
        await self.db.executescript("""
        pragma foreign_keys=on;
        create table parent (id integer primary key, name);
        create table child  (id integer primary key, parent_id references parent);
        """)
        await self.db.execute("insert into parent values (1, 'test')")
        await self.db.execute("insert into child values (2, 1)")

    @staticmethod
    def delete_item(transaction):
        transaction.execute('delete from parent where id=1')

    async def test_foreign_keys_integrity_error(self):
        self.assertListEqual([(1, 'test')], await self.db.execute_fetchall("select * from parent"))

        with self.assertRaises(sqlite3.IntegrityError):
            await self.db.run(self.delete_item)
        self.assertListEqual([(1, 'test')], await self.db.execute_fetchall("select * from parent"))

        await self.db.executescript("pragma foreign_keys=off;")

        await self.db.run(self.delete_item)
        self.assertListEqual([], await self.db.execute_fetchall("select * from parent"))

    async def test_run_without_foreign_keys(self):
        self.assertListEqual([(1, 'test')], await self.db.execute_fetchall("select * from parent"))
        await self.db.run_with_foreign_keys_disabled(self.delete_item)
        self.assertListEqual([], await self.db.execute_fetchall("select * from parent"))

    async def test_integrity_error_when_foreign_keys_disabled_and_skipped(self):
        await self.db.executescript("pragma foreign_keys=off;")
        self.assertListEqual([(1, 'test')], await self.db.execute_fetchall("select * from parent"))
        with self.assertRaises(sqlite3.IntegrityError):
            await self.db.run_with_foreign_keys_disabled(self.delete_item)
        self.assertListEqual([(1, 'test')], await self.db.execute_fetchall("select * from parent"))


class TestQueryBuilder(unittest.TestCase):

    def test_dot(self):
        self.assertTupleEqual(
            constraints_to_sql({'txo.position': 18}),
            ('txo.position = :txo_position0', {'txo_position0': 18})
        )
        self.assertTupleEqual(
            constraints_to_sql({'txo.position#6': 18}),
            ('txo.position = :txo_position6', {'txo_position6': 18})
        )

    def test_any(self):
        self.assertTupleEqual(
            constraints_to_sql({
                'ages__any': {
                    'txo.age__gt': 18,
                    'txo.age__lt': 38
                }
            }),
            ('(txo.age > :ages__any0_txo_age__gt0 OR txo.age < :ages__any0_txo_age__lt0)', {
                'ages__any0_txo_age__gt0': 18,
                'ages__any0_txo_age__lt0': 38
            })
        )

    def test_in(self):
        self.assertTupleEqual(
            constraints_to_sql({'txo.age__in#2': [18, 38]}),
            ('txo.age IN (:txo_age__in2_0, :txo_age__in2_1)', {
                'txo_age__in2_0': 18,
                'txo_age__in2_1': 38
            })
        )
        self.assertTupleEqual(
            constraints_to_sql({'txo.name__in': ('abc123', 'def456')}),
            ('txo.name IN (:txo_name__in0_0, :txo_name__in0_1)', {
                'txo_name__in0_0': 'abc123',
                'txo_name__in0_1': 'def456'
            })
        )
        self.assertTupleEqual(
            constraints_to_sql({'txo.name__in': {'abc123'}}),
            ('txo.name = :txo_name__in0', {
                'txo_name__in0': 'abc123',
            })
        )
        self.assertTupleEqual(
            constraints_to_sql({'txo.age__in': 'SELECT age from ages_table'}),
            ('txo.age IN (SELECT age from ages_table)', {})
        )

    def test_not_in(self):
        self.assertTupleEqual(
            constraints_to_sql({'txo.age__not_in': [18, 38]}),
            ('txo.age NOT IN (:txo_age__not_in0_0, :txo_age__not_in0_1)', {
                'txo_age__not_in0_0': 18,
                'txo_age__not_in0_1': 38
            })
        )
        self.assertTupleEqual(
            constraints_to_sql({'txo.name__not_in': ('abc123', 'def456')}),
            ('txo.name NOT IN (:txo_name__not_in0_0, :txo_name__not_in0_1)', {
                'txo_name__not_in0_0': 'abc123',
                'txo_name__not_in0_1': 'def456'
            })
        )
        self.assertTupleEqual(
            constraints_to_sql({'txo.name__not_in': ('abc123',)}),
            ('txo.name != :txo_name__not_in0', {
                'txo_name__not_in0': 'abc123',
            })
        )
        self.assertTupleEqual(
            constraints_to_sql({'txo.age__not_in': 'SELECT age from ages_table'}),
            ('txo.age NOT IN (SELECT age from ages_table)', {})
        )

    def test_in_invalid(self):
        with self.assertRaisesRegex(ValueError, 'list, set or string'):
            constraints_to_sql({'ages__in': 9})

    def test_query(self):
        self.assertTupleEqual(
            query("select * from foo"),
            ("select * from foo", {})
        )
        self.assertTupleEqual(
            query(
                "select * from foo",
                a__not='b', b__in='select * from blah where c=:$c',
                d__any={'one__like': 'o', 'two': 2}, limit=10, order_by='b', **{'$c': 3}),
            (
                "select * from foo WHERE a != :a__not0 AND "
                "b IN (select * from blah where c=:$c) AND "
                "(one LIKE :d__any0_one__like0 OR two = :d__any0_two0) ORDER BY b LIMIT 10",
                {'a__not0': 'b', 'd__any0_one__like0': 'o', 'd__any0_two0': 2, '$c': 3}
            )
        )

    def test_query_order_by(self):
        self.assertTupleEqual(
            query("select * from foo", order_by='foo'),
            ("select * from foo ORDER BY foo", {})
        )
        self.assertTupleEqual(
            query("select * from foo", order_by=['foo', 'bar']),
            ("select * from foo ORDER BY foo, bar", {})
        )
        with self.assertRaisesRegex(ValueError, 'order_by must be string or list'):
            query("select * from foo", order_by={'foo': 'bar'})

    def test_query_limit_offset(self):
        self.assertTupleEqual(
            query("select * from foo", limit=10),
            ("select * from foo LIMIT 10", {})
        )
        self.assertTupleEqual(
            query("select * from foo", offset=10),
            ("select * from foo OFFSET 10", {})
        )
        self.assertTupleEqual(
            query("select * from foo", limit=20, offset=10),
            ("select * from foo LIMIT 20 OFFSET 10", {})
        )

    def test_query_interpolation(self):
        self.maxDiff = None
        # tests that interpolation replaces longer keys first
        self.assertEqual(
            interpolate(*query(
                "select * from foo",
                a__not='b', b__in='select * from blah where c=:$c',
                d__any={'one__like': 'o', 'two': 2},
                a0=3, a00=1, a00a=2, a00aa=4,  # <-- breaks without correct interpolation key order
                ahash=sha256(b'hello world'),
                limit=10, order_by='b', **{'$c': 3})
            ),
            "select * from foo WHERE a != 'b' AND "
            "b IN (select * from blah where c=3) AND "
            "(one LIKE 'o' OR two = 2) AND "
            "a0 = 3 AND a00 = 1 AND a00a = 2 AND a00aa = 4 "
            "AND ahash = X'b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9' "
            "ORDER BY b LIMIT 10"
        )


class TestQueries(AsyncioTestCase):

    async def asyncSetUp(self):
        self.ledger = Ledger({
            'db': Database(':memory:'),
            'headers': Headers(':memory:')
        })
        await self.ledger.headers.open()
        self.wallet = Wallet()
        await self.ledger.db.open()

    async def asyncTearDown(self):
        await self.ledger.db.close()

    async def create_account(self, wallet=None):
        account = Account.generate(self.ledger, wallet or self.wallet)
        await account.ensure_address_gap()
        return account

    async def create_tx_from_nothing(self, my_account, height):
        to_address = await my_account.receiving.get_or_create_usable_address()
        to_hash = Ledger.address_to_hash160(to_address)
        tx = Transaction(height=height, is_verified=True) \
            .add_inputs([self.txi(self.txo(1, sha256(str(height).encode())))]) \
            .add_outputs([self.txo(1, to_hash)])
        await self.ledger.db.insert_transaction(tx)
        await self.ledger.db.save_transaction_io(tx, to_address, to_hash, '')
        return tx

    async def create_tx_from_txo(self, txo, to_account, height):
        from_hash = txo.script.values['pubkey_hash']
        from_address = self.ledger.hash160_to_address(from_hash)
        to_address = await to_account.receiving.get_or_create_usable_address()
        to_hash = Ledger.address_to_hash160(to_address)
        tx = Transaction(height=height, is_verified=True) \
            .add_inputs([self.txi(txo)]) \
            .add_outputs([self.txo(1, to_hash)])
        await self.ledger.db.insert_transaction(tx)
        await self.ledger.db.save_transaction_io(tx, from_address, from_hash, '')
        await self.ledger.db.save_transaction_io(tx, to_address, to_hash, '')
        return tx

    async def create_tx_to_nowhere(self, txo, height):
        from_hash = txo.script.values['pubkey_hash']
        from_address = self.ledger.hash160_to_address(from_hash)
        to_hash = NULL_HASH
        tx = Transaction(height=height, is_verified=True) \
            .add_inputs([self.txi(txo)]) \
            .add_outputs([self.txo(1, to_hash)])
        await self.ledger.db.insert_transaction(tx)
        await self.ledger.db.save_transaction_io(tx, from_address, from_hash, '')
        return tx

    def txo(self, amount, address):
        return get_output(int(amount*COIN), address)

    def txi(self, txo):
        return Input.spend(txo)

    async def test_large_tx_doesnt_hit_variable_limits(self):
        # SQLite is usually compiled with 999 variables limit: https://www.sqlite.org/limits.html
        # This can be removed when there is a better way. See: https://github.com/lbryio/lbry-sdk/issues/2281
        fetchall = self.ledger.db.db.execute_fetchall

        def check_parameters_length(sql, parameters, read_only=False):
            self.assertLess(len(parameters or []), 999)
            return fetchall(sql, parameters, read_only)

        self.ledger.db.db.execute_fetchall = check_parameters_length
        account = await self.create_account()
        tx = await self.create_tx_from_nothing(account, 0)
        for height in range(1, 1200):
            tx = await self.create_tx_from_txo(tx.outputs[0], account, height=height)
        variable_limit = self.ledger.db.MAX_QUERY_VARIABLES
        for limit in range(variable_limit - 2, variable_limit + 2):
            txs = await self.ledger.get_transactions(
                accounts=self.wallet.accounts, limit=limit, order_by='height asc')
            self.assertEqual(len(txs), limit)
            inputs, outputs, last_tx = set(), set(), txs[0]
            for tx in txs[1:]:
                self.assertEqual(len(tx.inputs), 1)
                self.assertEqual(tx.inputs[0].txo_ref.tx_ref.id, last_tx.id)
                self.assertEqual(len(tx.outputs), 1)
                last_tx = tx

    async def test_queries(self):
        wallet1 = Wallet()
        account1 = await self.create_account(wallet1)
        self.assertEqual(26, await self.ledger.db.get_address_count(accounts=[account1]))
        wallet2 = Wallet()
        account2 = await self.create_account(wallet2)
        account3 = await self.create_account(wallet2)
        self.assertEqual(26, await self.ledger.db.get_address_count(accounts=[account2]))

        self.assertEqual(0, await self.ledger.db.get_transaction_count(accounts=[account1, account2, account3]))
        self.assertEqual(0, await self.ledger.db.get_utxo_count())
        self.assertListEqual([], await self.ledger.db.get_utxos())
        self.assertEqual(0, await self.ledger.db.get_txo_count())
        self.assertEqual(0, await self.ledger.db.get_balance(wallet=wallet1))
        self.assertEqual(0, await self.ledger.db.get_balance(wallet=wallet2))
        self.assertEqual(0, await self.ledger.db.get_balance(accounts=[account1]))
        self.assertEqual(0, await self.ledger.db.get_balance(accounts=[account2]))
        self.assertEqual(0, await self.ledger.db.get_balance(accounts=[account3]))

        tx1 = await self.create_tx_from_nothing(account1, 1)
        self.assertEqual(1, await self.ledger.db.get_transaction_count(accounts=[account1]))
        self.assertEqual(0, await self.ledger.db.get_transaction_count(accounts=[account2]))
        self.assertEqual(1, await self.ledger.db.get_utxo_count(accounts=[account1]))
        self.assertEqual(1, await self.ledger.db.get_txo_count(accounts=[account1]))
        self.assertEqual(0, await self.ledger.db.get_txo_count(accounts=[account2]))
        self.assertEqual(10**8, await self.ledger.db.get_balance(wallet=wallet1))
        self.assertEqual(0, await self.ledger.db.get_balance(wallet=wallet2))
        self.assertEqual(10**8, await self.ledger.db.get_balance(accounts=[account1]))
        self.assertEqual(0, await self.ledger.db.get_balance(accounts=[account2]))
        self.assertEqual(0, await self.ledger.db.get_balance(accounts=[account3]))

        tx2 = await self.create_tx_from_txo(tx1.outputs[0], account2, 2)
        tx2b = await self.create_tx_from_nothing(account3, 2)
        self.assertEqual(2, await self.ledger.db.get_transaction_count(accounts=[account1]))
        self.assertEqual(1, await self.ledger.db.get_transaction_count(accounts=[account2]))
        self.assertEqual(1, await self.ledger.db.get_transaction_count(accounts=[account3]))
        self.assertEqual(0, await self.ledger.db.get_utxo_count(accounts=[account1]))
        self.assertEqual(1, await self.ledger.db.get_txo_count(accounts=[account1]))
        self.assertEqual(1, await self.ledger.db.get_utxo_count(accounts=[account2]))
        self.assertEqual(1, await self.ledger.db.get_txo_count(accounts=[account2]))
        self.assertEqual(1, await self.ledger.db.get_utxo_count(accounts=[account3]))
        self.assertEqual(1, await self.ledger.db.get_txo_count(accounts=[account3]))
        self.assertEqual(0, await self.ledger.db.get_balance(wallet=wallet1))
        self.assertEqual(10**8+10**8, await self.ledger.db.get_balance(wallet=wallet2))
        self.assertEqual(0, await self.ledger.db.get_balance(accounts=[account1]))
        self.assertEqual(10**8, await self.ledger.db.get_balance(accounts=[account2]))
        self.assertEqual(10**8, await self.ledger.db.get_balance(accounts=[account3]))

        tx3 = await self.create_tx_to_nowhere(tx2.outputs[0], 3)
        self.assertEqual(2, await self.ledger.db.get_transaction_count(accounts=[account1]))
        self.assertEqual(2, await self.ledger.db.get_transaction_count(accounts=[account2]))
        self.assertEqual(0, await self.ledger.db.get_utxo_count(accounts=[account1]))
        self.assertEqual(1, await self.ledger.db.get_txo_count(accounts=[account1]))
        self.assertEqual(0, await self.ledger.db.get_utxo_count(accounts=[account2]))
        self.assertEqual(1, await self.ledger.db.get_txo_count(accounts=[account2]))
        self.assertEqual(0, await self.ledger.db.get_balance(wallet=wallet1))
        self.assertEqual(10**8, await self.ledger.db.get_balance(wallet=wallet2))
        self.assertEqual(0, await self.ledger.db.get_balance(accounts=[account1]))
        self.assertEqual(0, await self.ledger.db.get_balance(accounts=[account2]))
        self.assertEqual(10**8, await self.ledger.db.get_balance(accounts=[account3]))

        txs = await self.ledger.db.get_transactions(accounts=[account1, account2])
        self.assertListEqual([tx3.id, tx2.id, tx1.id], [tx.id for tx in txs])
        self.assertListEqual([3, 2, 1], [tx.height for tx in txs])

        txs = await self.ledger.db.get_transactions(wallet=wallet1, accounts=wallet1.accounts, include_is_my_output=True)
        self.assertListEqual([tx2.id, tx1.id], [tx.id for tx in txs])
        self.assertEqual(txs[0].inputs[0].is_my_input, True)
        self.assertEqual(txs[0].outputs[0].is_my_output, False)
        self.assertEqual(txs[1].inputs[0].is_my_input, False)
        self.assertEqual(txs[1].outputs[0].is_my_output, True)

        txs = await self.ledger.db.get_transactions(wallet=wallet2, accounts=[account2], include_is_my_output=True)
        self.assertListEqual([tx3.id, tx2.id], [tx.id for tx in txs])
        self.assertEqual(txs[0].inputs[0].is_my_input, True)
        self.assertEqual(txs[0].outputs[0].is_my_output, False)
        self.assertEqual(txs[1].inputs[0].is_my_input, False)
        self.assertEqual(txs[1].outputs[0].is_my_output, True)
        self.assertEqual(2, await self.ledger.db.get_transaction_count(accounts=[account2]))

        tx = await self.ledger.db.get_transaction(txid=tx2.id)
        self.assertEqual(tx.id, tx2.id)
        self.assertIsNone(tx.inputs[0].is_my_input)
        self.assertIsNone(tx.outputs[0].is_my_output)
        tx = await self.ledger.db.get_transaction(wallet=wallet1, txid=tx2.id, include_is_my_output=True)
        self.assertTrue(tx.inputs[0].is_my_input)
        self.assertFalse(tx.outputs[0].is_my_output)
        tx = await self.ledger.db.get_transaction(wallet=wallet2, txid=tx2.id, include_is_my_output=True)
        self.assertFalse(tx.inputs[0].is_my_input)
        self.assertTrue(tx.outputs[0].is_my_output)

        # height 0 sorted to the top with the rest in descending order
        tx4 = await self.create_tx_from_nothing(account1, 0)
        txos = await self.ledger.db.get_txos()
        self.assertListEqual([0, 3, 2, 2, 1], [txo.tx_ref.height for txo in txos])
        self.assertListEqual([tx4.id, tx3.id, tx2.id, tx2b.id, tx1.id], [txo.tx_ref.id for txo in txos])
        txs = await self.ledger.db.get_transactions(accounts=[account1, account2])
        self.assertListEqual([0, 3, 2, 1], [tx.height for tx in txs])
        self.assertListEqual([tx4.id, tx3.id, tx2.id, tx1.id], [tx.id for tx in txs])

    async def test_empty_history(self):
        self.assertEqual((None, []), await self.ledger.get_local_status_and_history(''))


class TestUpgrade(AsyncioTestCase):

    def setUp(self) -> None:
        self.path = tempfile.mktemp()

    def tearDown(self) -> None:
        os.remove(self.path)

    def get_version(self):
        with sqlite3.connect(self.path) as conn:
            versions = conn.execute('select version from version').fetchall()
            assert len(versions) == 1
            return versions[0][0]

    def get_tables(self):
        with sqlite3.connect(self.path) as conn:
            sql = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
            return [col[0] for col in conn.execute(sql).fetchall()]

    def add_address(self, address):
        with sqlite3.connect(self.path) as conn:
            conn.execute("""
            INSERT INTO account_address (address, account, chain, n, pubkey, chain_code, depth)
            VALUES (?, 'account1', 0, 0, 'pubkey', 'chain_code', 0)
            """, (address,))

    def get_addresses(self):
        with sqlite3.connect(self.path) as conn:
            sql = "SELECT address FROM account_address ORDER BY address;"
            return [col[0] for col in conn.execute(sql).fetchall()]

    async def test_reset_on_version_change(self):
        self.ledger = Ledger({
            'db': Database(self.path),
            'headers': Headers(':memory:')
        })

        # initial open, pre-version enabled db
        self.ledger.db.SCHEMA_VERSION = None
        self.assertListEqual(self.get_tables(), [])
        await self.ledger.db.open()
        self.assertEqual(self.get_tables(), ['account_address', 'pubkey_address', 'tx', 'txi', 'txo'])
        self.assertListEqual(self.get_addresses(), [])
        self.add_address('address1')
        await self.ledger.db.close()

        # initial open after version enabled
        self.ledger.db.SCHEMA_VERSION = '1.0'
        await self.ledger.db.open()
        self.assertEqual(self.get_version(), '1.0')
        self.assertListEqual(self.get_tables(), ['account_address', 'pubkey_address', 'tx', 'txi', 'txo', 'version'])
        self.assertListEqual(self.get_addresses(), [])  # address1 deleted during version upgrade
        self.add_address('address2')
        await self.ledger.db.close()

        # nothing changes
        self.assertEqual(self.get_version(), '1.0')
        self.assertListEqual(self.get_tables(), ['account_address', 'pubkey_address', 'tx', 'txi', 'txo', 'version'])
        await self.ledger.db.open()
        self.assertEqual(self.get_version(), '1.0')
        self.assertListEqual(self.get_tables(), ['account_address', 'pubkey_address', 'tx', 'txi', 'txo', 'version'])
        self.assertListEqual(self.get_addresses(), ['address2'])
        await self.ledger.db.close()

        # upgrade version, database reset
        self.ledger.db.SCHEMA_VERSION = '1.1'
        self.ledger.db.CREATE_TABLES_QUERY += """
        create table if not exists foo (bar text);
        """
        await self.ledger.db.open()
        self.assertEqual(self.get_version(), '1.1')
        self.assertListEqual(self.get_tables(), ['account_address', 'foo', 'pubkey_address', 'tx', 'txi', 'txo', 'version'])
        self.assertListEqual(self.get_addresses(), [])  # all tables got reset
        await self.ledger.db.close()


class TestSQLiteRace(AsyncioTestCase):
    max_misuse_attempts = 120000

    def setup_db(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.db.executescript(
            "create table test1 (id text primary key not null, val text);\n" +
            "create table test2 (id text primary key not null, val text);\n" +
            "\n".join(f"insert into test1 values ({v}, NULL);" for v in range(1000))
        )

    async def asyncSetUp(self):
        self.executor = ThreadPoolExecutor(1)
        await self.loop.run_in_executor(self.executor, self.setup_db)

    async def asyncTearDown(self):
        await self.loop.run_in_executor(self.executor, self.db.close)
        self.executor.shutdown()

    async def test_binding_param_0_error(self):
        # test real param 0 binding errors

        for supported_type in [str, int, bytes]:
            await self.loop.run_in_executor(
                self.executor, self.db.executemany, "insert into test2 values (?, NULL)",
                [(supported_type(1), ), (supported_type(2), )]
            )
            await self.loop.run_in_executor(
                self.executor, self.db.execute, "delete from test2 where id in (1, 2)"
            )
        for unsupported_type in [lambda x: (x, ), lambda x: [x], lambda x: {x}]:
            try:
                await self.loop.run_in_executor(
                    self.executor, self.db.executemany, "insert into test2 (id, val) values (?, NULL)",
                    [(unsupported_type(1), ), (unsupported_type(2), )]
                )
                self.assertTrue(False)
            except sqlite3.InterfaceError as err:
                self.assertEqual(str(err), "Error binding parameter 0 - probably unsupported type.")

    async def test_unhandled_sqlite_misuse(self):
        # test SQLITE_MISUSE being incorrectly raised as a param 0 binding error
        attempts = 0
        python_version = sys.version.split('\n')[0].rstrip(' ')

        try:
            while attempts < self.max_misuse_attempts:
                f1 = asyncio.wrap_future(
                    self.loop.run_in_executor(
                        self.executor, self.db.executemany, "update test1 set val='derp' where id=?",
                        ((str(i),) for i in range(2))
                    )
                )
                f2 = asyncio.wrap_future(
                    self.loop.run_in_executor(
                        self.executor, self.db.executemany, "update test2 set val='derp' where id=?",
                        ((str(i),) for i in range(2))
                    )
                )
                attempts += 1
                await asyncio.gather(f1, f2)
            print(f"\nsqlite3 {sqlite3.version}/python {python_version} "
                  f"did not raise SQLITE_MISUSE within {attempts} attempts of the race condition")
            self.assertTrue(False, 'this test failing means either the sqlite race conditions '
                                   'have been fixed in cpython or the test max_attempts needs to be increased')
        except sqlite3.InterfaceError as err:
            self.assertEqual(str(err), "Error binding parameter 0 - probably unsupported type.")
        print(f"\nsqlite3 {sqlite3.version}/python {python_version} raised SQLITE_MISUSE "
              f"after {attempts} attempts of the race condition")

    @unittest.SkipTest
    async def test_fetchall_prevents_sqlite_misuse(self):
        # test that calling fetchall sufficiently avoids the race
        attempts = 0

        def executemany_fetchall(query, params):
            self.db.executemany(query, params).fetchall()

        while attempts < self.max_misuse_attempts:
            f1 = asyncio.wrap_future(
                self.loop.run_in_executor(
                    self.executor, executemany_fetchall, "update test1 set val='derp' where id=?",
                    ((str(i),) for i in range(2))
                )
            )
            f2 = asyncio.wrap_future(
                self.loop.run_in_executor(
                    self.executor, executemany_fetchall, "update test2 set val='derp' where id=?",
                    ((str(i),) for i in range(2))
                )
            )
            attempts += 1
            await asyncio.gather(f1, f2)