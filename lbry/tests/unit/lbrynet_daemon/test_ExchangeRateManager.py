import unittest
from decimal import Decimal
from lbrynet.schema.claim import Claim
from lbrynet.extras.daemon import exchange_rate_manager
from lbrynet.error import InvalidExchangeRateResponse
from tests import test_utils


class BTCLBCFeed(exchange_rate_manager.MarketFeed):
    def __init__(self):
        super().__init__(
            "BTCLBC",
            "market name",
            "derp.com",
            None,
            0.0
        )


class USDBTCFeed(exchange_rate_manager.MarketFeed):
    def __init__(self):
        super().__init__(
            "USDBTC",
            "market name",
            "derp.com",
            None,
            0.0
        )


class DummyExchangeRateManager(exchange_rate_manager.ExchangeRateManager):
    def __init__(self, market_feeds, rates):
        self.market_feeds = market_feeds
        for feed in self.market_feeds:
            feed.rate = exchange_rate_manager.ExchangeRate(
                feed.market, rates[feed.market]['spot'], rates[feed.market]['ts'])


def get_dummy_exchange_rate_manager(time):
    rates = {
        'BTCLBC': {'spot': 3.0, 'ts': time.time() + 1},
        'USDBTC': {'spot': 2.0, 'ts': time.time() + 2}
    }
    return DummyExchangeRateManager([BTCLBCFeed(), USDBTCFeed()], rates)


class ExchangeRateTest(unittest.TestCase):
    def setUp(self):
        test_utils.reset_time(self)

    def test_invalid_rates(self):
        with self.assertRaises(ValueError):
            exchange_rate_manager.ExchangeRate('USDBTC', 0, test_utils.DEFAULT_ISO_TIME)
        with self.assertRaises(ValueError):
            exchange_rate_manager.ExchangeRate('USDBTC', -1, test_utils.DEFAULT_ISO_TIME)


class FeeTest(unittest.TestCase):
    def setUp(self):
        test_utils.reset_time(self)

    def test_fee_converts_to_lbc(self):
        fee = Claim().stream.fee
        fee.usd = Decimal(10.0)
        fee.address = "bRcHraa8bYJZL7vkh5sNmGwPDERFUjGPP9"

        rates = {
            'BTCLBC': {'spot': 3.0, 'ts': test_utils.DEFAULT_ISO_TIME + 1},
            'USDBTC': {'spot': 2.0, 'ts': test_utils.DEFAULT_ISO_TIME + 2}
        }

        market_feeds = [BTCLBCFeed(), USDBTCFeed()]
        manager = DummyExchangeRateManager(market_feeds, rates)
        result = manager.convert_currency(fee.currency, "LBC", fee.amount)
        self.assertEqual(60.0, result)

    def test_missing_feed(self):
        # test when a feed is missing for conversion
        fee = Claim().stream.fee
        fee.usd = Decimal(1.0)
        fee.address = "bRcHraa8bYJZL7vkh5sNmGwPDERFUjGPP9"

        rates = {
            'BTCLBC': {'spot': 1.0, 'ts': test_utils.DEFAULT_ISO_TIME + 1},
        }
        market_feeds = [BTCLBCFeed()]
        manager = DummyExchangeRateManager(market_feeds, rates)
        with self.assertRaises(Exception):
            manager.convert_currency(fee.currency, "LBC", fee.amount)


class LBRYioFeedTest(unittest.TestCase):
    def test_handle_response(self):
        feed = exchange_rate_manager.LBRYioFeed()

        response = '{\"data\": {\"fresh\": 0, \"lbc_usd\": 0.05863062523378918, ' \
                   '\"lbc_btc\": 5.065289549855739e-05, \"btc_usd\": 1157.498}, ' \
                   '\"success\": true, \"error\": null}'
        out = feed._handle_response(response)
        expected = 1.0 / 5.065289549855739e-05
        self.assertEqual(expected, out)

        response = '{}'
        with self.assertRaises(InvalidExchangeRateResponse):
            feed._handle_response(response)

        response = '{"success":true,"result":[]}'
        with self.assertRaises(InvalidExchangeRateResponse):
            feed._handle_response(response)


class TestExchangeRateFeeds(unittest.TestCase):
    def test_handle_lbryio_btc_response(self):
        feed = exchange_rate_manager.LBRYioBTCFeed()

        response = '{\"data\": {\"fresh\": 0, \"lbc_usd\": 0.05863062523378918, ' \
                   '\"lbc_btc\": 5.065289549855739e-05, \"btc_usd\": 1157.498}, ' \
                   '\"success\": true, \"error\": null}'
        out = feed._handle_response(response)
        expected = 1.0 / 1157.498
        self.assertEqual(expected, out)

        response = '{}'
        with self.assertRaises(InvalidExchangeRateResponse):
            out = feed._handle_response(response)

        response = '{"success":true,"result":[]}'
        with self.assertRaises(InvalidExchangeRateResponse):
            out = feed._handle_response(response)

    def test_handle_cryptonator_lbc_response(self):
        feed = exchange_rate_manager.CryptonatorFeed()

        response = '{\"ticker\":{\"base\":\"BTC\",\"target\":\"LBC\",\"price\":\"23657.44026496\"' \
                   ',\"volume\":\"\",\"change\":\"-5.59806916\"},\"timestamp\":1507470422' \
                   ',\"success\":true,\"error\":\"\"}'
        out = feed._handle_response(response)
        expected = 23657.44026496
        self.assertEqual(expected, out)

        response = '{}'
        with self.assertRaises(InvalidExchangeRateResponse):
            feed._handle_response(response)

        response = '{"success":true,"ticker":{}}'
        with self.assertRaises(InvalidExchangeRateResponse):
            feed._handle_response(response)

    def test_handle_cryptonator_btc_response(self):
        feed = exchange_rate_manager.CryptonatorBTCFeed()

        response = '{\"ticker\":{\"base\":\"USD\",\"target\":\"BTC\",\"price\":\"0.00022123\",' \
                   '\"volume\":\"\",\"change\":\"-0.00000259\"},\"timestamp\":1507471141,' \
                   '\"success\":true,\"error\":\"\"}'
        out = feed._handle_response(response)
        expected = 0.00022123
        self.assertEqual(expected, out)

        response = '{}'
        with self.assertRaises(InvalidExchangeRateResponse):
            feed._handle_response(response)

        response = '{"success":true,"ticker":{}}'
        with self.assertRaises(InvalidExchangeRateResponse):
            feed._handle_response(response)

    def test_handle_bittrex_response(self):
        feed = exchange_rate_manager.BittrexFeed()

        response = '{"success":true,"message":"","result":[{"Id":6902471,"TimeStamp":"2017-02-2'\
        '7T23:41:52.213","Quantity":56.12611239,"Price":0.00001621,"Total":0.00090980,"FillType":"'\
        'PARTIAL_FILL","OrderType":"SELL"},{"Id":6902403,"TimeStamp":"2017-02-27T23:31:40.463","Qu'\
        'antity":430.99988180,"Price":0.00001592,"Total":0.00686151,"FillType":"PARTIAL_FILL","Ord'\
        'erType":"SELL"}]}'
        out = feed._handle_response(response)
        expected = 1.0 / ((0.00090980+0.00686151) / (56.12611239+430.99988180))
        self.assertEqual(expected, out)

        response = '{}'
        with self.assertRaises(InvalidExchangeRateResponse):
            feed._handle_response(response)

        response = '{"success":true,"result":[]}'
        with self.assertRaises(InvalidExchangeRateResponse):
            feed._handle_response(response)
