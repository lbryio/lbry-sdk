import mock
from lbrynet.metadata import Fee
from lbrynet.lbrynet_daemon import ExchangeRateManager

from twisted.trial import unittest


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
        patcher = mock.patch('time.time')
        self.time = patcher.start()
        self.time.return_value = 0
        self.addCleanup(patcher.stop)

    def test_fee_converts_to_lbc(self):
        fee_dict = {
            'USD': {
                'amount': 10.0,
                'address': "bRcHraa8bYJZL7vkh5sNmGwPDERFUjGPP9"
            }
        }
        rates = {'BTCLBC': {'spot': 3.0, 'ts': 2}, 'USDBTC': {'spot': 2.0, 'ts': 3}}
        manager = ExchangeRateManager.DummyExchangeRateManager(rates)
        self.assertEqual(60.0, manager.to_lbc(fee_dict).amount)
