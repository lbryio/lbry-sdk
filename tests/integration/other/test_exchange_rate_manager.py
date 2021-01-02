from decimal import Decimal
from lbry.testcase import AsyncioTestCase
from lbry.extras.daemon.exchange_rate_manager import ExchangeRate, ExchangeRateManager, FEEDS


class TestExchangeRateManager(AsyncioTestCase):
    async def test_exchange_rate_manager(self):
        # TODO: re-enable cryptonator.com
        # TODO: this uses real exchange rate feeds... update to use mocks
        manager = ExchangeRateManager(FEEDS)
        manager.start()
        self.addCleanup(manager.stop)
        for feed in manager.market_feeds:
            self.assertFalse(feed.is_online)
            self.assertIsNone(feed.rate)
        await manager.wait()
        for feed in manager.market_feeds:
            self.assertTrue(feed.is_online)
            self.assertIsInstance(feed.rate, ExchangeRate)
        lbc = manager.convert_currency('USD', 'LBC', Decimal('0.01'))
        self.assertGreaterEqual(lbc, 0.01)
        self.assertLessEqual(lbc, 10.0)
