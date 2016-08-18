import mock
from lbrynet.metadata import LBRYMetadata
from lbrynet.lbrynet_daemon import LBRYExchangeRateManager

from twisted.trial import unittest


class LBRYFeeFormatTest(unittest.TestCase):
    def test_fee_created_with_correct_inputs(self):
        fee_dict = {
            'USD': {
                'amount': 10.0,
                'address': "bRcHraa8bYJZL7vkh5sNmGwPDERFUjGPP9"
            }
        }
        fee = LBRYMetadata.LBRYFeeValidator(fee_dict)
        self.assertEqual(10.0, fee['USD']['amount'])


class LBRYFeeTest(unittest.TestCase):
    def setUp(self):
        self.patcher = mock.patch('time.time')
        self.time = self.patcher.start()
        self.time.return_value = 0

    def tearDown(self):
        self.time.stop()

    def test_fee_converts_to_lbc(self):
        fee_dict = {
            'USD': {
                'amount': 10.0,
                'address': "bRcHraa8bYJZL7vkh5sNmGwPDERFUjGPP9"
            }
        }
        rates = {'BTCLBC': {'spot': 3.0, 'ts': 2}, 'USDBTC': {'spot': 2.0, 'ts': 3}}
        manager = LBRYExchangeRateManager.DummyExchangeRateManager(rates)
        self.assertEqual(60.0, manager.to_lbc(fee_dict).amount)