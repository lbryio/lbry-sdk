import logging
from binascii import hexlify, unhexlify

from twisted.internet import defer

from torba.baseaccount import BaseAccount

from lbryschema.claim import ClaimDict
from lbryschema.signer import SECP256k1, get_signer

from .transaction import Transaction

log = logging.getLogger(__name__)


def generate_certificate():
    secp256k1_private_key = get_signer(SECP256k1).generate().private_key.to_pem()
    return ClaimDict.generate_certificate(secp256k1_private_key, curve=SECP256k1), secp256k1_private_key


def get_certificate_lookup(tx_or_hash, nout):
    if isinstance(tx_or_hash, Transaction):
        return '{}:{}'.format(tx_or_hash.id, nout)
    else:
        return '{}:{}'.format(tx_or_hash, nout)


class Account(BaseAccount):

    def __init__(self, *args, **kwargs):
        super(Account, self).__init__(*args, **kwargs)
        self.certificates = {}

    def add_certificate_private_key(self, tx_or_hash, nout, private_key):
        lookup_key = get_certificate_lookup(tx_or_hash, nout)
        assert lookup_key not in self.certificates, 'Trying to add a duplicate certificate.'
        self.certificates[lookup_key] = private_key

    def get_certificate_private_key(self, tx_or_hash, nout):
        return self.certificates.get(get_certificate_lookup(tx_or_hash, nout))

    @defer.inlineCallbacks
    def maybe_migrate_certificates(self):
        failed, succeded, total = 0, 0, 0
        for maybe_claim_id in self.certificates.keys():
            total += 1
            if ':' not in maybe_claim_id:
                claims = yield self.ledger.network.get_claims_by_ids(maybe_claim_id)
                claim = claims[maybe_claim_id]
                txhash = unhexlify(claim['txid'])[::-1]
                tx = yield self.ledger.get_transaction(txhash)
                if tx is not None:
                    txo = tx.outputs[claim['nout']]
                    assert txo.script.is_claim_involved,\
                        "Certificate with claim_id {} doesn't point to a valid transaction."\
                        .format(maybe_claim_id)
                    tx_nout = '{txid}:{nout}'.format(**claim)
                    self.certificates[tx_nout] = self.certificates[maybe_claim_id]
                    del self.certificates[maybe_claim_id]
                    log.info(
                        "Migrated certificate with claim_id '%s' ('%s') to a new look up key %s.",
                        maybe_claim_id, txo.script.values['claim_name'], tx_nout
                    )
                    succeded += 1
                else:
                    log.warning(
                        "Failed to migrate claim '%s', it's not associated with any of your addresses.",
                        maybe_claim_id
                    )
                    failed += 1
        log.info('Checked: %s, Converted: %s, Failed: %s', total, succeded, failed)

    def get_balance(self, confirmations=6, include_claims=False):
        if include_claims:
            return super(Account, self).get_balance(confirmations)
        else:
            return super(Account, self).get_balance(
                confirmations, is_claim=0, is_update=0, is_support=0
            )

    def get_unspent_outputs(self, include_claims=False):
        if include_claims:
            return super(Account, self).get_unspent_outputs()
        else:
            return super(Account, self).get_unspent_outputs(
                is_claim=0, is_update=0, is_support=0
            )

    @classmethod
    def from_dict(cls, ledger, d):  # type: (torba.baseledger.BaseLedger, Dict) -> BaseAccount
        account = super(Account, cls).from_dict(ledger, d)
        account.certificates = d['certificates']
        return account

    def to_dict(self):
        d = super(Account, self).to_dict()
        d['certificates'] = self.certificates
        return d
