import unittest

from lbrynet.extras.wallet.dewies import lbc_to_dewies as l2d, dewies_to_lbc as d2l


class TestDeweyConversion(unittest.TestCase):

    def test_good_output(self):
        self.assertEqual(d2l(1), "0.00000001")
        self.assertEqual(d2l(10**7), "0.1")
        self.assertEqual(d2l(2*10**8), "2.0")
        self.assertEqual(d2l(2*10**17), "2000000000.0")

    def test_good_input(self):
        self.assertEqual(l2d("0.00000001"), 1)
        self.assertEqual(l2d("0.1"), 10**7)
        self.assertEqual(l2d("1.0"), 10**8)
        self.assertEqual(l2d("2.00000000"), 2*10**8)
        self.assertEqual(l2d("2000000000.0"), 2*10**17)

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            l2d("1")
        with self.assertRaises(ValueError):
            l2d("-1.0")
        with self.assertRaises(ValueError):
            l2d("10000000000.0")
        with self.assertRaises(ValueError):
            l2d("1.000000000")
        with self.assertRaises(ValueError):
            l2d("-0")
        with self.assertRaises(ValueError):
            l2d("1")
        with self.assertRaises(ValueError):
            l2d(".1")
        with self.assertRaises(ValueError):
            l2d("1e-7")
