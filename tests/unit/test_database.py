from twisted.trial import unittest
from twisted.internet import defer

from torba.wallet import Wallet
from torba.constants import COIN
from torba.coin.bitcoinsegwit import MainNetLedger as ledger_class
from torba.basedatabase import query, constraints_to_sql

from .test_transaction import get_output, NULL_HASH


class TestQueryBuilder(unittest.TestCase):

    def test_dot(self):
        self.assertEqual(
            constraints_to_sql({'txo.position': 18}),
            ('txo.position = :txo_position', {'txo_position': 18})
        )

    def test_any(self):
        self.assertEqual(
            constraints_to_sql({
                'ages__any': {
                    'txo.age__gt': 18,
                    'txo.age__lt': 38
                }
            }),
            ('(txo.age > :ages__any_txo_age__gt OR txo.age < :ages__any_txo_age__lt)', {
                'ages__any_txo_age__gt': 18,
                'ages__any_txo_age__lt': 38
            })
        )

    def test_in_list(self):
        self.assertEqual(
            constraints_to_sql({'txo.age__in': [18, 38]}),
            ('txo.age IN (18, 38)', {})
        )
        self.assertEqual(
            constraints_to_sql({'txo.age__in': ['abc123', 'def456']}),
            ("txo.age IN ('abc123', 'def456')", {})
        )

    def test_in_query(self):
        self.assertEqual(
            constraints_to_sql({'txo.age__in': 'SELECT age from ages_table'}),
            ('txo.age IN (SELECT age from ages_table)', {})
        )

    def test_not_in_query(self):
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
                a='b', b__in='select * from blah where c=:$c',
                d__any={'one': 1, 'two': 2}, limit=10, order_by='b', **{'$c': 3}),
            (
                "select * from foo WHERE a = :a AND "
                "b IN (select * from blah where c=:$c) AND "
                "(one = :d__any_one OR two = :d__any_two) ORDER BY b LIMIT 10",
                {'a': 'b', 'd__any_one': 1, 'd__any_two': 2, '$c': 3}
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


class TestQueries(unittest.TestCase):

    def setUp(self):
        self.ledger = ledger_class({
            'db': ledger_class.database_class(':memory:'),
            'headers': ledger_class.headers_class(':memory:'),
        })
        return self.ledger.db.open()

    @defer.inlineCallbacks
    def create_account(self):
        account = self.ledger.account_class.generate(self.ledger, Wallet())
        yield account.ensure_address_gap()
        return account

    @defer.inlineCallbacks
    def create_tx_from_nothing(self, my_account, height):
        to_address = yield my_account.receiving.get_or_create_usable_address()
        to_hash = ledger_class.address_to_hash160(to_address)
        tx = ledger_class.transaction_class(height=height, is_verified=True) \
            .add_inputs([self.txi(self.txo(1, NULL_HASH))]) \
            .add_outputs([self.txo(1, to_hash)])
        yield self.ledger.db.save_transaction_io('insert', tx, to_address, to_hash, '')
        return tx

    @defer.inlineCallbacks
    def create_tx_from_txo(self, txo, to_account, height):
        from_hash = txo.script.values['pubkey_hash']
        from_address = self.ledger.hash160_to_address(from_hash)
        to_address = yield to_account.receiving.get_or_create_usable_address()
        to_hash = ledger_class.address_to_hash160(to_address)
        tx = ledger_class.transaction_class(height=height, is_verified=True) \
            .add_inputs([self.txi(txo)]) \
            .add_outputs([self.txo(1, to_hash)])
        yield self.ledger.db.save_transaction_io('insert', tx, from_address, from_hash, '')
        yield self.ledger.db.save_transaction_io('', tx, to_address, to_hash, '')
        return tx

    @defer.inlineCallbacks
    def create_tx_to_nowhere(self, txo, height):
        from_hash = txo.script.values['pubkey_hash']
        from_address = self.ledger.hash160_to_address(from_hash)
        to_hash = NULL_HASH
        tx = ledger_class.transaction_class(height=height, is_verified=True) \
            .add_inputs([self.txi(txo)]) \
            .add_outputs([self.txo(1, to_hash)])
        yield self.ledger.db.save_transaction_io('insert', tx, from_address, from_hash, '')
        return tx

    def txo(self, amount, address):
        return get_output(int(amount*COIN), address)

    def txi(self, txo):
        return ledger_class.transaction_class.input_class.spend(txo)

    @defer.inlineCallbacks
    def test_get_transactions(self):
        account1 = yield self.create_account()
        account2 = yield self.create_account()
        tx1 = yield self.create_tx_from_nothing(account1, 1)
        tx2 = yield self.create_tx_from_txo(tx1.outputs[0], account2, 2)
        tx3 = yield self.create_tx_to_nowhere(tx2.outputs[0], 3)

        txs = yield self.ledger.db.get_transactions()
        self.assertEqual([tx3.id, tx2.id, tx1.id], [tx.id for tx in txs])
        self.assertEqual([3, 2, 1], [tx.height for tx in txs])

        txs = yield self.ledger.db.get_transactions(account=account1)
        self.assertEqual([tx2.id, tx1.id], [tx.id for tx in txs])
        self.assertEqual(txs[0].inputs[0].is_my_account, True)
        self.assertEqual(txs[0].outputs[0].is_my_account, False)
        self.assertEqual(txs[1].inputs[0].is_my_account, False)
        self.assertEqual(txs[1].outputs[0].is_my_account, True)

        txs = yield self.ledger.db.get_transactions(account=account2)
        self.assertEqual([tx3.id, tx2.id], [tx.id for tx in txs])
        self.assertEqual(txs[0].inputs[0].is_my_account, True)
        self.assertEqual(txs[0].outputs[0].is_my_account, False)
        self.assertEqual(txs[1].inputs[0].is_my_account, False)
        self.assertEqual(txs[1].outputs[0].is_my_account, True)

        tx = yield self.ledger.db.get_transaction(txid=tx2.id)
        self.assertEqual(tx.id, tx2.id)
        self.assertEqual(tx.inputs[0].is_my_account, False)
        self.assertEqual(tx.outputs[0].is_my_account, False)
        tx = yield self.ledger.db.get_transaction(txid=tx2.id, account=account1)
        self.assertEqual(tx.inputs[0].is_my_account, True)
        self.assertEqual(tx.outputs[0].is_my_account, False)
        tx = yield self.ledger.db.get_transaction(txid=tx2.id, account=account2)
        self.assertEqual(tx.inputs[0].is_my_account, False)
        self.assertEqual(tx.outputs[0].is_my_account, True)
