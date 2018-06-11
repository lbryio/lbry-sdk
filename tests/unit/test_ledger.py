from twisted.trial import unittest
from twisted.internet import defer

from torba.basedatabase import BaseSQLiteWalletStorage


class TestDatabase(unittest.TestCase):

    def setUp(self):
        self.db = BaseSQLiteWalletStorage(':memory:')
        return self.db.start()

    @defer.inlineCallbacks
    def test_empty_db(self):
        result = yield self.db.
