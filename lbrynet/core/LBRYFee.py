import requests
import json

from lbrynet.conf import CURRENCIES


class LBRYFee(object):
    def __init__(self, currency, amount, address=None):
        assert currency in [c.keys()[0] for c in CURRENCIES], "Unsupported currency: %s" % str(currency)
        self.address = address
        self.currency_symbol = currency
        self.currency = [c for c in CURRENCIES if self.currency_symbol in c][0]
        if not isinstance(amount, float):
            self.amount = float(amount)
        else:
            self.amount = amount

    def convert_to(self, to_currency, rate_dict={}):
        if to_currency is self.currency_symbol:
            return self.as_dict()
        if self.currency[self.currency_symbol]['type'] is 'fiat':
            raise NotImplemented
        else:
            if to_currency not in rate_dict:
                params = {'market': '%s-%s' % (self.currency_symbol, to_currency)}
                r = requests.get("https://bittrex.com/api/v1.1/public/getticker", params)
                last = json.loads(r.text)['result']['Last']
                converted = self.amount / float(last)
            else:
                converted = self.amount / float(rate_dict[to_currency]['last'])

        return LBRYFee(to_currency, converted, self.address).as_dict()

    def as_dict(self):
        return {self.currency_symbol: {'amount': self.amount, 'address': self.address}}

    def from_dict(self, fee_dict):
        s = fee_dict.keys()[0]
        return LBRYFee(s, fee_dict[s]['amount'], fee_dict[s]['address'])