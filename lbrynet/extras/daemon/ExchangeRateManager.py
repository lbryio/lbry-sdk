import asyncio
import aiohttp
import time
import logging
import json

from lbrynet.error import InvalidExchangeRateResponse, CurrencyConversionError

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
        out = "Currency pair:{}, spot:{}, ts:{}".format(
            self.currency_pair, self.spot, self.ts)
        return out

    def as_dict(self):
        return {'spot': self.spot, 'ts': self.ts}


class MarketFeed:
    REQUESTS_TIMEOUT = 20
    EXCHANGE_RATE_UPDATE_RATE_SEC = 300

    def __init__(self, market: str, name: str, url: str, params, fee):
        self.market = market
        self.name = name
        self.url = url
        self.params = params
        self.fee = fee
        self.rate = None
        self._task: asyncio.Task = None
        self._online = True

    def rate_is_initialized(self):
        return self.rate is not None

    def is_online(self):
        return self._online

    async def _make_request(self):
        async with aiohttp.request('get', self.url, params=self.params) as response:
            return await response.json()

    def _handle_response(self, response):
        return NotImplementedError

    def _subtract_fee(self, from_amount):
        # increase amount to account for market fees
        return from_amount / (1.0 - self.fee)

    def _save_price(self, price):
        log.debug("Saving price update %f for %s from %s" % (price, self.market, self.name))
        self.rate = ExchangeRate(self.market, price, int(time.time()))
        self._online = True

    def _on_error(self, err):
        log.warning("There was a problem updating %s exchange rate information from %s",
                    self.market, self.name)
        log.debug("Exchange rate error (%s from %s): %s", self.market, self.name, err)
        self._online = False

    async def _update_price(self):
        while True:
            try:
                response = await asyncio.wait_for(self._make_request(), self.REQUESTS_TIMEOUT)
                self._save_price(self._subtract_fee(self._handle_response(response)))
            except (asyncio.CancelledError, asyncio.TimeoutError, InvalidExchangeRateResponse) as err:
                self._on_error(err)
            await asyncio.sleep(self.EXCHANGE_RATE_UPDATE_RATE_SEC)

    def start(self):
        if not self._task:
            self._task = asyncio.create_task(self._update_price())

    def stop(self):
        if self._task and not (self._task.done() or self._task.cancelled()):
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

    def _handle_response(self, response):
        json_response = json.loads(response)
        if 'result' not in json_response:
            raise InvalidExchangeRateResponse(self.name, 'result not found')
        trades = json_response['result']
        if len(trades) == 0:
            raise InvalidExchangeRateResponse(self.market, 'trades not found')
        totals = sum([i['Total'] for i in trades])
        qtys = sum([i['Quantity'] for i in trades])
        if totals <= 0 or qtys <= 0:
            raise InvalidExchangeRateResponse(self.market, 'quantities were not positive')
        vwap = totals / qtys
        return float(1.0 / vwap)


class LBRYioFeed(MarketFeed):
    def __init__(self):
        super().__init__(
            "BTCLBC",
            "lbry.io",
            "https://api.lbry.io/lbc/exchange_rate",
            {},
            0.0,
        )

    def _handle_response(self, response):
        json_response = json.loads(response)
        if 'data' not in json_response:
            raise InvalidExchangeRateResponse(self.name, 'result not found')
        return 1.0 / json_response['data']['lbc_btc']


class LBRYioBTCFeed(MarketFeed):
    def __init__(self):
        super().__init__(
            "USDBTC",
            "lbry.io",
            "https://api.lbry.io/lbc/exchange_rate",
            {},
            0.0,
        )

    def _handle_response(self, response):
        try:
            json_response = json.loads(response)
        except ValueError:
            raise InvalidExchangeRateResponse(self.name, "invalid rate response : %s" % response)
        if 'data' not in json_response:
            raise InvalidExchangeRateResponse(self.name, 'result not found')
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

    def _handle_response(self, response):
        try:
            json_response = json.loads(response)
        except ValueError:
            raise InvalidExchangeRateResponse(self.name, "invalid rate response")
        if 'ticker' not in json_response or len(json_response['ticker']) == 0 or \
                'success' not in json_response or json_response['success'] is not True:
            raise InvalidExchangeRateResponse(self.name, 'result not found')
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

    def _handle_response(self, response):
        try:
            json_response = json.loads(response)
        except ValueError:
            raise InvalidExchangeRateResponse(self.name, "invalid rate response")
        if 'ticker' not in json_response or len(json_response['ticker']) == 0 or \
                'success' not in json_response or json_response['success'] is not True:
            raise InvalidExchangeRateResponse(self.name, 'result not found')
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
        log.info("Converting %f %s to %s, rates: %s" % (amount, from_currency, to_currency, rates))
        if from_currency == to_currency:
            return amount

        for market in self.market_feeds:
            if (market.rate_is_initialized() and market.is_online() and
                    market.rate.currency_pair == (from_currency, to_currency)):
                return amount * market.rate.spot
        for market in self.market_feeds:
            if (market.rate_is_initialized() and market.is_online() and
                    market.rate.currency_pair[0] == from_currency):
                return self.convert_currency(
                    market.rate.currency_pair[1], to_currency, amount * market.rate.spot)
        raise CurrencyConversionError(
            f'Unable to convert {amount} from {from_currency} to {to_currency}')

    def fee_dict(self):
        return {market: market.rate.as_dict() for market in self.market_feeds}
