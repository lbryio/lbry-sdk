import json
import logging

from torba.client.baseaccount import BaseAccount
from torba.client.basetransaction import TXORef

from lbrynet.schema.claim import ClaimDict
from lbrynet.schema.signer import SECP256k1, get_signer


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

    async def maybe_migrate_certificates(self):
        if not self.certificates:
            return

        addresses = {}
        results = {
            'total': 0,
            'not-a-claim-tx': 0,
            'migrate-success': 0,
            'migrate-failed': 0,
            'previous-success': 0,
            'previous-corrupted': 0
        }

        for maybe_claim_id in list(self.certificates):
            results['total'] += 1
            if ':' not in maybe_claim_id:
                claims = await self.ledger.network.get_claims_by_ids(maybe_claim_id)
                if maybe_claim_id not in claims:
                    log.warning(
                        "Failed to migrate claim '%s', server did not return any claim information.",
                        maybe_claim_id
                    )
                    results['migrate-failed'] += 1
                    continue
                claim = claims[maybe_claim_id]
                tx = None
                if claim:
                    tx = await self.ledger.db.get_transaction(txid=claim['txid'])
                else:
                    log.warning(maybe_claim_id)
                if tx is not None:
                    txo = tx.outputs[claim['nout']]
                    if not txo.script.is_claim_involved:
                        results['not-a-claim-tx'] += 1
                        raise ValueError(
                            "Certificate with claim_id {} doesn't point to a valid transaction."
                            .format(maybe_claim_id)
                        )
                    tx_nout = '{txid}:{nout}'.format(**claim)
                    self.certificates[tx_nout] = self.certificates[maybe_claim_id]
                    del self.certificates[maybe_claim_id]
                    log.info(
                        "Migrated certificate with claim_id '%s' ('%s') to a new look up key %s.",
                        maybe_claim_id, txo.script.values['claim_name'], tx_nout
                    )
                    results['migrate-success'] += 1
                else:
                    if claim:
                        addresses.setdefault(claim['address'], 0)
                        addresses[claim['address']] += 1
                        log.warning(
                            "Failed to migrate claim '%s', it's not associated with any of your addresses.",
                            maybe_claim_id
                        )
                    else:
                        log.warning(
                            "Failed to migrate claim '%s', it appears abandoned.",
                            maybe_claim_id
                        )
                    results['migrate-failed'] += 1
            else:
                try:
                    txid, nout = maybe_claim_id.split(':')
                    tx = await self.ledger.db.get_transaction(txid=txid)
                    if not tx:
                        log.warning(
                            "Claim migration failed to find a transaction for outpoint %s", maybe_claim_id
                        )
                        results['previous-corrupted'] += 1
                        continue
                    if tx.outputs[int(nout)].script.is_claim_involved:
                        results['previous-success'] += 1
                    else:
                        results['previous-corrupted'] += 1
                except Exception:
                    log.exception("Couldn't verify certificate with look up key: %s", maybe_claim_id)
                    results['previous-corrupted'] += 1

        self.wallet.save()
        log.info('verifying and possibly migrating certificates:')
        log.info(json.dumps(results, indent=2))
        if addresses:
            log.warning('failed for addresses:')
            log.warning(json.dumps(
                [{'address': a, 'number of certificates': c} for a, c in addresses.items()],
                indent=2
            ))

    async def save_max_gap(self):
        gap = await self.get_max_gap()
        self.receiving.gap = max(20, gap['max_receiving_gap'] + 1)
        self.change.gap = max(6, gap['max_change_gap'] + 1)
        self.wallet.save()

    def get_balance(self, confirmations=0, include_claims=False, **constraints):
        if not include_claims:
            constraints.update({'is_claim': 0, 'is_update': 0, 'is_support': 0})
        return super().get_balance(confirmations, **constraints)

    @classmethod
    def get_private_key_from_seed(cls, ledger: 'baseledger.BaseLedger', seed: str, password: str):
        return super().get_private_key_from_seed(
            ledger, seed, password or 'lbryum'
        )

    @classmethod
    def from_dict(cls, ledger, wallet, d: dict) -> 'Account':
        account = super().from_dict(ledger, wallet, d)
        account.certificates = d.get('certificates', {})
        return account

    def to_dict(self):
        d = super().to_dict()
        d['certificates'] = self.certificates
        return d

    async def get_details(self, **kwargs):
        details = await super().get_details(**kwargs)
        details['certificates'] = len(self.certificates)
        return details

    def get_claim(self, claim_id=None, txid=None, nout=None):
        if claim_id is not None:
            return self.ledger.db.get_claims(account=self, claim_id=claim_id)
        elif txid is not None and nout is not None:
            return self.ledger.db.get_claims(**{'account': self, 'txo.txid': txid, 'txo.position': nout})

    @staticmethod
    def constraint_utxos_sans_claims(constraints):
        constraints.update({'is_claim': 0, 'is_update': 0, 'is_support': 0})

    def get_utxos(self, **constraints):
        self.constraint_utxos_sans_claims(constraints)
        return super().get_utxos(**constraints)

    def get_utxo_count(self, **constraints):
        self.constraint_utxos_sans_claims(constraints)
        return super().get_utxo_count(**constraints)

    def get_claims(self, **constraints):
        return self.ledger.db.get_claims(account=self, **constraints)

    def get_claim_count(self, **constraints):
        return self.ledger.db.get_claim_count(account=self, **constraints)

    def get_channels(self, **constraints):
        return self.ledger.db.get_channels(account=self, **constraints)

    def get_channel_count(self, **constraints):
        return self.ledger.db.get_channel_count(account=self, **constraints)
