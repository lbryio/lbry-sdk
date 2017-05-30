from lbryschema.fee import Fee
from lbrynet.lbrynet_daemon import ExchangeRateManager
from lbrynet.core.Error import InvalidExchangeRateResponse

from twisted.trial import unittest
from twisted.internet import defer
from tests import util


class FeeFormatTest(unittest.TestCase):
    def test_fee_created_with_correct_inputs(self):
        fee_dict = {
            'currency':'USD',
            'amount': 10.0,
            'address': "bRcHraa8bYJZL7vkh5sNmGwPDERFUjGPP9"
        }
        fee = Fee(fee_dict)
        self.assertEqual(10.0, fee['amount'])
        self.assertEqual('USD', fee['currency'])

class FeeTest(unittest.TestCase):
    def setUp(self):
        util.resetTime(self)

    def test_fee_converts_to_lbc(self):
        fee = Fee({
            'currency':'USD',
            'amount': 10.0,
            'address': "bRcHraa8bYJZL7vkh5sNmGwPDERFUjGPP9"
            })

        rates = {
            'BTCLBC': {'spot': 3.0, 'ts': util.DEFAULT_ISO_TIME + 1},
            'USDBTC': {'spot': 2.0, 'ts': util.DEFAULT_ISO_TIME + 2}
        }
        manager = ExchangeRateManager.DummyExchangeRateManager(rates)
        result = manager.convert_currency(fee.currency, "LBC", fee.amount)
        self.assertEqual(60.0, result)

class GoogleBTCFeedTest(unittest.TestCase):

    @defer.inlineCallbacks
    def test_handle_response(self):
        feed = ExchangeRateManager.GoogleBTCFeed()

        response = '// [ { "id": "-2001" ,"t" : "USDBTC" ,"e" : "CURRENCY" ,"l" : "0.0008" ,"l_fix" : "" ,"l_cur" : "" ,"s": "0" ,"ltt":"" ,"lt" : "Feb 27, 10:21PM GMT" ,"lt_dts" : "2017-02-27T22:21:39Z" ,"c" : "-0.00001" ,"c_fix" : "" ,"cp" : "-0.917" ,"cp_fix" : "" ,"ccol" : "chr" ,"pcls_fix" : "" } ]'
        out = yield feed._handle_response(response)
        self.assertEqual(0.0008, out)

        # check negative trade price throws exception
        response = '// [ { "id": "-2001" ,"t" : "USDBTC" ,"e" : "CURRENCY" ,"l" : "-0.0008" ,"l_fix" : "" ,"l_cur" : "" ,"s": "0" ,"ltt":"" ,"lt" : "Feb 27, 10:21PM GMT" ,"lt_dts" : "2017-02-27T22:21:39Z" ,"c" : "-0.00001" ,"c_fix" : "" ,"cp" : "-0.917" ,"cp_fix" : "" ,"ccol" : "chr" ,"pcls_fix" : "" } ]'
        with self.assertRaises(InvalidExchangeRateResponse):
            out = yield feed._handle_response(response)


class LBRYioFeedTest(unittest.TestCase):
    @defer.inlineCallbacks
    def test_handle_response(self):
        feed = ExchangeRateManager.LBRYioFeed()

        response ='{\"data\": {\"fresh\": 0, \"lbc_usd\": 0.05863062523378918, \"lbc_btc\": 5.065289549855739e-05, \"btc_usd\": 1157.498}, \"success\": true, \"error\": null}'
        out = yield feed._handle_response(response)
        expected = 1.0 / 5.065289549855739e-05
        self.assertEqual(expected, out)

        response='{}'
        with self.assertRaises(InvalidExchangeRateResponse):
            out = yield feed._handle_response(response)

        response='{"success":true,"result":[]}'
        with self.assertRaises(InvalidExchangeRateResponse):
            out = yield feed._handle_response(response)



