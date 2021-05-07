import asyncio
from decimal import Decimal
from time import time
from lbry.schema.claim import Claim
from lbry.extras.daemon.exchange_rate_manager import (
    ExchangeRate, ExchangeRateManager, CurrencyConversionError,
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
        await manager.wait()
        for feed in manager.market_feeds:  # no rate but it tried
            self.assertFalse(feed.has_rate)
            self.assertTrue(feed.event.is_set())
        self.addCleanup(manager.stop)

    async def test_median_rate_used(self):
        manager = ExchangeRateManager([BittrexBTCFeed, CoinExBTCFeed])
        for feed in manager.market_feeds:
            feed.last_check = time()
        bittrex, coinex = manager.market_feeds
        bittrex.rate = ExchangeRate(bittrex.market, 1.0, time())
        coinex.rate = ExchangeRate(coinex.market, 2.0, time())
        coinex.rate = ExchangeRate(coinex.market, 3.0, time())
        self.assertEqual(14.0, manager.convert_currency("BTC", "LBC", Decimal(7.0)))
        coinex.rate.spot = 4.0
        self.assertEqual(17.5, manager.convert_currency("BTC", "LBC", Decimal(7.0)))
