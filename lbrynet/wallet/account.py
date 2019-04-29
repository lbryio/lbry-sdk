import json
import logging
import binascii
from hashlib import sha256
from string import hexdigits

from torba.client.baseaccount import BaseAccount, HierarchicalDeterministic
from torba.client.basetransaction import TXORef


log = logging.getLogger(__name__)


def validate_claim_id(claim_id):
    if not len(claim_id) == 40:
        raise Exception("Incorrect claimid length: %i" % len(claim_id))
    if isinstance(claim_id, bytes):
        claim_id = claim_id.decode('utf-8')
    if set(claim_id).difference(hexdigits):
        raise Exception("Claim id is not hex encoded")


class Account(BaseAccount):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.channel_keys = {}

    @property
    def hash(self) -> bytes:
        h = sha256(json.dumps(self.to_dict(False)).encode())
        for cert in sorted(self.channel_keys.keys()):
            h.update(cert.encode())
        return h.digest()

    def apply(self, d: dict):
        super().apply(d)
        self.channel_keys.update(d.get('certificates', {}))

    def add_channel_private_key(self, ref: TXORef, private_key):
        assert ref.id not in self.channel_keys, 'Trying to add a duplicate channel private key.'
        self.channel_keys[ref.id] = private_key

    def get_channel_private_key(self, ref: TXORef):
        return self.channel_keys.get(ref.id)

    async def maybe_migrate_certificates(self):
        if not self.channel_keys:
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
        double_hex_encoded_to_pop = []

        for maybe_claim_id in list(self.channel_keys):
            if ':' not in maybe_claim_id:
                try:
                    validate_claim_id(maybe_claim_id)
                    continue
                except Exception:
                    try:
                        maybe_claim_id_bytes = maybe_claim_id
                        if isinstance(maybe_claim_id_bytes, str):
                            maybe_claim_id_bytes = maybe_claim_id_bytes.encode()
                        decoded_double_hex = binascii.unhexlify(maybe_claim_id_bytes).decode()
                        validate_claim_id(decoded_double_hex)
                        if decoded_double_hex in self.channel_keys:
                            log.warning("don't know how to migrate certificate %s", decoded_double_hex)
                        else:
                            log.info("claim id was double hex encoded, fixing it")
                            double_hex_encoded_to_pop.append((maybe_claim_id, decoded_double_hex))
                    except Exception:
                        continue

        for double_encoded_claim_id, correct_claim_id in double_hex_encoded_to_pop:
            self.channel_keys[correct_claim_id] = self.channel_keys.pop(double_encoded_claim_id)

        for maybe_claim_id in list(self.channel_keys):
            results['total'] += 1
            if ':' not in maybe_claim_id:
                try:
                    validate_claim_id(maybe_claim_id)
                except Exception as e:
                    log.warning(
                        "Failed to migrate claim '%s': %s",
                        maybe_claim_id, str(e)
                    )
                    results['migrate-failed'] += 1
                    continue
                claims = await self.ledger.network.get_claims_by_ids([maybe_claim_id])
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
                    self.channel_keys[tx_nout] = self.channel_keys[maybe_claim_id]
                    del self.channel_keys[maybe_claim_id]
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
        if issubclass(self.address_generator, HierarchicalDeterministic):
            gap = await self.get_max_gap()
            self.receiving.gap = max(20, gap['max_receiving_gap'] + 1)
            self.change.gap = max(6, gap['max_change_gap'] + 1)
            self.wallet.save()

    def get_balance(self, confirmations=0, include_claims=False, **constraints):
        if not include_claims:
            constraints.update({'is_claim': 0, 'is_update': 0, 'is_support': 0})
        return super().get_balance(confirmations, **constraints)

    @classmethod
    def get_private_key_from_seed(cls, ledger, seed: str, password: str):
        return super().get_private_key_from_seed(
            ledger, seed, password or 'lbryum'
        )

    @classmethod
    def from_dict(cls, ledger, wallet, d: dict) -> 'Account':
        account = super().from_dict(ledger, wallet, d)
        account.channel_keys = d.get('certificates', {})
        return account

    def to_dict(self, include_channel_keys=True):
        d = super().to_dict()
        if include_channel_keys:
            d['certificates'] = self.channel_keys
        return d

    async def get_details(self, **kwargs):
        details = await super().get_details(**kwargs)
        details['certificates'] = len(self.channel_keys)
        return details

    @staticmethod
    def constraint_spending_utxos(constraints):
        constraints.update({'is_claim': 0, 'is_update': 0, 'is_support': 0})

    def get_utxos(self, **constraints):
        self.constraint_spending_utxos(constraints)
        return super().get_utxos(**constraints)

    def get_utxo_count(self, **constraints):
        self.constraint_spending_utxos(constraints)
        return super().get_utxo_count(**constraints)

    def get_claims(self, **constraints):
        return self.ledger.db.get_claims(account=self, **constraints)

    def get_claim_count(self, **constraints):
        return self.ledger.db.get_claim_count(account=self, **constraints)

    def get_streams(self, **constraints):
        return self.ledger.db.get_streams(account=self, **constraints)

    def get_stream_count(self, **constraints):
        return self.ledger.db.get_stream_count(account=self, **constraints)

    def get_channels(self, **constraints):
        return self.ledger.db.get_channels(account=self, **constraints)

    def get_channel_count(self, **constraints):
        return self.ledger.db.get_channel_count(account=self, **constraints)

    def get_supports(self, **constraints):
        return self.ledger.db.get_supports(account=self, **constraints)

    def get_support_count(self, **constraints):
        return self.ledger.db.get_support_count(account=self, **constraints)

    async def release_all_outputs(self):
        await self.ledger.db.release_all_outputs(self)
