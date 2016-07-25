import requests
import json

from googlefinance import getQuotes
from lbrynet.conf import CURRENCIES

SOURCE_TYPES = ['lbry_sd_hash', 'url', 'btih']

BASE_METADATA_FIELDS = ['title', 'description', 'author', 'language', 'license', 'content-type', 'sources']
OPTIONAL_METADATA_FIELDS = ['thumbnail', 'preview', 'fee', 'contact', 'pubkey']

#v0.0.1 metadata
METADATA_REVISIONS = {'0.0.1': {'required': BASE_METADATA_FIELDS, 'optional': OPTIONAL_METADATA_FIELDS}}

#v0.0.2 metadata additions
METADATA_REVISIONS['0.0.2'] = {'required': ['nsfw', 'ver'], 'optional': ['licence_url']}

CURRENT_METADATA_VERSION = '0.0.2'

class LBRYFee(object):
    def __init__(self, currency, amount, address=None):
        assert currency in [c.keys()[0] for c in CURRENCIES], "Unsupported currency: %s" % str(currency)
        self.address = address
        self.currency_symbol = currency
        self.currency = next(c for c in CURRENCIES if self.currency_symbol in c)
        if not isinstance(amount, float):
            self.amount = float(amount)
        else:
            self.amount = amount

    def __call__(self):
        return {self.currency_symbol: {'amount': self.amount, 'address': self.address}}

    def convert(self, amount_only=False):
        if self.currency_symbol == "LBC":
            r = round(float(self.amount), 5)
        elif self.currency_symbol == "BTC":
            r = round(float(self.BTC_to_LBC(self.amount)), 5)
        elif self.currency_symbol == "USD":
            r = round(float(self.BTC_to_LBC(self.USD_to_BTC(self.amount))), 5)

        if not amount_only:
            return {'LBC': {'amount': r, 'address': self.address}}
        else:
            return r

    def USD_to_BTC(self, usd):
        r = float(getQuotes('CURRENCY:%sBTC' % self.currency_symbol)[0]['LastTradePrice']) * float(usd)
        return r

    def BTC_to_LBC(self, btc):
        r = requests.get("https://bittrex.com/api/v1.1/public/getticker", {'market': 'BTC-LBC'})
        last = json.loads(r.text)['result']['Last']
        converted = float(btc) / float(last)
        return converted


def fee_from_dict(fee_dict):
    s = fee_dict.keys()[0]
    return LBRYFee(s, fee_dict[s]['amount'], fee_dict[s]['address'])


class Metadata(dict):
    def __init__(self, metadata):
        dict.__init__(self)
        self.metaversion = None
        m = metadata.copy()

        if 'fee' in metadata:
            assert fee_from_dict(metadata['fee'])

        assert "sources" in metadata, "No sources given"
        for source in metadata['sources']:
            assert source in SOURCE_TYPES, "Unknown source type"

        for version in METADATA_REVISIONS:
            for k in METADATA_REVISIONS[version]['required']:
                assert k in metadata, "Missing required metadata field: %s" % k
                self.update({k: m.pop(k)})
            for k in METADATA_REVISIONS[version]['optional']:
                if k in metadata:
                    self.update({k: m.pop(k)})
            if not len(m):
                self.metaversion = version
                break
        assert m == {}, "Unknown metadata keys: %s" % json.dumps(m.keys())
