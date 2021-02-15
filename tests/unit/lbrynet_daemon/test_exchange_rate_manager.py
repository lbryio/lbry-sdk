import asyncio
from decimal import Decimal
from time import time
from lbry.schema.claim import Claim
from lbry.extras.daemon.exchange_rate_manager import (
    ExchangeRate, ExchangeRateManager, CurrencyConversionError,
    CryptonatorUSDFeed, CryptonatorBTCFeed,
    BittrexUSDFeed, BittrexBTCFeed,
    CoinExBTCFeed
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
        self.assertEqual(20.0, result)

    def test_missing_feed(self):
        fee = Claim().stream.fee
        fee.usd = Decimal(1.0)
        fee.address = "bRcHraa8bYJZL7vkh5sNmGwPDERFUjGPP9"
        manager = FakeExchangeRateManager([BittrexBTCFeed()], {'BTCLBC': 1.0})
        with self.assertRaises(CurrencyConversionError):
            manager.convert_currency(fee.currency, "LBC", fee.amount)

    def test_cryptonator_lbc_feed_response(self):
        feed = CryptonatorUSDFeed()
        out = feed.get_rate_from_response({
            'ticker': {
                'base': 'USD', 'target': 'LBC', 'price': 23657.44026496,
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
        feed = BittrexBTCFeed()
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


class BadMarketFeed(BittrexUSDFeed):

    def get_response(self):
        raise InvalidExchangeRateResponseError(self.name, 'bad stuff')


class ExchangeRateManagerTests(AsyncioTestCase):

    async def test_get_rate_failure_retrieved(self):
        manager = ExchangeRateManager([BadMarketFeed])
        manager.start()
        await asyncio.sleep(1)
        self.addCleanup(manager.stop)

    async def test_median_rate_used(self):
        manager = ExchangeRateManager([BittrexBTCFeed, CryptonatorBTCFeed, CoinExBTCFeed])
        for feed in manager.market_feeds:
            feed.last_check = time()
        bittrex, cryptonator, coinex = manager.market_feeds
        bittrex.rate = ExchangeRate(bittrex.market, 1.0, time())
        cryptonator.rate = ExchangeRate(cryptonator.market, 2.0, time())
        coinex.rate = ExchangeRate(coinex.market, 3.0, time())
        self.assertEqual(14.0, manager.convert_currency("BTC", "LBC", Decimal(7.0)))
        cryptonator.rate.spot = 4.0
        self.assertEqual(21.0, manager.convert_currency("BTC", "LBC", Decimal(7.0)))
