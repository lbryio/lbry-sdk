import asyncio
import logging
from decimal import Decimal
from lbry.testcase import AsyncioTestCase
from lbry.extras.daemon.exchange_rate_manager import ExchangeRate, ExchangeRateManager, FEEDS, MarketFeed


class TestExchangeRateManager(AsyncioTestCase):
    async def test_exchange_rate_manager(self):
        manager = ExchangeRateManager(FEEDS)
        manager.start()
        self.addCleanup(manager.stop)
        for feed in manager.market_feeds:
            self.assertFalse(feed.is_online)
            self.assertIsNone(feed.rate)
        await manager.wait()
        failures = set()
        for feed in manager.market_feeds:
            if feed.is_online:
                self.assertIsInstance(feed.rate, ExchangeRate)
            else:
                failures.add(feed.name)
                self.assertFalse(feed.has_rate)
        self.assertLessEqual(len(failures), 1, f"feed failures: {failures}. Please check exchange rate feeds!")
        lbc = manager.convert_currency('USD', 'LBC', Decimal('1.0'))
        self.assertGreaterEqual(lbc, 2.0)
        self.assertLessEqual(lbc, 80.0)
        lbc = manager.convert_currency('BTC', 'LBC', Decimal('0.01'))
        self.assertGreaterEqual(lbc, 1_000)
        self.assertLessEqual(lbc, 30_000)

    async def test_it_handles_feed_being_offline(self):
        class FakeFeed(MarketFeed):
            name = "fake"
            url = "http://impossi.bru"
        manager = ExchangeRateManager((FakeFeed,))
        manager.start()
        self.addCleanup(manager.stop)
        for feed in manager.market_feeds:
            self.assertFalse(feed.is_online)
            self.assertIsNone(feed.rate)
        await asyncio.wait_for(manager.wait(), 2)
        for feed in manager.market_feeds:
            self.assertFalse(feed.is_online)
            self.assertFalse(feed.has_rate)
