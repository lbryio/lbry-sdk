import logging

from twisted.internet import defer

from torba.baseaccount import BaseAccount
from torba.basetransaction import TXORef

from lbryschema.claim import ClaimDict
from lbryschema.signer import SECP256k1, get_signer


log = logging.getLogger(__name__)


def generate_certificate():
    secp256k1_private_key = get_signer(SECP256k1).generate().private_key.to_pem()
    return ClaimDict.generate_certificate(secp256k1_private_key, curve=SECP256k1), secp256k1_private_key


class Account(BaseAccount):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.certificates = {}

    def add_certificate_private_key(self, ref: TXORef, private_key):
        assert ref.id not in self.certificates, 'Trying to add a duplicate certificate.'
        self.certificates[ref.id] = private_key

    def get_certificate_private_key(self, ref: TXORef):
        return self.certificates.get(ref.id)

    @defer.inlineCallbacks
    def maybe_migrate_certificates(self):
        failed, succeded, done, total = 0, 0, 0, 0
        for maybe_claim_id in self.certificates.keys():
            total += 1
            if ':' not in maybe_claim_id:
                claims = yield self.ledger.network.get_claims_by_ids(maybe_claim_id)
                claim = claims[maybe_claim_id]
                #txhash = unhexlify(claim['txid'])[::-1]
                tx = yield self.ledger.get_transaction(claim['txid'])
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
            else:
                try:
                    txid, nout = maybe_claim_id.split(':')
                    tx = yield self.ledger.get_transaction(txid)
                    if tx.outputs[int(nout)].script.is_claim_involved:
                        done += 1
                    else:
                        failed += 1
                except Exception:
                    log.exception("Couldn't verify certificate with look up key: %s", maybe_claim_id)
                    failed += 1

        log.info('Checked: %s, Done: %s, Converted: %s, Failed: %s', total, done, succeded, failed)

    def get_balance(self, confirmations=6, include_claims=False, **constraints):
        if not include_claims:
            constraints.update({'is_claim': 0, 'is_update': 0, 'is_support': 0})
        return super().get_balance(confirmations, **constraints)

    def get_unspent_outputs(self, include_claims=False, **constraints):
        if not include_claims:
            constraints.update({'is_claim': 0, 'is_update': 0, 'is_support': 0})
        return super().get_unspent_outputs(**constraints)

    @defer.inlineCallbacks
    def get_channels(self):
        utxos = yield super().get_unspent_outputs(
            claim_type__any={'is_claim': 1, 'is_update': 1},
            claim_name__like='@%'
        )
        channels = []
        for utxo in utxos:
            d = ClaimDict.deserialize(utxo.script.values['claim'])
            channels.append({
                'name': utxo.claim_name,
                'claim_id': utxo.claim_id,
                'txid': utxo.tx_ref.id,
                'nout': utxo.position,
                'have_certificate': utxo.ref.id in self.certificates
            })
        defer.returnValue(channels)

    @classmethod
    def get_private_key_from_seed(cls, ledger: 'baseledger.BaseLedger', seed: str, password: str):
        return super().get_private_key_from_seed(
            ledger, seed, password or 'lbryum'
        )

    @classmethod
    def from_dict(cls, ledger, d: dict) -> 'Account':
        account = super().from_dict(ledger, d)
        account.certificates = d['certificates']
        return account

    def to_dict(self):
        d = super().to_dict()
        d['certificates'] = self.certificates
        return d

    def get_claim(self, claim_id):
        return self.ledger.db.get_claim(self, claim_id)
