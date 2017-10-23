import time
import requests
import logging
import json
from twisted.internet import defer, threads
from twisted.internet.task import LoopingCall

from lbrynet import conf
from lbrynet.core.Error import InvalidExchangeRateResponse

log = logging.getLogger(__name__)

CURRENCY_PAIRS = ["USDBTC", "BTCLBC"]
BITTREX_FEE = 0.0025
COINBASE_FEE = 0.0 #add fee


class ExchangeRate(object):
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


class MarketFeed(object):
    REQUESTS_TIMEOUT = 20
    EXCHANGE_RATE_UPDATE_RATE_SEC = 300
    def __init__(self, market, name, url, params, fee):
        self.market = market
        self.name = name
        self.url = url
        self.params = params
        self.fee = fee
        self.rate = None
        self._updater = LoopingCall(self._update_price)
        self._online = True

    @property
    def rate_is_initialized(self):
        return self.rate is not None

    @property
    def is_online(self):
        return self._online

    def _make_request(self):
        r = requests.get(self.url, self.params, timeout=self.REQUESTS_TIMEOUT)
        if r.status_code == 200:
            self._online = True
            return r.text
        self._online = False
        return ""

    def _handle_response(self, response):
        return NotImplementedError

    def _subtract_fee(self, from_amount):
        # increase amount to account for market fees
        return defer.succeed(from_amount / (1.0 - self.fee))

    def _save_price(self, price):
        log.debug("Saving price update %f for %s from %s" % (price, self.market, self.name))
        self.rate = ExchangeRate(self.market, price, int(time.time()))

    def _log_error(self, err):
        log.warning(
            "There was a problem updating %s exchange rate information from %s: %s",
            self.market, self.name, err)

    def _update_price(self):
        d = threads.deferToThread(self._make_request)
        d.addCallback(self._handle_response)
        d.addCallback(self._subtract_fee)
        d.addCallback(self._save_price)
        d.addErrback(self._log_error)
        return d

    def start(self):
        if not self._updater.running:
            self._updater.start(self.EXCHANGE_RATE_UPDATE_RATE_SEC)

    def stop(self):
        if self._updater.running:
            self._updater.stop()


class BittrexFeed(MarketFeed):
    def __init__(self):
        MarketFeed.__init__(
            self,
            "BTCLBC",
            "Bittrex",
            conf.settings['bittrex_feed'],
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
        vwap = totals/qtys
        return defer.succeed(float(1.0 / vwap))


class LBRYioFeed(MarketFeed):
    def __init__(self):
        MarketFeed.__init__(
            self,
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
        return defer.succeed(1.0 / json_response['data']['lbc_btc'])


class LBRYioBTCFeed(MarketFeed):
    def __init__(self):
        MarketFeed.__init__(
            self,
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
        return defer.succeed(1.0 / json_response['data']['btc_usd'])


class CryptonatorBTCFeed(MarketFeed):
    def __init__(self):
        MarketFeed.__init__(
            self,
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
            raise InvalidExchangeRateResponse(self.name, "invalid rate response : %s" % response)
        if 'ticker' not in json_response or len(json_response['ticker']) == 0 or \
                        'success' not in json_response or json_response['success'] is not True:
            raise InvalidExchangeRateResponse(self.name, 'result not found')
        return defer.succeed(float(json_response['ticker']['price']))



class CryptonatorFeed(MarketFeed):
    def __init__(self):
        MarketFeed.__init__(
            self,
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
            raise InvalidExchangeRateResponse(self.name, "invalid rate response : %s" % response)
        if 'ticker' not in json_response or len(json_response['ticker']) == 0 or \
                        'success' not in json_response or json_response['success'] is not True:
            raise InvalidExchangeRateResponse(self.name, 'result not found')
        return defer.succeed(float(json_response['ticker']['price']))


def get_default_market_feed(currency_pair):
    currencies = None
    if isinstance(currency_pair, str):
        currencies = (currency_pair[0:3], currency_pair[3:6])
    elif isinstance(currency_pair, tuple):
        currencies = currency_pair
    assert currencies is not None

    if currencies == ("USD", "BTC"):
        return LBRYioBTCFeed()
    elif currencies == ("BTC", "LBC"):
        return LBRYioFeed()


class ExchangeRateManager(object):
    def __init__(self):
        self.market_feeds = [
           LBRYioBTCFeed(), LBRYioFeed(), CryptonatorBTCFeed(), CryptonatorFeed()]

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
            if (market.rate_is_initialized and market.is_online and
                market.rate.currency_pair == (from_currency, to_currency)):
                return amount * market.rate.spot
        for market in self.market_feeds:
            if (market.rate_is_initialized and market.is_online and
                market.rate.currency_pair[0] == from_currency):
                return self.convert_currency(
                    market.rate.currency_pair[1], to_currency, amount * market.rate.spot)
        raise Exception(
            'Unable to convert {} from {} to {}'.format(amount, from_currency, to_currency))

    def fee_dict(self):
        return {market: market.rate.as_dict() for market in self.market_feeds}
