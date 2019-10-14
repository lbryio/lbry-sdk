import asyncio
import time
import logging
import json
from decimal import Decimal
from typing import Optional
from json.decoder import JSONDecodeError
from aiohttp.client_exceptions import ClientError
from lbry.error import InvalidExchangeRateResponseError, CurrencyConversionError
from lbry.utils import aiohttp_request
from lbry.wallet.dewies import lbc_to_dewies

log = logging.getLogger(__name__)

CURRENCY_PAIRS = ["USDBTC", "BTCLBC"]
BITTREX_FEE = 0.0025
COINBASE_FEE = 0.0  # add fee


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
        out = f"Currency pair:{self.currency_pair}, spot:{self.spot}, ts:{self.ts}"
        return out

    def as_dict(self):
        return {'spot': self.spot, 'ts': self.ts}


class Deserializer:
    def __init__(self, content_type):
        self.content_type = content_type
        self._deserializer = self._get_deserializer(content_type)

    def deserialize(self, body):
        return self._deserializer(body)

    def _get_deserializer(self, content_type):
        if content_type == 'json':
            return self._deserialize_json
        else:
            raise ValueError('Content type {content_type} is not supported')

    def _deserialize_json(self, body):
        try:
            return json.loads(body)
        except (ValueError, JSONDecodeError):
            log.error('Failed to deserialize response body: %s', body)
            raise


class AioHttpManager:
    REQUESTS_TIMEOUT = 20

    def __init__(self, url, params, content_type):
        self.url = url
        self.params = params
        self.content_type = content_type

    async def _make_request(self):
        async with aiohttp_request('get', self.url, params=self.params) as response:
            return await response

    async def get_response_body(self):
        response = await asyncio.wait_for(self._make_request(), self.REQUESTS_TIMEOUT)
        if self.content_type not in response.headers.get('Content-Type'):
            raise InvalidExchangeRateResponse(self.url, f'Received response is not of type {self.content_type}')
        return response.read().decode()


class MarketFeed:
    EXCHANGE_RATE_UPDATE_RATE_SEC = 300

    def __init__(self, market: str, name: str, url: str, params: dict, fee: float,
                 content_type: str = 'json', network_manager=AioHttpManager,
                 deserializer=Deserializer):
        self.market = market
        self.name = name
        self.fee = fee
        self.rate = None
        self._network_manager = network_manager(url, params, content_type)
        self._deserializer = deserializer(content_type)
        self._task: Optional[asyncio.Task] = None
        self._online = True

    def rate_is_initialized(self):
        return self.rate is not None

    def is_online(self):
        return self._online

    def _on_error(self, err):
        log.warning("There was a problem updating %s exchange rate information from %s",
                    self.market, self.name)
        log.debug("Exchange rate error (%s from %s): %s", self.market, self.name, err)
        self._online = False

    def _handle_response(self, body):
        raise NotImplementedError()

    def _subtract_fee(self, from_amount):
        # increase amount to account for market fees
        return from_amount / (1.0 - self.fee)

    def _save_price(self, price):
        log.debug("Saving price update %f for %s from %s" % (price, self.market, self.name))
        self.rate = ExchangeRate(self.market, price, int(time.time()))
        self._online = True

    async def _get_current_price(self):
        body = self._deserializer.deserialize(await self._network_manager.get_response_body())
        return self._subtract_fee(self._handle_response(body))

    async def _update_price(self):
        try:
            self._save_price(await self._get_current_price())
        except (asyncio.TimeoutError, InvalidExchangeRateResponseError, ClientError) as err:
            self._on_error(err)

    async def _keep_updated(self):
        while True:
            self._update_price()
            await asyncio.sleep(self.EXCHANGE_RATE_UPDATE_RATE_SEC)

    def start(self):
        if not self._task:
            self._task = asyncio.create_task(self._keep_updated)

    def stop(self):
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None


class BittrexFeed(MarketFeed):
    def __init__(self):
        super().__init__(
            "BTCLBC",
            "Bittrex",
            "https://bittrex.com/api/v1.1/public/getmarkethistory",
            {'market': 'BTC-LBC', 'count': 50},
            BITTREX_FEE
        )

    def _handle_response(self, json_response):
        if 'result' not in json_response:
            raise InvalidExchangeRateResponseError(self.name, 'result not found')
        trades = json_response['result']
        if len(trades) == 0:
            raise InvalidExchangeRateResponseError(self.market, 'trades not found')
        totals = sum([i['Total'] for i in trades])
        qtys = sum([i['Quantity'] for i in trades])
        if totals <= 0 or qtys <= 0:
            raise InvalidExchangeRateResponseError(self.market, 'quantities were not positive')
        vwap = totals / qtys
        return float(1.0 / vwap)


class LBRYioFeed(MarketFeed):
    def __init__(self):
        super().__init__(
            "BTCLBC",
            "lbry.com",
            "https://api.lbry.com/lbc/exchange_rate",
            {},
            0.0,
        )

    def _handle_response(self, json_response):
        if 'data' not in json_response:
            raise InvalidExchangeRateResponseError(self.name, 'result not found')
        return 1.0 / json_response['data']['lbc_btc']


class LBRYioBTCFeed(MarketFeed):
    def __init__(self):
        super().__init__(
            "USDBTC",
            "lbry.com",
            "https://api.lbry.com/lbc/exchange_rate",
            {},
            0.0,
        )

    def _handle_response(self, json_response):
        if 'data' not in json_response:
            raise InvalidExchangeRateResponseError(self.name, 'result not found')
        return 1.0 / json_response['data']['btc_usd']


class CryptonatorBTCFeed(MarketFeed):
    def __init__(self):
        super().__init__(
            "USDBTC",
            "cryptonator.com",
            "https://api.cryptonator.com/api/ticker/usd-btc",
            {},
            0.0,
        )

    def _handle_response(self, json_response):
        if 'ticker' not in json_response or len(json_response['ticker']) == 0 or \
                'success' not in json_response or json_response['success'] is not True:
            raise InvalidExchangeRateResponseError(self.name, 'result not found')
        return float(json_response['ticker']['price'])


class CryptonatorFeed(MarketFeed):
    def __init__(self):
        super().__init__(
            "BTCLBC",
            "cryptonator.com",
            "https://api.cryptonator.com/api/ticker/btc-lbc",
            {},
            0.0,
        )

    def _handle_response(self, json_response):
        if 'ticker' not in json_response or len(json_response['ticker']) == 0 or \
                'success' not in json_response or json_response['success'] is not True:
            raise InvalidExchangeRateResponseError(self.name, 'result not found')
        return float(json_response['ticker']['price'])


class ExchangeRateManager:
    def __init__(self):
        self.market_feeds = [
            LBRYioBTCFeed(),
            LBRYioFeed(),
            BittrexFeed(),
            # CryptonatorBTCFeed(),
            # CryptonatorFeed()
        ]

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
            if (market.rate_is_initialized() and market.is_online() and
                    market.rate.currency_pair == (from_currency, to_currency)):
                return round(amount * Decimal(market.rate.spot), 8)
        for market in self.market_feeds:
            if (market.rate_is_initialized() and market.is_online() and
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
