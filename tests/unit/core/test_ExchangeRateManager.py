from lbrynet.metadata import Fee
from lbrynet.lbrynet_daemon import ExchangeRateManager

from twisted.trial import unittest

from tests import util


class FeeFormatTest(unittest.TestCase):
    def test_fee_created_with_correct_inputs(self):
        fee_dict = {
            'USD': {
                'amount': 10.0,
                'address': "bRcHraa8bYJZL7vkh5sNmGwPDERFUjGPP9"
            }
        }
        fee = Fee.FeeValidator(fee_dict)
        self.assertEqual(10.0, fee['USD']['amount'])


class FeeTest(unittest.TestCase):
    def setUp(self):
        util.resetTime(self)

    def test_fee_converts_to_lbc(self):
        fee_dict = {
            'USD': {
                'amount': 10.0,
                'address': "bRcHraa8bYJZL7vkh5sNmGwPDERFUjGPP9"
            }
        }
        rates = {
            'BTCLBC': {'spot': 3.0, 'ts': util.DEFAULT_ISO_TIME + 1},
            'USDBTC': {'spot': 2.0, 'ts': util.DEFAULT_ISO_TIME + 2}
        }
        manager = ExchangeRateManager.DummyExchangeRateManager(rates)
        result = manager.to_lbc(fee_dict).amount
        self.assertEqual(60.0, result)
