import unittest

from lbrynet.wallet.coins.lbc.lbc import LBRYCredits
from lbrynet.wallet.coins.bitcoin import Bitcoin
from lbrynet.wallet.coinselection import CoinSelector, MAXIMUM_TRIES
from lbrynet.wallet.constants import CENT
from lbrynet.wallet.manager import WalletManager

from .test_transaction import get_output as utxo


NULL_HASH = '\x00'*32


def search(*args, **kwargs):
    selection = CoinSelector(*args, **kwargs).branch_and_bound()
    return [o.amount for o in selection] if selection else selection


class TestCoinSelectionTests(unittest.TestCase):

    def setUp(self):
        WalletManager([], {
            LBRYCredits.ledger_class: LBRYCredits.ledger_class(LBRYCredits),
        }).install()

    def test_empty_coins(self):
        self.assertIsNone(CoinSelector([], 0, 0).select())

    def test_skip_binary_search_if_total_not_enough(self):
        fee = utxo(CENT).spend().fee
        big_pool = [utxo(CENT+fee) for _ in range(100)]
        selector = CoinSelector(big_pool, 101 * CENT, 0)
        self.assertIsNone(selector.select())
        self.assertEqual(selector.tries, 0)  # Never tried.
        # check happy path
        selector = CoinSelector(big_pool, 100 * CENT, 0)
        self.assertEqual(len(selector.select()), 100)
        self.assertEqual(selector.tries, 201)

    def test_exact_match(self):
        fee = utxo(CENT).spend().fee
        utxo_pool = [
            utxo(CENT + fee),
            utxo(CENT),
            utxo(CENT - fee),
        ]
        selector = CoinSelector(utxo_pool, CENT, 0)
        match = selector.select()
        self.assertEqual([CENT + fee], [c.amount for c in match])
        self.assertTrue(selector.exact_match)

    def test_random_draw(self):
        utxo_pool = [
            utxo(2 * CENT),
            utxo(3 * CENT),
            utxo(4 * CENT),
        ]
        selector = CoinSelector(utxo_pool, CENT, 0, 1)
        match = selector.select()
        self.assertEqual([2 * CENT], [c.amount for c in match])
        self.assertFalse(selector.exact_match)


class TestOfficialBitcoinCoinSelectionTests(unittest.TestCase):

    #       Bitcoin implementation:
    #       https://github.com/bitcoin/bitcoin/blob/master/src/wallet/coinselection.cpp
    #
    #       Bitcoin implementation tests:
    #       https://github.com/bitcoin/bitcoin/blob/master/src/wallet/test/coinselector_tests.cpp
    #
    #       Branch and Bound coin selection white paper:
    #       https://murch.one/wp-content/uploads/2016/11/erhardt2016coinselection.pdf

    def setUp(self):
        WalletManager([], {
            Bitcoin.ledger_class: Bitcoin.ledger_class(Bitcoin),
        }).install()

    def make_hard_case(self, utxos):
        target = 0
        utxo_pool = []
        for i in range(utxos):
            amount = 1 << (utxos+i)
            target += amount
            utxo_pool.append(utxo(amount))
            utxo_pool.append(utxo(amount + (1 << (utxos-1-i))))
        return utxo_pool, target

    def test_branch_and_bound_coin_selection(self):
        utxo_pool = [
            utxo(1 * CENT),
            utxo(2 * CENT),
            utxo(3 * CENT),
            utxo(4 * CENT)
        ]

        # Select 1 Cent
        self.assertEqual([1 * CENT], search(utxo_pool, 1 * CENT, 0.5 * CENT))

        # Select 2 Cent
        self.assertEqual([2 * CENT], search(utxo_pool, 2 * CENT, 0.5 * CENT))

        # Select 5 Cent
        self.assertEqual([3 * CENT, 2 * CENT], search(utxo_pool, 5 * CENT, 0.5 * CENT))

        # Select 11 Cent, not possible
        self.assertIsNone(search(utxo_pool, 11 * CENT, 0.5 * CENT))

        # Select 10 Cent
        utxo_pool += [utxo(5 * CENT)]
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
        self.assertIsNone(search(utxo_pool, 0.25 * CENT, 0.5 * CENT))

        # Iteration exhaustion test
        utxo_pool, target = self.make_hard_case(17)
        selector = CoinSelector(utxo_pool, target, 0)
        self.assertIsNone(selector.branch_and_bound())
        self.assertEqual(selector.tries, MAXIMUM_TRIES)  # Should exhaust
        utxo_pool, target = self.make_hard_case(14)
        self.assertIsNotNone(search(utxo_pool, target, 0))  # Should not exhaust

        # Test same value early bailout optimization
        utxo_pool = [
            utxo(7 * CENT),
            utxo(7 * CENT),
            utxo(7 * CENT),
            utxo(7 * CENT),
            utxo(2 * CENT)
        ] + [utxo(5 * CENT)]*50000
        self.assertEqual(
            [7 * CENT, 7 * CENT, 7 * CENT, 7 * CENT, 2 * CENT],
            search(utxo_pool, 30 * CENT, 5000)
        )

        # Select 1 Cent with pool of only greater than 5 Cent
        utxo_pool = [utxo(i * CENT) for i in range(5, 21)]
        for _ in range(100):
            self.assertIsNone(search(utxo_pool, 1 * CENT, 2 * CENT))
