import requests
import json
import time

from googlefinance import getQuotes
from lbrynet.conf import CURRENCIES
import logging

log = logging.getLogger(__name__)

BITTREX_FEE = 0.0025

SOURCE_TYPES = ['lbry_sd_hash', 'url', 'btih']
BASE_METADATA_FIELDS = ['title', 'description', 'author', 'language', 'license', 'content-type', 'sources']
OPTIONAL_METADATA_FIELDS = ['thumbnail', 'preview', 'fee', 'contact', 'pubkey']

#v0.0.1 metadata
METADATA_REVISIONS = {'0.0.1': {'required': BASE_METADATA_FIELDS, 'optional': OPTIONAL_METADATA_FIELDS}}
#v0.0.2 metadata additions
METADATA_REVISIONS['0.0.2'] = {'required': ['nsfw', 'ver'], 'optional': ['licence_url']}
CURRENT_METADATA_VERSION = '0.0.2'


#v0.0.1 fee
FEE_REVISIONS = {'0.0.1': {'required': ['amount', 'address'], 'optional': []}}
CURRENT_FEE_REVISION = '0.0.1'


class LBRYFee(object):
    def __init__(self, fee_dict, rate_dict):
        fee = LBRYFeeFormat(fee_dict)

        for currency in fee:
            self.address = fee[currency]['address']
            if not isinstance(fee[currency]['amount'], float):
                self.amount = float(fee[currency]['amount'])
            else:
                self.amount = fee[currency]['amount']
            self.currency_symbol = currency

        assert 'BTCLBC' in rate_dict and 'USDBTC' in rate_dict
        for fx in rate_dict:
            assert int(time.time()) - int(rate_dict[fx]['ts']) < 3600, "%s quote is out of date" % fx
        self._USDBTC = {'spot': rate_dict['USDBTC']['spot'], 'ts': rate_dict['USDBTC']['ts']}
        self._BTCLBC = {'spot': rate_dict['BTCLBC']['spot'], 'ts': rate_dict['BTCLBC']['ts']}

    def to_lbc(self):
        r = None
        if self.currency_symbol == "LBC":
            r = round(float(self.amount), 5)
        elif self.currency_symbol == "BTC":
            r = round(float(self._btc_to_lbc(self.amount)), 5)
        elif self.currency_symbol == "USD":
            r = round(float(self._btc_to_lbc(self._usd_to_btc(self.amount))), 5)
        assert r is not None
        return r

    def to_usd(self):
        r = None
        if self.currency_symbol == "USD":
            r = round(float(self.amount), 5)
        elif self.currency_symbol == "BTC":
            r = round(float(self._btc_to_usd(self.amount)), 5)
        elif self.currency_symbol == "LBC":
            r = round(float(self._btc_to_usd(self._lbc_to_btc(self.amount))), 5)
        assert r is not None
        return r

    def _usd_to_btc(self, usd):
        return self._USDBTC['spot'] * float(usd)

    def _btc_to_usd(self, btc):
        return float(btc) / self._USDBTC['spot']

    def _btc_to_lbc(self, btc):
        return float(btc) / self._BTCLBC['spot'] / (1.0 - BITTREX_FEE)

    def _lbc_to_btc(self, lbc):
        return self._BTCLBC['spot'] * float(lbc)


class LBRYFeeFormat(dict):
    def __init__(self, fee_dict):
        dict.__init__(self)
        self.fee_version = None
        f = fee_dict.copy()
        assert len(fee_dict) == 1
        for currency in fee_dict:
            assert currency in CURRENCIES, "Unsupported currency: %s" % str(currency)
            self.update({currency: {}})
            for version in FEE_REVISIONS:
                for k in FEE_REVISIONS[version]['required']:
                    assert k in fee_dict[currency], "Missing required fee field: %s" % k
                    self[currency].update({k: f[currency].pop(k)})
                for k in FEE_REVISIONS[version]['optional']:
                    if k in fee_dict[currency]:
                        self[currency].update({k: f[currency].pop(k)})
                if not len(f):
                    self.fee_version = version
                    break
            assert f[currency] == {}, "Unknown fee keys: %s" % json.dumps(f.keys())


class Metadata(dict):
    def __init__(self, metadata):
        dict.__init__(self)
        self.metaversion = None
        m = metadata.copy()

        assert "sources" in metadata, "No sources given"
        for source in metadata['sources']:
            assert source in SOURCE_TYPES, "Unknown source type"

        for version in METADATA_REVISIONS:
            for k in METADATA_REVISIONS[version]['required']:
                assert k in metadata, "Missing required metadata field: %s" % k
                self.update({k: m.pop(k)})
            for k in METADATA_REVISIONS[version]['optional']:
                if k == 'fee':
                    pass
                elif k in metadata:
                    self.update({k: m.pop(k)})
            if not len(m) or m.keys() == ['fee']:
                self.metaversion = version
                break
        if 'fee' in m:
            self.update({'fee': LBRYFeeFormat(m.pop('fee'))})
        assert m == {}, "Unknown metadata keys: %s" % json.dumps(m.keys())
