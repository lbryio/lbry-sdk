import json
import logging
from functools import partial
from hashlib import sha256
from string import hexdigits

import ecdsa
from lbry.wallet.constants import TXO_TYPES

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
        h = sha256(json.dumps(self.to_dict(include_channel_keys=False)).encode())
        for cert in sorted(self.channel_keys.keys()):
            h.update(cert.encode())
        return h.digest()

    def merge(self, d: dict):
        super().merge(d)
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
        if self.channel_keys != channel_keys:
            self.channel_keys = channel_keys
            self.wallet.save()

    async def save_max_gap(self):
        if issubclass(self.address_generator, HierarchicalDeterministic):
            gap = await self.get_max_gap()
            gap_changed = False
            new_receiving_gap = max(20, gap['max_receiving_gap'] + 1)
            if self.receiving.gap != new_receiving_gap:
                self.receiving.gap = new_receiving_gap
                gap_changed = True
            new_change_gap = max(6, gap['max_change_gap'] + 1)
            if self.change.gap != new_change_gap:
                self.change.gap = new_change_gap
                gap_changed = True
            if gap_changed:
                self.wallet.save()

    def get_balance(self, confirmations=0, include_claims=False, **constraints):
        if not include_claims:
            constraints.update({'txo_type': 0})
        return super().get_balance(confirmations, **constraints)

    async def get_detailed_balance(self, confirmations=0, reserved_subtotals=False):
        tips_balance, supports_balance, claims_balance = 0, 0, 0
        get_total_balance = partial(self.get_balance, confirmations=confirmations, include_claims=True)
        total = await get_total_balance()
        if reserved_subtotals:
            claims_balance = await get_total_balance(txo_type__in=[TXO_TYPES['stream'], TXO_TYPES['channel']])
            for amount, spent, from_me, to_me, height in await self.get_support_summary():
                if confirmations > 0 and not 0 < height <= self.ledger.headers.height - (confirmations - 1):
                    continue
                if not spent and to_me:
                    if from_me:
                        supports_balance += amount
                    else:
                        tips_balance += amount
            reserved = claims_balance + supports_balance + tips_balance
        else:
            reserved = await self.get_balance(
                confirmations=confirmations, include_claims=True, txo_type__gt=0
            )
        return {
            'total': total,
            'available': total - reserved,
            'reserved': reserved,
            'reserved_subtotals': {
                'claims': claims_balance,
                'supports': supports_balance,
                'tips': tips_balance
            } if reserved_subtotals else None
        }

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

    def to_dict(self, encrypt_password: str = None, include_channel_keys: bool = True):
        d = super().to_dict(encrypt_password)
        if include_channel_keys:
            d['certificates'] = self.channel_keys
        return d

    async def get_details(self, **kwargs):
        details = await super().get_details(**kwargs)
        details['certificates'] = len(self.channel_keys)
        return details

    def get_transaction_history(self, **constraints):
        return self.ledger.get_transaction_history(wallet=self.wallet, accounts=[self], **constraints)

    def get_transaction_history_count(self, **constraints):
        return self.ledger.get_transaction_history_count(wallet=self.wallet, accounts=[self], **constraints)

    def get_claims(self, **constraints):
        return self.ledger.get_claims(wallet=self.wallet, accounts=[self], **constraints)

    def get_claim_count(self, **constraints):
        return self.ledger.get_claim_count(wallet=self.wallet, accounts=[self], **constraints)

    def get_streams(self, **constraints):
        return self.ledger.get_streams(wallet=self.wallet, accounts=[self], **constraints)

    def get_stream_count(self, **constraints):
        return self.ledger.get_stream_count(wallet=self.wallet, accounts=[self], **constraints)

    def get_channels(self, **constraints):
        return self.ledger.get_channels(wallet=self.wallet, accounts=[self], **constraints)

    def get_channel_count(self, **constraints):
        return self.ledger.get_channel_count(wallet=self.wallet, accounts=[self], **constraints)

    def get_supports(self, **constraints):
        return self.ledger.get_supports(wallet=self.wallet, accounts=[self], **constraints)

    def get_support_count(self, **constraints):
        return self.ledger.get_support_count(wallet=self.wallet, accounts=[self], **constraints)

    def get_support_summary(self):
        return self.ledger.db.get_supports_summary(account_id=self.id)

    async def release_all_outputs(self):
        await self.ledger.db.release_all_outputs(self)
