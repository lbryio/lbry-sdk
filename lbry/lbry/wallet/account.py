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

    def add_channel_private_key(self, private_key):
        public_key_bytes = private_key.get_verifying_key().to_der()
        channel_pubkey_hash = self.ledger.public_key_to_address(public_key_bytes)
        self.channel_keys[channel_pubkey_hash] = private_key.to_pem().decode()

    def get_channel_private_key(self, public_key_bytes):
        channel_pubkey_hash = self.ledger.public_key_to_address(public_key_bytes)
        private_key_pem = self.channel_keys.get(channel_pubkey_hash)
        if private_key_pem:
            return ecdsa.SigningKey.from_pem(private_key_pem, hashfunc=sha256)

    async def maybe_migrate_certificates(self):
        if not self.channel_keys:
            return
        channel_keys = {}
        for private_key_pem in self.channel_keys.values():
            if not isinstance(private_key_pem, str):
                continue
            if "-----BEGIN EC PRIVATE KEY-----" not in private_key_pem:
                continue
            private_key = ecdsa.SigningKey.from_pem(private_key_pem, hashfunc=sha256)
            public_key_der = private_key.get_verifying_key().to_der()
            channel_keys[self.ledger.public_key_to_address(public_key_der)] = private_key_pem
        self.channel_keys = channel_keys
        self.wallet.save()

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
        return self.ledger.db.get_claims(my_accounts=[self], **constraints)

    def get_claim_count(self, **constraints):
        return self.ledger.db.get_claim_count(my_accounts=[self], **constraints)

    def get_streams(self, **constraints):
        return self.ledger.db.get_streams(my_accounts=[self], **constraints)

    def get_stream_count(self, **constraints):
        return self.ledger.db.get_stream_count(my_accounts=[self], **constraints)

    def get_channels(self, **constraints):
        return self.ledger.db.get_channels(my_accounts=[self], **constraints)

    def get_channel_count(self, **constraints):
        return self.ledger.db.get_channel_count(my_accounts=[self], **constraints)

    def get_supports(self, **constraints):
        return self.ledger.db.get_supports(my_accounts=[self], **constraints)

    def get_support_count(self, **constraints):
        return self.ledger.db.get_support_count(my_accounts=[self], **constraints)

    async def release_all_outputs(self):
        await self.ledger.db.release_all_outputs(self)
