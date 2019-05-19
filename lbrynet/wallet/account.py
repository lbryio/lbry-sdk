import hashlib
import json
import logging
from hashlib import sha256
from string import hexdigits

import ecdsa

from torba.client.baseaccount import BaseAccount, HierarchicalDeterministic


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

    def add_channel_private_key(self, channel_name, channel_pubkey_hash, ref_id, private_key):
        assert ref_id not in self.channel_keys, 'Trying to add a duplicate channel private key.'
        self.channel_keys[ref_id] = private_key
        if channel_pubkey_hash not in self.channel_keys:
            self.channel_keys[channel_pubkey_hash] = private_key
        else:
            log.info("Public-Private key mapping for the channel %s already exists. Skipping...", channel_name)

    def get_channel_private_key(self, channel_pubkey_hash):
        return self.channel_keys.get(channel_pubkey_hash)

    async def maybe_migrate_certificates(self):
        if not self.channel_keys:
            return

        addresses = {}
        results = {
            'total': 0,
            'old-tx-pri-key-map': 0,
            'migrate-success': 0,
            'migrate-failed': 0,
            'previous-success': 0,
            'previous-corrupted': 0
        }

        new_channel_keys = {}

        for maybe_outpoint in self.channel_keys:
            results['total'] += 1
            if ':' in maybe_outpoint:
                results['old-tx-pri-key-map'] += 1
                try:
                    private_key_pem = self.channel_keys[maybe_outpoint]
                    pubkey_hash = self._get_pubkey_address_from_private_key_pem(private_key_pem)

                    if pubkey_hash not in new_channel_keys and pubkey_hash not in self.channel_keys:
                        new_channel_keys[pubkey_hash] = private_key_pem
                        results['migrate-success'] += 1
                except Exception as e:
                    results['migrate-failed'] += 1
                    log.warning("Failed to migrate certificate for %s, incorrect private key: %s",
                                maybe_outpoint, str(e))
            else:
                try:
                    pubkey_hash = self._get_pubkey_address_from_private_key_pem(self.channel_keys[maybe_outpoint])
                    if pubkey_hash == maybe_outpoint:
                        results['previous-success'] += 1
                    else:
                        results['previous-corrupted'] += 1
                except Exception as e:
                    log.warning("Corrupt public:private key-pair: %s", str(e))
                    results['previous-corrupted'] += 1

        for key in new_channel_keys:
            self.channel_keys[key] = new_channel_keys[key]

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

    def _get_pubkey_address_from_private_key_pem(self, private_key_pem):
        private_key = ecdsa.SigningKey.from_pem(private_key_pem, hashfunc=hashlib.sha256)

        public_key_der = private_key.get_verifying_key().to_der()
        return self.ledger.public_key_to_address(public_key_der)
