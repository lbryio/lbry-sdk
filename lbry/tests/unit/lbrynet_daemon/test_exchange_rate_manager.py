import asyncio
from decimal import Decimal
from time import time
from lbry.schema.claim import Claim
from lbry.extras.daemon.exchange_rate_manager import (
    ExchangeRate, ExchangeRateManager, CurrencyConversionError,
    LBRYFeed, LBRYBTCFeed,
    CryptonatorFeed, CryptonatorBTCFeed,
    BittrexFeed,
)
from torba.testcase import AsyncioTestCase
from lbry.error import InvalidExchangeRateResponseError


class DummyExchangeRateManager(ExchangeRateManager):
    def __init__(self, market_feeds, rates):
        self.market_feeds = market_feeds
        for feed in self.market_feeds:
            feed.last_check = time()
            feed.rate = ExchangeRate(feed.market, rates[feed.market], time())


def get_dummy_exchange_rate_manager():
    return DummyExchangeRateManager(
        [LBRYFeed(), LBRYBTCFeed()],
        {'BTCLBC': 3.0, 'USDBTC': 2.0}
    )


class ExchangeRateTests(AsyncioTestCase):

    def test_invalid_rates(self):
        with self.assertRaises(ValueError):
            ExchangeRate('USDBTC', 0, time())
        with self.assertRaises(ValueError):
            ExchangeRate('USDBTC', -1, time())

    def test_fee_converts_to_lbc(self):
        fee = Claim().stream.fee
        fee.usd = Decimal(10.0)
        fee.address = "bRcHraa8bYJZL7vkh5sNmGwPDERFUjGPP9"
        manager = get_dummy_exchange_rate_manager()
        result = manager.convert_currency(fee.currency, "LBC", fee.amount)
        self.assertEqual(60.0, result)

    def test_missing_feed(self):
        fee = Claim().stream.fee
        fee.usd = Decimal(1.0)
        fee.address = "bRcHraa8bYJZL7vkh5sNmGwPDERFUjGPP9"
        manager = DummyExchangeRateManager([LBRYFeed()], {'BTCLBC': 1.0})
        with self.assertRaises(CurrencyConversionError):
            manager.convert_currency(fee.currency, "LBC", fee.amount)

    def test_lbry_feed_response(self):
        feed = LBRYFeed()
        out = feed.get_rate_from_response({
            'data': {
                'fresh': 0, 'lbc_usd': 0.05863062523378918,
                'lbc_btc': 5.065289549855739e-05, 'btc_usd': 1157.498
            },
            'success': True,
            'error': None
        })
        self.assertEqual(1.0 / 5.065289549855739e-05, out)
        with self.assertRaises(InvalidExchangeRateResponseError):
            feed.get_rate_from_response({})
        with self.assertRaises(InvalidExchangeRateResponseError):
            feed.get_rate_from_response({
                "success": True,
                "result": []
            })

    def test_lbry_btc_feed_response(self):
        feed = LBRYBTCFeed()
        out = feed.get_rate_from_response({
            'data': {
                'fresh': 0, 'lbc_usd': 0.05863062523378918,
                'lbc_btc': 5.065289549855739e-05, 'btc_usd': 1157.498
            },
            'success': True,
            'error': None
        })
        self.assertEqual(1.0 / 1157.498, out)
        with self.assertRaises(InvalidExchangeRateResponseError):
            feed.get_rate_from_response({})
        with self.assertRaises(InvalidExchangeRateResponseError):
            feed.get_rate_from_response({
                "success": True,
                "result": {}
            })

    def test_cryptonator_lbc_feed_response(self):
        feed = CryptonatorFeed()
        out = feed.get_rate_from_response({
            'ticker': {
                'base': 'BTC', 'target': 'LBC', 'price': 23657.44026496,
                'volume': '', 'change': -5.59806916,
            },
            'timestamp': 1507470422,
            'success': True,
            'error': ""
        })
        self.assertEqual(23_657.44026496, out)
        with self.assertRaises(InvalidExchangeRateResponseError):
            feed.get_rate_from_response({})
        with self.assertRaises(InvalidExchangeRateResponseError):
            feed.get_rate_from_response({
                "success": True,
                "ticker": {}
            })

    def test_cryptonator_btc_feed_response(self):
        feed = CryptonatorBTCFeed()
        out = feed.get_rate_from_response({
            'ticker': {
                'base': 'BTC', 'target': 'LBC', 'price': 0.00022123,
                'volume': '', 'change': -0.00000259,
            },
            'timestamp': 1507471141,
            'success': True,
            'error': ''
        })
        self.assertEqual(0.00022123, out)
        with self.assertRaises(InvalidExchangeRateResponseError):
            feed.get_rate_from_response({})
        with self.assertRaises(InvalidExchangeRateResponseError):
            feed.get_rate_from_response({
                "success": True,
                "ticker": {}
            })

    def test_bittrex_feed_response(self):
        feed = BittrexFeed()
        out = feed.get_rate_from_response({
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
        })
        self.assertEqual(1.0 / ((0.00090980+0.00686151) / (56.12611239+430.99988180)), out)
        with self.assertRaises(InvalidExchangeRateResponseError):
            feed.get_rate_from_response({})
        with self.assertRaises(InvalidExchangeRateResponseError):
            feed.get_rate_from_response({
                "success": True,
                "result": []
            })


class BadMarketFeed(LBRYFeed):

    def get_response(self):
        raise InvalidExchangeRateResponseError(self.name, 'bad stuff')


class ExchangeRateManagerTests(AsyncioTestCase):

    async def test_get_rate_failure_retrieved(self):
        manager = ExchangeRateManager([BadMarketFeed])
        manager.start()
        await asyncio.sleep(1)
        self.addCleanup(manager.stop)
