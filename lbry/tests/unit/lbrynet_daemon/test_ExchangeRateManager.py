import unittest
import logging
from decimal import Decimal
from lbry.schema.claim import Claim
from lbry.extras.daemon import exchange_rate_manager
from torba.testcase import AsyncioTestCase
from lbry.error import InvalidExchangeRateResponseError
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

        response = {
            'data': {
                'fresh': 0, 'lbc_usd': 0.05863062523378918, 'lbc_btc': 5.065289549855739e-05, 'btc_usd': 1157.498
            },
            'success': True,
            'error': None
        }
        out = feed._handle_response(response)
        expected = 1.0 / 5.065289549855739e-05
        self.assertEqual(expected, out)

        response = {}
        with self.assertRaises(InvalidExchangeRateResponseError):
            feed._handle_response(response)

        response = {
            "success": True,
            "result": []
        }
        with self.assertRaises(InvalidExchangeRateResponseError):
            feed._handle_response(response)


class TestExchangeRateFeeds(unittest.TestCase):
    def test_handle_lbryio_btc_response(self):
        feed = exchange_rate_manager.LBRYioBTCFeed()

        response = {
            'data': {
                'fresh': 0, 'lbc_usd': 0.05863062523378918, 'lbc_btc': 5.065289549855739e-05, 'btc_usd': 1157.498
            },
            'success': True,
            'error': None
        }
        out = feed._handle_response(response)
        expected = 1.0 / 1157.498
        self.assertEqual(expected, out)

        response = {}
        with self.assertRaises(InvalidExchangeRateResponseError):
            out = feed._handle_response(response)

        response = {
            "success": True,
            "result": {}
        }
        with self.assertRaises(InvalidExchangeRateResponseError):
            out = feed._handle_response(response)

    def test_handle_cryptonator_lbc_response(self):
        feed = exchange_rate_manager.CryptonatorFeed()

        response = {
            'ticker': {
                'base': 'BTC', 'target': 'LBC', 'price': 23657.44026496, 'volume': '', 'change': -5.59806916,
            },
            'timestamp': 1507470422,
            'success': True,
            'error': ""
        }
        out = feed._handle_response(response)
        expected = 23657.44026496
        self.assertEqual(expected, out)

        response = {}
        with self.assertRaises(InvalidExchangeRateResponseError):
            feed._handle_response(response)

        response = {
            "success": True,
            "ticker": {}
        }
        with self.assertRaises(InvalidExchangeRateResponseError):
            feed._handle_response(response)

    def test_handle_cryptonator_btc_response(self):
        feed = exchange_rate_manager.CryptonatorBTCFeed()

        response = {
            'ticker': {
                'base': 'BTC', 'target': 'LBC', 'price': 0.00022123, 'volume': '', 'change': -0.00000259,
            },
            'timestamp': 1507471141,
            'success': True,
            'error': ''
        }

        out = feed._handle_response(response)
        expected = 0.00022123
        self.assertEqual(expected, out)

        response = '{}'
        with self.assertRaises(InvalidExchangeRateResponseError):
            feed._handle_response(response)

        response = {
            "success": True,
            "ticker": {}
        }
        with self.assertRaises(InvalidExchangeRateResponseError):
            feed._handle_response(response)

    def test_handle_bittrex_response(self):
        feed = exchange_rate_manager.BittrexFeed()

        response = {
            "success": True,
            "message": "",
            "result": [
                {
                    'Id': 6902471, 'TimeStamp': '2017-02-27T23:41:52.213', 'Quantity': 56.12611239,
                    "Price": 0.00001621, "Total": 0.00090980, "FillType": "PARTIAL_FILL", "OrderType": "SELL"
                },
                {
                    "Id": 6902403, "TimeStamp": "2017-02-27t23:31:40.463", "Quantity": 430.99988180,
                    "Price": 0.00001592, "Total": 0.00686151, "FillType": "PARTIAL_FILL", "OrderType": "SELL"
                }
            ]
        }
        out = feed._handle_response(response)
        expected = 1.0 / ((0.00090980+0.00686151) / (56.12611239+430.99988180))
        self.assertEqual(expected, out)

        response = {}
        with self.assertRaises(InvalidExchangeRateResponseError):
            feed._handle_response(response)

        response = {
            "success": True,
            "result": []
        }
        with self.assertRaises(InvalidExchangeRateResponseError):
            feed._handle_response(response)


class TestMarketFeed(AsyncioTestCase):
    def setUp(self):
        self.feed = exchange_rate_manager.MarketFeed('some market', 'some name', 'some url', {'param': 1}, 0.005)

    def test_save_price(self):
        with self.assertLogs('lbry.extras.daemon.exchange_rate_manager', logging.DEBUG) as cm:
            self.feed._save_price(1)
        self.assertIn(self.feed.market, ' '.join(cm.output))
        self.assertIn(self.feed.name, ' '.join(cm.output))
        self.assertTrue(self.feed.is_online())
        self.assertIsNotNone(self.feed.rate)

        with self.assertRaises(ValueError):
            self.feed._save_price(0)

        with self.assertRaises(TypeError):
            self.feed._save_price('not a price')

    async def test_update_price(self):
        def mock_handle_response(json_obj):
            return json_obj['data']['lbc_btc']

        async def get_response_body_mock(self):
            return '{\"data\": {\"fresh\": 0, \"lbc_usd\": 0.05863062523378918, ' \
                   '\"lbc_btc\": 5.065289549855739e-05, \"btc_usd\": 1157.498}, ' \
                   '\"success\": true, \"error\": null}'

        self.feed._handle_response = mock_handle_response

        with unittest.mock.patch.object(
                exchange_rate_manager.AioHttpManager, 'get_response_body', get_response_body_mock
        ):
            await self.feed._update_price()
        self.assertEqual(self.feed.rate.spot, 5.090743266186672e-05)
        self.assertTrue(self.feed.is_online())

        async def get_response_body_mock(self):
            return '<h1>not a json</h1>'

        with unittest.mock.patch.object(
            exchange_rate_manager.AioHttpManager, 'get_response_body', get_response_body_mock
        ), self.assertRaises(ValueError):
            await self.feed._update_price()


class TestDeserializer(unittest.TestCase):
    def test_valid_json(self):
        deserializer = exchange_rate_manager.Deserializer('json')
        body = '{"data": "valid json", "some_float": 3.1415, "and_a_dict": {"value": true}}'
        json_obj = deserializer.deserialize(body)
        self.assertEqual(json_obj['data'], 'valid json')
        self.assertEqual(json_obj['some_float'], 3.1415)
        self.assertTrue(json_obj['and_a_dict']['value'])

    def test_invalid_json(self):
        def assert_raises_error(body):
            with self.assertRaises(ValueError):
                deserializer.deserialize(body)

        deserializer = exchange_rate_manager.Deserializer('json')
        assert_raises_error('<h1>not a json</h1>')
        assert_raises_error('')
        assert_raises_error('{')

    def test_invalid_content_type(self):
        with self.assertRaises(ValueError):
            exchange_rate_manager.Deserializer('not a format')


class TestAioHttpManager(AsyncioTestCase):
    async def test_get_response_body(self):
        async def make_request_mock(self):
            response = unittest.mock.Mock(
                headers={'Content-Type': 'jibberish'}
            )
            return response

        manager = exchange_rate_manager.AioHttpManager('some url', 'some params', 'json')
        with unittest.mock.patch.object(
                exchange_rate_manager.AioHttpManager, '_make_request', make_request_mock
        ), self.assertRaises(InvalidExchangeRateResponseError):
            await manager.get_response_body()
