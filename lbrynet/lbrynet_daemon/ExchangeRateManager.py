import time
import requests
import logging
import json
import googlefinance
from twisted.internet import defer, reactor
from twisted.internet.task import LoopingCall

from lbrynet.metadata.Fee import FeeValidator

log = logging.getLogger(__name__)

CURRENCY_PAIRS = ["USDBTC", "BTCLBC"]
BITTREX_FEE = 0.0025
COINBASE_FEE = 0.0 #add fee


class ExchangeRate(object):
    def __init__(self, market, spot, ts):
        assert int(time.time()) - ts < 600
        self.currency_pair = (market[0:3], market[3:6])
        self.spot = spot
        self.ts = ts

    def as_dict(self):
        return {'spot': self.spot, 'ts': self.ts}


class MarketFeed(object):
    def __init__(self, market, name, url, params, fee):
        self.market = market
        self.name = name
        self.url = url
        self.params = params
        self.fee = fee
        self.rate = None
        self._updater = LoopingCall(self._update_price)

    def _make_request(self):
        try:
            r = requests.get(self.url, self.params)
            return defer.succeed(r.text)
        except Exception as err:
            log.error(err)
            return defer.fail(err)

    def _handle_response(self, response):
        return NotImplementedError

    def _subtract_fee(self, from_amount):
        # increase amount to account for market fees
        return defer.succeed(from_amount / (1.0 - self.fee))

    def _save_price(self, price):
        log.debug("Saving price update %f for %s" % (price, self.market))
        self.rate = ExchangeRate(self.market, price, int(time.time()))

    def _log_error(self, err):
        log.error(err)
        log.warning("There was a problem updating %s exchange rate information from %s", self.market, self.name)

    def _update_price(self):
        d = self._make_request()
        d.addCallback(self._handle_response)
        d.addCallback(self._subtract_fee)
        d.addCallback(self._save_price)
        d.addErrback(self._log_error)

    def start(self):
        if not self._updater.running:
            self._updater.start(300)

    def stop(self):
        if self._updater.running:
            self._updater.stop()


class BittrexFeed(MarketFeed):
    def __init__(self):
        MarketFeed.__init__(
            self,
            "BTCLBC",
            "Bittrex",
            "https://bittrex.com/api/v1.1/public/getmarkethistory",
            {'market': 'BTC-LBC', 'count': 50},
            BITTREX_FEE
        )

    def _handle_response(self, response):
        trades = json.loads(response)['result']
        vwap = sum([i['Total'] for i in trades]) / sum([i['Quantity'] for i in trades])
        return defer.succeed(float(1.0 / vwap))


class GoogleBTCFeed(MarketFeed):
    def __init__(self):
        MarketFeed.__init__(
            self,
            "USDBTC",
            "Coinbase via Google finance",
            None,
            None,
            COINBASE_FEE
        )

    def _make_request(self):
        try:
            r = googlefinance.getQuotes('CURRENCY:USDBTC')[0]
            return defer.succeed(r)
        except Exception as err:
            return defer.fail(err)

    def _handle_response(self, response):
        return float(response['LastTradePrice'])


def get_default_market_feed(currency_pair):
    currencies = None
    if isinstance(currency_pair, str):
        currencies = (currency_pair[0:3], currency_pair[3:6])
    elif isinstance(currency_pair, tuple):
        currencies = currency_pair
    assert currencies is not None

    if currencies == ("USD", "BTC"):
        return GoogleBTCFeed()
    elif currencies == ("BTC", "LBC"):
        return BittrexFeed()


class ExchangeRateManager(object):
    def __init__(self):
        reactor.addSystemEventTrigger('before', 'shutdown', self.stop)
        self.market_feeds = [get_default_market_feed(currency_pair) for currency_pair in CURRENCY_PAIRS]

    def start(self):
        log.info("Starting exchange rate manager")
        for feed in self.market_feeds:
            feed.start()

    def stop(self):
        log.info("Stopping exchange rate manager")
        for source in self.market_feeds:
            source.stop()

    def convert_currency(self, from_currency, to_currency, amount):
        log.info("Converting %f %s to %s" % (amount, from_currency, to_currency))
        if from_currency == to_currency:
            return amount
        for market in self.market_feeds:
            if market.rate.currency_pair == (from_currency, to_currency):
                return amount * market.rate.spot
        for market in self.market_feeds:
            if market.rate.currency_pair[0] == from_currency:
                return self.convert_currency(market.rate.currency_pair[1], to_currency, amount * market.rate.spot)
        raise Exception('Unable to convert {} from {} to {}'.format(amount, from_currency, to_currency))

    def fee_dict(self):
        return {market: market.rate.as_dict() for market in self.market_feeds}

    def to_lbc(self, fee):
        if fee is None:
            return None
        if not isinstance(fee, FeeValidator):
            fee_in = FeeValidator(fee)
        else:
            fee_in = fee

        return FeeValidator({fee_in.currency_symbol:
                                    {
                                        'amount': self.convert_currency(fee_in.currency_symbol, "LBC", fee_in.amount),
                                        'address': fee_in.address
                                    }
        })


class DummyBTCLBCFeed(MarketFeed):
    def __init__(self):
        MarketFeed.__init__(
            self,
            "BTCLBC",
            "market name",
            "derp.com",
            None,
            0.0
        )


class DummyUSDBTCFeed(MarketFeed):
    def __init__(self):
        MarketFeed.__init__(
            self,
            "USDBTC",
            "market name",
            "derp.com",
            None,
            0.0
        )


class DummyExchangeRateManager(object):
    def __init__(self, rates):
        self.market_feeds = [DummyBTCLBCFeed(), DummyUSDBTCFeed()]
        for feed in self.market_feeds:
            feed.rate = ExchangeRate(feed.market, rates[feed.market]['spot'], rates[feed.market]['ts'])

    def convert_currency(self, from_currency, to_currency, amount):
        log.debug("Converting %f %s to %s" % (amount, from_currency, to_currency))
        for market in self.market_feeds:
            if market.rate.currency_pair == (from_currency, to_currency):
                return amount * market.rate.spot
        for market in self.market_feeds:
            if market.rate.currency_pair[0] == from_currency:
                return self.convert_currency(market.rate.currency_pair[1], to_currency, amount * market.rate.spot)

    def to_lbc(self, fee):
        if fee is None:
            return None
        if not isinstance(fee, FeeValidator):
            fee_in = FeeValidator(fee)
        else:
            fee_in = fee

        return FeeValidator({fee_in.currency_symbol:
                                    {
                                        'amount': self.convert_currency(fee_in.currency_symbol, "LBC", fee_in.amount),
                                        'address': fee_in.address
                                    }
        })