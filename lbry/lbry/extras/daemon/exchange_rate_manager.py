import json
import time
import asyncio
import logging
from decimal import Decimal
from typing import Optional, Iterable, Type
from lbry.error import InvalidExchangeRateResponseError, CurrencyConversionError
from lbry.utils import aiohttp_request
from lbry.wallet.dewies import lbc_to_dewies

log = logging.getLogger(__name__)


class ExchangeRate:
    def __init__(self, market, spot, ts):
        if not int(time.time()) - ts < 600:
            raise ValueError('The timestamp is too dated.')
        if not spot > 0:
            raise ValueError('Spot must be greater than 0.')
        self.currency_pair = (market[0:3], market[3:6])
        self.spot = spot
        self.ts = ts

    def __repr__(self):
        return f"Currency pair:{self.currency_pair}, spot:{self.spot}, ts:{self.ts}"

    def as_dict(self):
        return {'spot': self.spot, 'ts': self.ts}


class MarketFeed:
    name: str
    market: str
    url: str
    params = {}
    fee = 0

    update_interval = 300
    request_timeout = 50

    def __init__(self):
        self.rate: Optional[float] = None
        self.last_check = 0
        self._last_response = None
        self._task: Optional[asyncio.Task] = None
        self.event = asyncio.Event()

    @property
    def has_rate(self):
        return self.rate is not None

    @property
    def is_online(self):
        return self.last_check+self.update_interval+self.request_timeout > time.time()

    def get_rate_from_response(self, response):
        raise NotImplementedError()

    async def get_response(self):
        async with aiohttp_request('get', self.url, params=self.params, timeout=self.request_timeout) as response:
            self._last_response = await response.json()
            return self._last_response

    async def get_rate(self):
        try:
            data = await self.get_response()
            rate = self.get_rate_from_response(data)
            rate = rate / (1.0 - self.fee)
            log.debug("Saving rate update %f for %s from %s", rate, self.market, self.name)
            self.rate = ExchangeRate(self.market, rate, int(time.time()))
            self.last_check = time.time()
            self.event.set()
            return self.rate
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            log.warning("Timed out fetching exchange rate from %s.", self.name)
        except json.JSONDecodeError as e:
            log.warning("Could not parse exchange rate response from %s: %s", self.name, e.doc)
        except InvalidExchangeRateResponseError as e:
            log.warning(str(e))
        except Exception as e:
            log.exception("Exchange rate error (%s from %s):", self.market, self.name)

    async def keep_updated(self):
        while True:
            await self.get_rate()
            await asyncio.sleep(self.update_interval)

    def start(self):
        if not self._task:
            self._task = asyncio.create_task(self.keep_updated())

    def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self.event.clear()


class BittrexFeed(MarketFeed):
    name = "Bittrex"
    market = "BTCLBC"
    url = "https://bittrex.com/api/v1.1/public/getmarkethistory"
    params = {'market': 'BTC-LBC', 'count': 50}
    fee = 0.0025

    def get_rate_from_response(self, json_response):
        if 'result' not in json_response:
            raise InvalidExchangeRateResponseError(self.name, 'result not found')
        trades = json_response['result']
        if len(trades) == 0:
            raise InvalidExchangeRateResponseError(self.name, 'trades not found')
        totals = sum([i['Total'] for i in trades])
        qtys = sum([i['Quantity'] for i in trades])
        if totals <= 0 or qtys <= 0:
            raise InvalidExchangeRateResponseError(self.name, 'quantities were not positive')
        vwap = totals / qtys
        return float(1.0 / vwap)


class LBRYFeed(MarketFeed):
    name = "lbry.com"
    market = "BTCLBC"
    url = "https://api.lbry.com/lbc/exchange_rate"

    def get_rate_from_response(self, json_response):
        if 'data' not in json_response:
            raise InvalidExchangeRateResponseError(self.name, 'result not found')
        return 1.0 / json_response['data']['lbc_btc']


class LBRYBTCFeed(LBRYFeed):
    market = "USDBTC"

    def get_rate_from_response(self, json_response):
        if 'data' not in json_response:
            raise InvalidExchangeRateResponseError(self.name, 'result not found')
        return 1.0 / json_response['data']['btc_usd']


class CryptonatorFeed(MarketFeed):
    name = "cryptonator.com"
    market = "BTCLBC"
    url = "https://api.cryptonator.com/api/ticker/btc-lbc"

    def get_rate_from_response(self, json_response):
        if 'ticker' not in json_response or len(json_response['ticker']) == 0 or \
                'success' not in json_response or json_response['success'] is not True:
            raise InvalidExchangeRateResponseError(self.name, 'result not found')
        return float(json_response['ticker']['price'])


class CryptonatorBTCFeed(CryptonatorFeed):
    market = "USDBTC"
    url = "https://api.cryptonator.com/api/ticker/usd-btc"


FEEDS: Iterable[Type[MarketFeed]] = (
    LBRYFeed,
    LBRYBTCFeed,
    BittrexFeed,
    CryptonatorFeed,
    CryptonatorBTCFeed,
)


class ExchangeRateManager:
    def __init__(self, feeds=FEEDS):
        self.market_feeds = [Feed() for Feed in feeds]

    def wait(self):
        return asyncio.wait(
            [feed.event.wait() for feed in self.market_feeds],
        )

    def start(self):
        log.info("Starting exchange rate manager")
        for feed in self.market_feeds:
            feed.start()

    def stop(self):
        log.info("Stopping exchange rate manager")
        for source in self.market_feeds:
            source.stop()

    def convert_currency(self, from_currency, to_currency, amount):
        rates = [market.rate for market in self.market_feeds]
        log.debug("Converting %f %s to %s, rates: %s" % (amount, from_currency, to_currency, rates))
        if from_currency == to_currency:
            return round(amount, 8)

        for market in self.market_feeds:
            if (market.has_rate and market.is_online and
                    market.rate.currency_pair == (from_currency, to_currency)):
                return round(amount * Decimal(market.rate.spot), 8)
        for market in self.market_feeds:
            if (market.has_rate and market.is_online and
                    market.rate.currency_pair[0] == from_currency):
                return round(self.convert_currency(
                    market.rate.currency_pair[1], to_currency, amount * Decimal(market.rate.spot)), 8)
        raise CurrencyConversionError(
            f'Unable to convert {amount} from {from_currency} to {to_currency}')

    def to_dewies(self, currency, amount) -> int:
        converted = self.convert_currency(currency, "LBC", amount)
        return lbc_to_dewies(str(converted))

    def fee_dict(self):
        return {market: market.rate.as_dict() for market in self.market_feeds}
