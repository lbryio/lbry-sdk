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
from lbry.testcase import AsyncioTestCase, FakeExchangeRateManager, get_fake_exchange_rate_manager
from lbry.error import InvalidExchangeRateResponseError


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
        manager = get_fake_exchange_rate_manager()
        result = manager.convert_currency(fee.currency, "LBC", fee.amount)
        self.assertEqual(60.0, result)

    def test_missing_feed(self):
        fee = Claim().stream.fee
        fee.usd = Decimal(1.0)
        fee.address = "bRcHraa8bYJZL7vkh5sNmGwPDERFUjGPP9"
        manager = FakeExchangeRateManager([LBRYFeed()], {'BTCLBC': 1.0})
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
            "symbol": "LBC-BTC",
            "lastTradeRate": "0.00000323",
            "bidRate": "0.00000322",
            "askRate": "0.00000327"
        })
        self.assertEqual(1.0 / 0.00000323, out)
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
