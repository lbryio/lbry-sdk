from types import GeneratorType

from orchstr8.testcase import AsyncioTestCase

from torba.coin.bitcoinsegwit import MainNetLedger as ledger_class
from torba.coinselection import CoinSelector, MAXIMUM_TRIES
from torba.constants import CENT

from .test_transaction import get_output as utxo


NULL_HASH = b'\x00'*32


def search(*args, **kwargs):
    selection = CoinSelector(*args, **kwargs).branch_and_bound()
    return [o.txo.amount for o in selection] if selection else selection


class BaseSelectionTestCase(AsyncioTestCase):

    async def asyncSetUp(self):
        self.ledger = ledger_class({
            'db': ledger_class.database_class(':memory:'),
            'headers': ledger_class.headers_class(':memory:'),
        })
        await self.ledger.db.open()

    async def asyncTearDown(self):
        await self.ledger.db.close()

    def estimates(self, *args):
        txos = args[0] if isinstance(args[0], (GeneratorType, list)) else args
        return [txo.get_estimator(self.ledger) for txo in txos]


class TestCoinSelectionTests(BaseSelectionTestCase):

    def test_empty_coins(self):
        self.assertEqual(CoinSelector([], 0, 0).select(), [])

    def test_skip_binary_search_if_total_not_enough(self):
        fee = utxo(CENT).get_estimator(self.ledger).fee
        big_pool = self.estimates(utxo(CENT+fee) for _ in range(100))
        selector = CoinSelector(big_pool, 101 * CENT, 0)
        self.assertEqual(selector.select(), [])
        self.assertEqual(selector.tries, 0)  # Never tried.
        # check happy path
        selector = CoinSelector(big_pool, 100 * CENT, 0)
        self.assertEqual(len(selector.select()), 100)
        self.assertEqual(selector.tries, 201)

    def test_exact_match(self):
        fee = utxo(CENT).get_estimator(self.ledger).fee
        utxo_pool = self.estimates(
            utxo(CENT + fee),
            utxo(CENT),
            utxo(CENT - fee)
        )
        selector = CoinSelector(utxo_pool, CENT, 0)
        match = selector.select()
        self.assertEqual([CENT + fee], [c.txo.amount for c in match])
        self.assertTrue(selector.exact_match)

    def test_random_draw(self):
        utxo_pool = self.estimates(
            utxo(2 * CENT),
            utxo(3 * CENT),
            utxo(4 * CENT)
        )
        selector = CoinSelector(utxo_pool, CENT, 0, '\x00')
        match = selector.select()
        self.assertEqual([2 * CENT], [c.txo.amount for c in match])
        self.assertFalse(selector.exact_match)

    def test_pick(self):
        utxo_pool = self.estimates(
            utxo(1*CENT),
            utxo(1*CENT),
            utxo(3*CENT),
            utxo(5*CENT),
            utxo(10*CENT),
        )
        selector = CoinSelector(utxo_pool, 3*CENT, 0)
        match = selector.select()
        self.assertEqual([5*CENT], [c.txo.amount for c in match])


class TestOfficialBitcoinCoinSelectionTests(BaseSelectionTestCase):

    #       Bitcoin implementation:
    #       https://github.com/bitcoin/bitcoin/blob/master/src/wallet/coinselection.cpp
    #
    #       Bitcoin implementation tests:
    #       https://github.com/bitcoin/bitcoin/blob/master/src/wallet/test/coinselector_tests.cpp
    #
    #       Branch and Bound coin selection white paper:
    #       https://murch.one/wp-content/uploads/2016/11/erhardt2016coinselection.pdf

    def make_hard_case(self, utxos):
        target = 0
        utxo_pool = []
        for i in range(utxos):
            amount = 1 << (utxos+i)
            target += amount
            utxo_pool.append(utxo(amount))
            utxo_pool.append(utxo(amount + (1 << (utxos-1-i))))
        return self.estimates(utxo_pool), target

    def test_branch_and_bound_coin_selection(self):
        self.ledger.fee_per_byte = 0

        utxo_pool = self.estimates(
            utxo(1 * CENT),
            utxo(2 * CENT),
            utxo(3 * CENT),
            utxo(4 * CENT)
        )

        # Select 1 Cent
        self.assertEqual([1 * CENT], search(utxo_pool, 1 * CENT, 0.5 * CENT))

        # Select 2 Cent
        self.assertEqual([2 * CENT], search(utxo_pool, 2 * CENT, 0.5 * CENT))

        # Select 5 Cent
        self.assertEqual([3 * CENT, 2 * CENT], search(utxo_pool, 5 * CENT, 0.5 * CENT))

        # Select 11 Cent, not possible
        self.assertEqual([], search(utxo_pool, 11 * CENT, 0.5 * CENT))

        # Select 10 Cent
        utxo_pool += self.estimates(utxo(5 * CENT))
        self.assertEqual(
            [4 * CENT, 3 * CENT, 2 * CENT, 1 * CENT],
            search(utxo_pool, 10 * CENT, 0.5 * CENT)
        )

        # Negative effective value
        # Select 10 Cent but have 1 Cent not be possible because too small
        # TODO: bitcoin has [5, 3, 2]
        self.assertEqual(
            [4 * CENT, 3 * CENT, 2 * CENT, 1 * CENT],
            search(utxo_pool, 10 * CENT, 5000)
        )

        # Select 0.25 Cent, not possible
        self.assertEqual(search(utxo_pool, 0.25 * CENT, 0.5 * CENT), [])

        # Iteration exhaustion test
        utxo_pool, target = self.make_hard_case(17)
        selector = CoinSelector(utxo_pool, target, 0)
        self.assertEqual(selector.branch_and_bound(), [])
        self.assertEqual(selector.tries, MAXIMUM_TRIES)  # Should exhaust
        utxo_pool, target = self.make_hard_case(14)
        self.assertIsNotNone(search(utxo_pool, target, 0))  # Should not exhaust

        # Test same value early bailout optimization
        utxo_pool = self.estimates([
            utxo(7 * CENT),
            utxo(7 * CENT),
            utxo(7 * CENT),
            utxo(7 * CENT),
            utxo(2 * CENT)
        ] + [utxo(5 * CENT)]*50000)
        self.assertEqual(
            [7 * CENT, 7 * CENT, 7 * CENT, 7 * CENT, 2 * CENT],
            search(utxo_pool, 30 * CENT, 5000)
        )

        # Select 1 Cent with pool of only greater than 5 Cent
        utxo_pool = self.estimates(utxo(i * CENT) for i in range(5, 21))
        for _ in range(100):
            self.assertEqual(search(utxo_pool, 1 * CENT, 2 * CENT), [])
