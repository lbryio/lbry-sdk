from decimal import Decimal
from lbry.testcase import AsyncioTestCase
from lbry.extras.daemon.exchange_rate_manager import ExchangeRate, ExchangeRateManager, FEEDS


class TestExchangeRateManager(AsyncioTestCase):
    async def test_exchange_rate_manager(self):
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
            # print(f'{feed.name} - {feed.market} - {feed.rate.spot}')
        lbc = manager.convert_currency('USD', 'LBC', Decimal('1.0'))
        self.assertGreaterEqual(lbc, 2.0)
        self.assertLessEqual(lbc, 10.0)
        lbc = manager.convert_currency('BTC', 'LBC', Decimal('0.01'))
        self.assertGreaterEqual(lbc, 1_000)
        self.assertLessEqual(lbc, 4_000)
