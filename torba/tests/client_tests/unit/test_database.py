import unittest
import sqlite3
from functools import wraps

from torba.client.wallet import Wallet
from torba.client.constants import COIN
from torba.coin.bitcoinsegwit import MainNetLedger as ledger_class
from torba.client.basedatabase import query, constraints_to_sql, AIOSQLite
from torba.client.hash import sha256

from torba.testcase import AsyncioTestCase

from client_tests.unit.test_transaction import get_output, NULL_HASH


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
        self.assertEqual(
            constraints_to_sql({'txo.position': 18}),
            ('txo.position = :txo_position0', {'txo_position0': 18})
        )
        self.assertEqual(
            constraints_to_sql({'txo.position#6': 18}),
            ('txo.position = :txo_position6', {'txo_position6': 18})
        )

    def test_any(self):
        self.assertEqual(
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
        self.assertEqual(
            constraints_to_sql({'txo.age__in#2': [18, 38]}),
            ('txo.age IN (:txo_age__in2_0, :txo_age__in2_1)', {
                'txo_age__in2_0': 18,
                'txo_age__in2_1': 38
            })
        )
        self.assertEqual(
            constraints_to_sql({'txo.name__in': ('abc123', 'def456')}),
            ('txo.name IN (:txo_name__in0_0, :txo_name__in0_1)', {
                'txo_name__in0_0': 'abc123',
                'txo_name__in0_1': 'def456'
            })
        )
        self.assertEqual(
            constraints_to_sql({'txo.age__in': 'SELECT age from ages_table'}),
            ('txo.age IN (SELECT age from ages_table)', {})
        )

    def test_not_in(self):
        self.assertEqual(
            constraints_to_sql({'txo.age__not_in': [18, 38]}),
            ('txo.age NOT IN (:txo_age__not_in0_0, :txo_age__not_in0_1)', {
                'txo_age__not_in0_0': 18,
                'txo_age__not_in0_1': 38
            })
        )
        self.assertEqual(
            constraints_to_sql({'txo.name__not_in': ('abc123', 'def456')}),
            ('txo.name NOT IN (:txo_name__not_in0_0, :txo_name__not_in0_1)', {
                'txo_name__not_in0_0': 'abc123',
                'txo_name__not_in0_1': 'def456'
            })
        )
        self.assertEqual(
            constraints_to_sql({'txo.age__not_in': 'SELECT age from ages_table'}),
            ('txo.age NOT IN (SELECT age from ages_table)', {})
        )

    def test_in_invalid(self):
        with self.assertRaisesRegex(ValueError, 'list, set or string'):
            constraints_to_sql({'ages__in': 9})

    def test_query(self):
        self.assertEqual(
            query("select * from foo"),
            ("select * from foo", {})
        )
        self.assertEqual(
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
        self.assertEqual(
            query("select * from foo", order_by='foo'),
            ("select * from foo ORDER BY foo", {})
        )
        self.assertEqual(
            query("select * from foo", order_by=['foo', 'bar']),
            ("select * from foo ORDER BY foo, bar", {})
        )
        with self.assertRaisesRegex(ValueError, 'order_by must be string or list'):
            query("select * from foo", order_by={'foo': 'bar'})

    def test_query_limit_offset(self):
        self.assertEqual(
            query("select * from foo", limit=10),
            ("select * from foo LIMIT 10", {})
        )
        self.assertEqual(
            query("select * from foo", offset=10),
            ("select * from foo OFFSET 10", {})
        )
        self.assertEqual(
            query("select * from foo", limit=20, offset=10),
            ("select * from foo LIMIT 20 OFFSET 10", {})
        )


class TestQueries(AsyncioTestCase):

    async def asyncSetUp(self):
        self.ledger = ledger_class({
            'db': ledger_class.database_class(':memory:'),
            'headers': ledger_class.headers_class(':memory:'),
        })
        await self.ledger.db.open()

    async def asyncTearDown(self):
        await self.ledger.db.close()

    async def create_account(self):
        account = self.ledger.account_class.generate(self.ledger, Wallet())
        await account.ensure_address_gap()
        return account

    async def create_tx_from_nothing(self, my_account, height):
        to_address = await my_account.receiving.get_or_create_usable_address()
        to_hash = ledger_class.address_to_hash160(to_address)
        tx = ledger_class.transaction_class(height=height, is_verified=True) \
            .add_inputs([self.txi(self.txo(1, sha256(str(height).encode())))]) \
            .add_outputs([self.txo(1, to_hash)])
        await self.ledger.db.insert_transaction(tx)
        await self.ledger.db.save_transaction_io(tx, to_address, to_hash, '')
        return tx

    async def create_tx_from_txo(self, txo, to_account, height):
        from_hash = txo.script.values['pubkey_hash']
        from_address = self.ledger.hash160_to_address(from_hash)
        to_address = await to_account.receiving.get_or_create_usable_address()
        to_hash = ledger_class.address_to_hash160(to_address)
        tx = ledger_class.transaction_class(height=height, is_verified=True) \
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
        tx = ledger_class.transaction_class(height=height, is_verified=True) \
            .add_inputs([self.txi(txo)]) \
            .add_outputs([self.txo(1, to_hash)])
        await self.ledger.db.insert_transaction(tx)
        await self.ledger.db.save_transaction_io(tx, from_address, from_hash, '')
        return tx

    def txo(self, amount, address):
        return get_output(int(amount*COIN), address)

    def txi(self, txo):
        return ledger_class.transaction_class.input_class.spend(txo)

    async def test_large_tx_doesnt_hit_variable_limits(self):
        # SQLite is usually compiled with 999 variables limit: https://www.sqlite.org/limits.html
        # This can be removed when there is a better way. See: https://github.com/lbryio/lbry-sdk/issues/2281
        fetchall = self.ledger.db.db.execute_fetchall
        def check_parameters_length(sql, parameters):
            self.assertLess(len(parameters or []), 999)
            return fetchall(sql, parameters)

        self.ledger.db.db.execute_fetchall = check_parameters_length
        account = await self.create_account()
        tx = await self.create_tx_from_nothing(account, 0)
        for height in range(1200):
            tx = await self.create_tx_from_txo(tx.outputs[0], account, height=height)
        variable_limit = self.ledger.db.MAX_QUERY_VARIABLES
        for limit in range(variable_limit-2, variable_limit+2):
            txs = await self.ledger.db.get_transactions(limit=limit, order_by='height asc')
            self.assertEqual(len(txs), limit)
            inputs, outputs, last_tx = set(), set(), txs[0]
            for tx in txs[1:]:
                self.assertEqual(len(tx.inputs), 1)
                self.assertEqual(tx.inputs[0].txo_ref.tx_ref.id, last_tx.id)
                self.assertEqual(len(tx.outputs), 1)
                last_tx = tx


    async def test_queries(self):
        self.assertEqual(0, await self.ledger.db.get_address_count())
        account1 = await self.create_account()
        self.assertEqual(26, await self.ledger.db.get_address_count())
        account2 = await self.create_account()
        self.assertEqual(52, await self.ledger.db.get_address_count())

        self.assertEqual(0, await self.ledger.db.get_transaction_count())
        self.assertEqual(0, await self.ledger.db.get_utxo_count())
        self.assertEqual([], await self.ledger.db.get_utxos(my_account=None))
        self.assertEqual(0, await self.ledger.db.get_txo_count())
        self.assertEqual(0, await self.ledger.db.get_balance())
        self.assertEqual(0, await self.ledger.db.get_balance(account=account1))
        self.assertEqual(0, await self.ledger.db.get_balance(account=account2))

        tx1 = await self.create_tx_from_nothing(account1, 1)
        self.assertEqual(1, await self.ledger.db.get_transaction_count(account=account1))
        self.assertEqual(0, await self.ledger.db.get_transaction_count(account=account2))
        self.assertEqual(1, await self.ledger.db.get_utxo_count(account=account1))
        self.assertEqual(1, await self.ledger.db.get_txo_count(account=account1))
        self.assertEqual(0, await self.ledger.db.get_txo_count(account=account2))
        self.assertEqual(10**8, await self.ledger.db.get_balance())
        self.assertEqual(10**8, await self.ledger.db.get_balance(account=account1))
        self.assertEqual(0, await self.ledger.db.get_balance(account=account2))

        tx2 = await self.create_tx_from_txo(tx1.outputs[0], account2, 2)
        self.assertEqual(2, await self.ledger.db.get_transaction_count(account=account1))
        self.assertEqual(1, await self.ledger.db.get_transaction_count(account=account2))
        self.assertEqual(0, await self.ledger.db.get_utxo_count(account=account1))
        self.assertEqual(1, await self.ledger.db.get_txo_count(account=account1))
        self.assertEqual(1, await self.ledger.db.get_utxo_count(account=account2))
        self.assertEqual(1, await self.ledger.db.get_txo_count(account=account2))
        self.assertEqual(10**8, await self.ledger.db.get_balance())
        self.assertEqual(0, await self.ledger.db.get_balance(account=account1))
        self.assertEqual(10**8, await self.ledger.db.get_balance(account=account2))

        tx3 = await self.create_tx_to_nowhere(tx2.outputs[0], 3)
        self.assertEqual(2, await self.ledger.db.get_transaction_count(account=account1))
        self.assertEqual(2, await self.ledger.db.get_transaction_count(account=account2))
        self.assertEqual(0, await self.ledger.db.get_utxo_count(account=account1))
        self.assertEqual(1, await self.ledger.db.get_txo_count(account=account1))
        self.assertEqual(0, await self.ledger.db.get_utxo_count(account=account2))
        self.assertEqual(1, await self.ledger.db.get_txo_count(account=account2))
        self.assertEqual(0, await self.ledger.db.get_balance())
        self.assertEqual(0, await self.ledger.db.get_balance(account=account1))
        self.assertEqual(0, await self.ledger.db.get_balance(account=account2))

        txs = await self.ledger.db.get_transactions()
        self.assertEqual([tx3.id, tx2.id, tx1.id], [tx.id for tx in txs])
        self.assertEqual([3, 2, 1], [tx.height for tx in txs])

        txs = await self.ledger.db.get_transactions(account=account1)
        self.assertEqual([tx2.id, tx1.id], [tx.id for tx in txs])
        self.assertEqual(txs[0].inputs[0].is_my_account, True)
        self.assertEqual(txs[0].outputs[0].is_my_account, False)
        self.assertEqual(txs[1].inputs[0].is_my_account, False)
        self.assertEqual(txs[1].outputs[0].is_my_account, True)

        txs = await self.ledger.db.get_transactions(account=account2)
        self.assertEqual([tx3.id, tx2.id], [tx.id for tx in txs])
        self.assertEqual(txs[0].inputs[0].is_my_account, True)
        self.assertEqual(txs[0].outputs[0].is_my_account, False)
        self.assertEqual(txs[1].inputs[0].is_my_account, False)
        self.assertEqual(txs[1].outputs[0].is_my_account, True)
        self.assertEqual(2, await self.ledger.db.get_transaction_count(account=account2))

        tx = await self.ledger.db.get_transaction(txid=tx2.id)
        self.assertEqual(tx.id, tx2.id)
        self.assertEqual(tx.inputs[0].is_my_account, False)
        self.assertEqual(tx.outputs[0].is_my_account, False)
        tx = await self.ledger.db.get_transaction(txid=tx2.id, account=account1)
        self.assertEqual(tx.inputs[0].is_my_account, True)
        self.assertEqual(tx.outputs[0].is_my_account, False)
        tx = await self.ledger.db.get_transaction(txid=tx2.id, account=account2)
        self.assertEqual(tx.inputs[0].is_my_account, False)
        self.assertEqual(tx.outputs[0].is_my_account, True)

        # height 0 sorted to the top with the rest in descending order
        tx4 = await self.create_tx_from_nothing(account1, 0)
        txos = await self.ledger.db.get_txos(my_accounts=None)
        self.assertEqual([0, 2, 1], [txo.tx_ref.height for txo in txos])
        self.assertEqual([tx4.id, tx2.id, tx1.id], [txo.tx_ref.id for txo in txos])
        txs = await self.ledger.db.get_transactions()
        self.assertEqual([0, 3, 2, 1], [tx.height for tx in txs])
        self.assertEqual([tx4.id, tx3.id, tx2.id, tx1.id], [tx.id for tx in txs])
