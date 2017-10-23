from lbryschema.fee import Fee
from lbrynet.daemon import ExchangeRateManager
from lbrynet.core.Error import InvalidExchangeRateResponse
from twisted.trial import unittest
from twisted.internet import defer
from lbrynet.tests import util
from lbrynet.tests.mocks import ExchangeRateManager as DummyExchangeRateManager
from lbrynet.tests.mocks import BTCLBCFeed, USDBTCFeed


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

    def test_fee_zero(self):
        fee_dict = {
            'currency':'LBC',
            'amount': 0.0,
            'address': "bRcHraa8bYJZL7vkh5sNmGwPDERFUjGPP9"
        }
        fee = Fee(fee_dict)
        self.assertEqual(0.0, fee['amount'])
        self.assertEqual('LBC', fee['currency'])


class ExchangeRateTest(unittest.TestCase):
    def setUp(self):
        util.resetTime(self)

    def test_invalid_rates(self):
        with self.assertRaises(ValueError):
            ExchangeRateManager.ExchangeRate('USDBTC', 0, util.DEFAULT_ISO_TIME)
        with self.assertRaises(ValueError):
            ExchangeRateManager.ExchangeRate('USDBTC', -1, util.DEFAULT_ISO_TIME)


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

        market_feeds = [BTCLBCFeed(), USDBTCFeed()]
        manager = DummyExchangeRateManager(market_feeds, rates)
        result = manager.convert_currency(fee.currency, "LBC", fee.amount)
        self.assertEqual(60.0, result)

    def test_missing_feed(self):
        # test when a feed is missing for conversion
        fee = Fee({
            'currency':'USD',
            'amount': 1.0,
            'address': "bRcHraa8bYJZL7vkh5sNmGwPDERFUjGPP9"
            })

        rates = {
            'BTCLBC': {'spot': 1.0, 'ts': util.DEFAULT_ISO_TIME + 1},
        }
        market_feeds = [BTCLBCFeed()]
        manager = DummyExchangeRateManager(market_feeds, rates)
        with self.assertRaises(Exception):
            manager.convert_currency(fee.currency, "LBC", fee.amount)


class LBRYioFeedTest(unittest.TestCase):
    @defer.inlineCallbacks
    def test_handle_response(self):
        feed = ExchangeRateManager.LBRYioFeed()

        response = '{\"data\": {\"fresh\": 0, \"lbc_usd\": 0.05863062523378918, ' \
                   '\"lbc_btc\": 5.065289549855739e-05, \"btc_usd\": 1157.498}, ' \
                   '\"success\": true, \"error\": null}'
        out = yield feed._handle_response(response)
        expected = 1.0 / 5.065289549855739e-05
        self.assertEqual(expected, out)

        response = '{}'
        with self.assertRaises(InvalidExchangeRateResponse):
            out = yield feed._handle_response(response)

        response = '{"success":true,"result":[]}'
        with self.assertRaises(InvalidExchangeRateResponse):
            out = yield feed._handle_response(response)


class LBRYioBTCFeedTest(unittest.TestCase):
    @defer.inlineCallbacks
    def test_handle_response(self):
        feed = ExchangeRateManager.LBRYioBTCFeed()

        response = '{\"data\": {\"fresh\": 0, \"lbc_usd\": 0.05863062523378918, ' \
                   '\"lbc_btc\": 5.065289549855739e-05, \"btc_usd\": 1157.498}, ' \
                   '\"success\": true, \"error\": null}'
        out = yield feed._handle_response(response)
        expected = 1.0 / 1157.498
        self.assertEqual(expected, out)

        response = '{}'
        with self.assertRaises(InvalidExchangeRateResponse):
            out = yield feed._handle_response(response)

        response = '{"success":true,"result":[]}'
        with self.assertRaises(InvalidExchangeRateResponse):
            out = yield feed._handle_response(response)

class CryptonatorFeedTest(unittest.TestCase):
    @defer.inlineCallbacks
    def test_handle_response(self):
        feed = ExchangeRateManager.CryptonatorFeed()

        response = '{\"ticker\":{\"base\":\"BTC\",\"target\":\"LBC\",\"price\":\"23657.44026496\"' \
                   ',\"volume\":\"\",\"change\":\"-5.59806916\"},\"timestamp\":1507470422' \
                   ',\"success\":true,\"error\":\"\"}'
        out = yield feed._handle_response(response)
        expected = 23657.44026496
        self.assertEqual(expected, out)

        response = '{}'
        with self.assertRaises(InvalidExchangeRateResponse):
            out = yield feed._handle_response(response)

        response = '{"success":true,"ticker":{}}'
        with self.assertRaises(InvalidExchangeRateResponse):
            out = yield feed._handle_response(response)

class CryptonatorBTCFeedTest(unittest.TestCase):
    @defer.inlineCallbacks
    def test_handle_response(self):
        feed = ExchangeRateManager.CryptonatorBTCFeed()

        response = '{\"ticker\":{\"base\":\"USD\",\"target\":\"BTC\",\"price\":\"0.00022123\",' \
                   '\"volume\":\"\",\"change\":\"-0.00000259\"},\"timestamp\":1507471141,' \
                   '\"success\":true,\"error\":\"\"}'
        out = yield feed._handle_response(response)
        expected = 0.00022123
        self.assertEqual(expected, out)

        response = '{}'
        with self.assertRaises(InvalidExchangeRateResponse):
            out = yield feed._handle_response(response)

        response = '{"success":true,"ticker":{}}'
        with self.assertRaises(InvalidExchangeRateResponse):
            out = yield feed._handle_response(response)


class BittrexFeedTest(unittest.TestCase):

    @defer.inlineCallbacks
    def test_handle_response(self):
        feed = ExchangeRateManager.BittrexFeed()

        response = '{"success":true,"message":"","result":[{"Id":6902471,"TimeStamp":"2017-02-2'\
        '7T23:41:52.213","Quantity":56.12611239,"Price":0.00001621,"Total":0.00090980,"FillType":"'\
        'PARTIAL_FILL","OrderType":"SELL"},{"Id":6902403,"TimeStamp":"2017-02-27T23:31:40.463","Qu'\
        'antity":430.99988180,"Price":0.00001592,"Total":0.00686151,"FillType":"PARTIAL_FILL","Ord'\
        'erType":"SELL"}]}'
        out = yield feed._handle_response(response)
        expected = 1.0 / ((0.00090980+0.00686151) / (56.12611239+430.99988180))
        self.assertEqual(expected, out)

        response = '{}'
        with self.assertRaises(InvalidExchangeRateResponse):
            out = yield feed._handle_response(response)

        response = '{"success":true,"result":[]}'
        with self.assertRaises(InvalidExchangeRateResponse):
            out = yield feed._handle_response(response)

