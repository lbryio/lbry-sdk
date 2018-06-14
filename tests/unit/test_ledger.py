import six
from binascii import hexlify
from twisted.trial import unittest
from twisted.internet import defer

from torba.coin.bitcoinsegwit import MainNetLedger

from .test_transaction import get_transaction

if six.PY3:
    buffer = memoryview


class MockNetwork:

    def __init__(self, history, transaction):
        self.history = history
        self.transaction = transaction
        self.address = None
        self.get_history_called = []
        self.get_transaction_called = []

    def get_history(self, address):
        self.get_history_called.append(address)
        self.address = address
        return defer.succeed(self.history)

    def get_transaction(self, tx_hash):
        self.get_transaction_called.append(tx_hash)
        return defer.succeed(self.transaction[tx_hash])


class TestSynchronization(unittest.TestCase):

    def setUp(self):
        self.ledger = MainNetLedger(db=':memory:')
        return self.ledger.db.start()

    @defer.inlineCallbacks
    def test_update_history(self):
        account = self.ledger.account_class.generate(self.ledger, u"torba")
        address = yield account.receiving.get_or_create_usable_address()
        address_details = yield self.ledger.db.get_address(address)
        self.assertEqual(address_details['history'], None)

        self.ledger.network = MockNetwork([
            {'tx_hash': b'abc', 'height': 1},
            {'tx_hash': b'def', 'height': 2},
            {'tx_hash': b'ghi', 'height': 3},
        ], {
            b'abc': hexlify(get_transaction().raw),
            b'def': hexlify(get_transaction().raw),
            b'ghi': hexlify(get_transaction().raw),
        })
        yield self.ledger.update_history(address)
        self.assertEqual(self.ledger.network.get_history_called, [address])
        self.assertEqual(self.ledger.network.get_transaction_called, [b'abc', b'def', b'ghi'])

        address_details = yield self.ledger.db.get_address(address)
        self.assertEqual(address_details['history'], buffer(b'abc:1:def:2:ghi:3:'))

        self.ledger.network.get_history_called = []
        self.ledger.network.get_transaction_called = []
        yield self.ledger.update_history(address)
        self.assertEqual(self.ledger.network.get_history_called, [address])
        self.assertEqual(self.ledger.network.get_transaction_called, [])

        self.ledger.network.history.append({'tx_hash': b'jkl', 'height': 4})
        self.ledger.network.transaction[b'jkl'] = hexlify(get_transaction().raw)
        self.ledger.network.get_history_called = []
        self.ledger.network.get_transaction_called = []
        yield self.ledger.update_history(address)
        self.assertEqual(self.ledger.network.get_history_called, [address])
        self.assertEqual(self.ledger.network.get_transaction_called, [b'jkl'])
        address_details = yield self.ledger.db.get_address(address)
        self.assertEqual(address_details['history'], buffer(b'abc:1:def:2:ghi:3:jkl:4:'))
