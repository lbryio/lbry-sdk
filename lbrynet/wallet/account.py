from binascii import hexlify
from twisted.internet import defer

from torba.baseaccount import BaseAccount

from lbryschema.claim import ClaimDict
from lbryschema.signer import SECP256k1, get_signer

from .transaction import Transaction


def generate_certificate():
    secp256k1_private_key = get_signer(SECP256k1).generate().private_key.to_pem()
    return ClaimDict.generate_certificate(secp256k1_private_key, curve=SECP256k1), secp256k1_private_key


def get_certificate_lookup(tx_or_hash, nout):
    if isinstance(tx_or_hash, Transaction):
        return '{}:{}'.format(tx_or_hash.hex_id.decode(), nout)
    else:
        return '{}:{}'.format(hexlify(tx_or_hash[::-1]).decode(), nout)


class Account(BaseAccount):

    def __init__(self, *args, **kwargs):
        super(Account, self).__init__(*args, **kwargs)
        self.certificates = {}

    def add_certificate(self, tx, nout, private_key):
        lookup_key = '{}:{}'.format(tx.hex_id.decode(), nout)
        assert lookup_key not in self.certificates, 'Trying to add a duplicate certificate.'
        self.certificates[lookup_key] = private_key

    def get_certificate_private_key(self, tx_or_hash, nout):
        return self.certificates.get(get_certificate_lookup(tx_or_hash, nout))

    @defer.inlineCallbacks
    def maybe_migrate_certificates(self):
        for lookup_key in self.certificates.keys():
            if ':' not in lookup_key:
                claim = yield self.ledger.network.get_claims_by_ids(lookup_key)
                print(claim)
                break

    def get_balance(self, include_claims=False):
        if include_claims:
            return super(Account, self).get_balance()
        else:
            return super(Account, self).get_balance(
                is_claim=0, is_update=0, is_support=0
            )

    def get_unspent_outputs(self, include_claims=False):
        if include_claims:
            return super(Account, self).get_unspent_outputs()
        else:
            return super(Account, self).get_unspent_outputs(
                is_claim=0, is_update=0, is_support=0
            )
