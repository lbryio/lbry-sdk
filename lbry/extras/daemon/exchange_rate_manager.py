import json
import time
import asyncio
import logging
from statistics import median
from decimal import Decimal
from typing import Optional, Iterable, Type
from aiohttp.client_exceptions import ContentTypeError, ClientConnectionError
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
    name: str = ""
    market: str = ""
    url: str = ""
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

    def get_rate_from_response(self, json_response):
        raise NotImplementedError()

    async def get_response(self):
        async with aiohttp_request(
                'get', self.url, params=self.params,
                timeout=self.request_timeout, headers={"User-Agent": "lbrynet"}
        ) as response:
            try:
                self._last_response = await response.json(content_type=None)
            except ContentTypeError as e:
                self._last_response = {}
                log.warning("Could not parse exchange rate response from %s: %s", self.name, e.message)
                log.debug(await response.text())
            return self._last_response

    async def get_rate(self):
        try:
            data = await self.get_response()
            rate = self.get_rate_from_response(data)
            rate = rate / (1.0 - self.fee)
            log.debug("Saving rate update %f for %s from %s", rate, self.market, self.name)
            self.rate = ExchangeRate(self.market, rate, int(time.time()))
            self.last_check = time.time()
            return self.rate
        except asyncio.TimeoutError:
            log.warning("Timed out fetching exchange rate from %s.", self.name)
        except json.JSONDecodeError as e:
            msg = e.doc if '<html>' not in e.doc else 'unexpected content type.'
            log.warning("Could not parse exchange rate response from %s: %s", self.name, msg)
            log.debug(e.doc)
        except InvalidExchangeRateResponseError as e:
            log.warning(str(e))
        except ClientConnectionError as e:
            log.warning("Error trying to connect to exchange rate %s: %s", self.name, str(e))
        except Exception as e:
            log.exception("Exchange rate error (%s from %s):", self.market, self.name)
        finally:
            self.event.set()

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


class BaseBittrexFeed(MarketFeed):
    name = "Bittrex"
    market = None
    url = None
    fee = 0.0025

    def get_rate_from_response(self, json_response):
        if 'lastTradeRate' not in json_response:
            raise InvalidExchangeRateResponseError(self.name, 'result not found')
        return 1.0 / float(json_response['lastTradeRate'])


class BittrexBTCFeed(BaseBittrexFeed):
    market = "BTCLBC"
    url = "https://api.bittrex.com/v3/markets/LBC-BTC/ticker"


class BittrexUSDFeed(BaseBittrexFeed):
    market = "USDLBC"
    url = "https://api.bittrex.com/v3/markets/LBC-USD/ticker"


class BaseCoinExFeed(MarketFeed):
    name = "CoinEx"
    market = None
    url = None

    def get_rate_from_response(self, json_response):
        if 'data' not in json_response or \
           'ticker' not in json_response['data'] or \
           'last' not in json_response['data']['ticker']:
            raise InvalidExchangeRateResponseError(self.name, 'result not found')
        return 1.0 / float(json_response['data']['ticker']['last'])


class CoinExBTCFeed(BaseCoinExFeed):
    market = "BTCLBC"
    url = "https://api.coinex.com/v1/market/ticker?market=LBCBTC"


class CoinExUSDFeed(BaseCoinExFeed):
    market = "USDLBC"
    url = "https://api.coinex.com/v1/market/ticker?market=LBCUSDT"


class BaseHotbitFeed(MarketFeed):
    name = "hotbit"
    market = None
    url = "https://api.hotbit.io/api/v1/market.last"

    def get_rate_from_response(self, json_response):
        if 'result' not in json_response:
            raise InvalidExchangeRateResponseError(self.name, 'result not found')
        return 1.0 / float(json_response['result'])


class HotbitBTCFeed(BaseHotbitFeed):
    market = "BTCLBC"
    params = {"market": "LBC/BTC"}


class HotbitUSDFeed(BaseHotbitFeed):
    market = "USDLBC"
    params = {"market": "LBC/USDT"}


class UPbitBTCFeed(MarketFeed):
    name = "UPbit"
    market = "BTCLBC"
    url = "https://api.upbit.com/v1/ticker"
    params = {"markets": "BTC-LBC"}

    def get_rate_from_response(self, json_response):
        if "error" in json_response or len(json_response) != 1 or 'trade_price' not in json_response[0]:
            raise InvalidExchangeRateResponseError(self.name, 'result not found')
        return 1.0 / float(json_response[0]['trade_price'])


FEEDS: Iterable[Type[MarketFeed]] = (
    BittrexBTCFeed,
    BittrexUSDFeed,
    CoinExBTCFeed,
    CoinExUSDFeed,
#    HotbitBTCFeed,
#    HotbitUSDFeed,
#    UPbitBTCFeed,
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
        log.debug(
            "Converting %f %s to %s, rates: %s",
            amount, from_currency, to_currency,
            [market.rate for market in self.market_feeds]
        )
        if from_currency == to_currency:
            return round(amount, 8)

        rates = []
        for market in self.market_feeds:
            if (market.has_rate and market.is_online and
                    market.rate.currency_pair == (from_currency, to_currency)):
                rates.append(market.rate.spot)

        if rates:
            return round(amount * Decimal(median(rates)), 8)

        raise CurrencyConversionError(
            f'Unable to convert {amount} from {from_currency} to {to_currency}')

    def to_dewies(self, currency, amount) -> int:
        converted = self.convert_currency(currency, "LBC", amount)
        return lbc_to_dewies(str(converted))

    def fee_dict(self):
        return {market: market.rate.as_dict() for market in self.market_feeds}
