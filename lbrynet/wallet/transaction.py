import struct
import hashlib
from binascii import hexlify, unhexlify
from typing import List, Optional

import ecdsa
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import load_der_public_key
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
from ecdsa.util import sigencode_der

from torba.client.basetransaction import BaseTransaction, BaseInput, BaseOutput, ReadOnlyList
from torba.client.hash import hash160, sha256, Base58
from lbrynet.schema.claim import Claim
from lbrynet.schema.url import normalize_name
from lbrynet.wallet.account import Account
from lbrynet.wallet.script import InputScript, OutputScript


class Input(BaseInput):
    script: InputScript
    script_class = InputScript


class Output(BaseOutput):
    script: OutputScript
    script_class = OutputScript

    __slots__ = 'channel', 'private_key', 'meta'

    def __init__(self, *args, channel: Optional['Output'] = None,
                 private_key: Optional[str] = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.channel = channel
        self.private_key = private_key
        self.meta = {}

    def update_annotations(self, annotated):
        super().update_annotations(annotated)
        self.channel = annotated.channel if annotated else None
        self.private_key = annotated.private_key if annotated else None

    def get_fee(self, ledger):
        name_fee = 0
        if self.script.is_claim_name:
            name_fee = len(self.script.values['claim_name']) * ledger.fee_per_name_char
        return max(name_fee, super().get_fee(ledger))

    @property
    def is_claim(self) -> bool:
        return self.script.is_claim_name or self.script.is_update_claim

    @property
    def is_support(self) -> bool:
        return self.script.is_support_claim

    @property
    def claim_hash(self) -> bytes:
        if self.script.is_claim_name:
            return hash160(self.tx_ref.hash + struct.pack('>I', self.position))
        elif self.script.is_update_claim or self.script.is_support_claim:
            return self.script.values['claim_id']
        else:
            raise ValueError('No claim_id associated.')

    @property
    def claim_id(self) -> str:
        return hexlify(self.claim_hash[::-1]).decode()

    @property
    def claim_name(self) -> str:
        if self.script.is_claim_involved:
            return self.script.values['claim_name'].decode()
        raise ValueError('No claim_name associated.')

    @property
    def normalized_name(self) -> str:
        return normalize_name(self.claim_name)

    @property
    def claim(self) -> Claim:
        if self.is_claim:
            if not isinstance(self.script.values['claim'], Claim):
                self.script.values['claim'] = Claim.from_bytes(self.script.values['claim'])
            return self.script.values['claim']
        raise ValueError('Only claim name and claim update have the claim payload.')

    @property
    def permanent_url(self) -> str:
        if self.script.is_claim_involved:
            return f"lbry://{self.claim_name}#{self.claim_id}"
        raise ValueError('No claim associated.')

    @property
    def has_private_key(self):
        return self.private_key is not None

    def is_signed_by(self, channel: 'Output', ledger=None):
        if self.claim.unsigned_payload:
            pieces = [
                Base58.decode(self.get_address(ledger)),
                self.claim.unsigned_payload,
                self.claim.signing_channel_hash[::-1]
            ]
        else:
            pieces = [
                self.tx_ref.tx.inputs[0].txo_ref.hash,
                self.claim.signing_channel_hash,
                self.claim.to_message_bytes()
            ]
        digest = sha256(b''.join(pieces))
        public_key = load_der_public_key(channel.claim.channel.public_key_bytes, default_backend())
        hash = hashes.SHA256()
        signature = hexlify(self.claim.signature)
        r = int(signature[:int(len(signature)/2)], 16)
        s = int(signature[int(len(signature)/2):], 16)
        encoded_sig = sigencode_der(r, s, len(signature)*4)
        public_key.verify(encoded_sig, digest, ec.ECDSA(Prehashed(hash)))
        return True

    def sign(self, channel: 'Output', first_input_id=None):
        self.channel = channel
        self.claim.signing_channel_hash = channel.claim_hash
        digest = sha256(b''.join([
            first_input_id or self.tx_ref.tx.inputs[0].txo_ref.hash,
            self.claim.signing_channel_hash,
            self.claim.to_message_bytes()
        ]))
        private_key = ecdsa.SigningKey.from_pem(channel.private_key, hashfunc=hashlib.sha256)
        self.claim.signature = private_key.sign_digest_deterministic(digest, hashfunc=hashlib.sha256)
        self.script.generate()

    def clear_signature(self):
        self.channel = None
        self.claim.clear_signature()

    def generate_channel_private_key(self):
        private_key = ecdsa.SigningKey.generate(curve=ecdsa.SECP256k1, hashfunc=hashlib.sha256)
        self.private_key = private_key.to_pem().decode()
        self.claim.channel.public_key_bytes = private_key.get_verifying_key().to_der()
        self.script.generate()
        return self.private_key

    def is_channel_private_key(self, private_key_pem):
        private_key = ecdsa.SigningKey.from_pem(private_key_pem, hashfunc=hashlib.sha256)
        return self.claim.channel.public_key_bytes == private_key.get_verifying_key().to_der()

    @classmethod
    def pay_claim_name_pubkey_hash(
            cls, amount: int, claim_name: str, claim: Claim, pubkey_hash: bytes) -> 'Output':
        script = cls.script_class.pay_claim_name_pubkey_hash(
            claim_name.encode(), claim, pubkey_hash)
        txo = cls(amount, script)
        return txo

    @classmethod
    def pay_update_claim_pubkey_hash(
            cls, amount: int, claim_name: str, claim_id: str, claim: Claim, pubkey_hash: bytes) -> 'Output':
        script = cls.script_class.pay_update_claim_pubkey_hash(
            claim_name.encode(), unhexlify(claim_id)[::-1], claim, pubkey_hash)
        txo = cls(amount, script)
        return txo

    @classmethod
    def pay_support_pubkey_hash(cls, amount: int, claim_name: str, claim_id: str, pubkey_hash: bytes) -> 'Output':
        script = cls.script_class.pay_support_pubkey_hash(claim_name.encode(), unhexlify(claim_id)[::-1], pubkey_hash)
        return cls(amount, script)

    @classmethod
    def purchase_claim_pubkey_hash(cls, amount: int, claim_id: str, pubkey_hash: bytes) -> 'Output':
        script = cls.script_class.purchase_claim_pubkey_hash(unhexlify(claim_id)[::-1], pubkey_hash)
        return cls(amount, script)


class Transaction(BaseTransaction):

    input_class = Input
    output_class = Output

    outputs: ReadOnlyList[Output]
    inputs: ReadOnlyList[Input]

    @classmethod
    def pay(cls, amount: int, address: bytes, funding_accounts: List[Account], change_account: Account):
        ledger = cls.ensure_all_have_same_ledger(funding_accounts, change_account)
        output = Output.pay_pubkey_hash(amount, ledger.address_to_hash160(address))
        return cls.create([], [output], funding_accounts, change_account)

    @classmethod
    def claim_create(
            cls, name: str, claim: Claim, amount: int, holding_address: str,
            funding_accounts: List[Account], change_account: Account, signing_channel: Output = None):
        ledger = cls.ensure_all_have_same_ledger(funding_accounts, change_account)
        claim_output = Output.pay_claim_name_pubkey_hash(
            amount, name, claim, ledger.address_to_hash160(holding_address)
        )
        if signing_channel is not None:
            claim_output.sign(signing_channel, b'placeholder txid:nout')
        return cls.create([], [claim_output], funding_accounts, change_account, sign=False)

    @classmethod
    def claim_update(
            cls, previous_claim: Output, claim: Claim, amount: int, holding_address: str,
            funding_accounts: List[Account], change_account: Account, signing_channel: Output = None):
        ledger = cls.ensure_all_have_same_ledger(funding_accounts, change_account)
        updated_claim = Output.pay_update_claim_pubkey_hash(
            amount, previous_claim.claim_name, previous_claim.claim_id,
            claim, ledger.address_to_hash160(holding_address)
        )
        if signing_channel is not None:
            updated_claim.sign(signing_channel, b'placeholder txid:nout')
        else:
            updated_claim.clear_signature()
        return cls.create(
            [Input.spend(previous_claim)], [updated_claim], funding_accounts, change_account, sign=False
        )

    @classmethod
    def support(cls, claim_name: str, claim_id: str, amount: int, holding_address: str,
                funding_accounts: List[Account], change_account: Account):
        ledger = cls.ensure_all_have_same_ledger(funding_accounts, change_account)
        support_output = Output.pay_support_pubkey_hash(
            amount, claim_name, claim_id, ledger.address_to_hash160(holding_address)
        )
        return cls.create([], [support_output], funding_accounts, change_account)

    @classmethod
    def purchase(cls, claim: Output, amount: int, merchant_address: bytes,
                 funding_accounts: List[Account], change_account: Account):
        ledger = cls.ensure_all_have_same_ledger(funding_accounts, change_account)
        claim_output = Output.purchase_claim_pubkey_hash(
            amount, claim.claim_id, ledger.address_to_hash160(merchant_address)
        )
        return cls.create([], [claim_output], funding_accounts, change_account)

    @property
    def my_inputs(self):
        for txi in self.inputs:
            if txi.txo_ref.txo is not None and txi.txo_ref.txo.is_my_account:
                yield txi

    def _filter_my_outputs(self, f):
        for txo in self.outputs:
            if txo.is_my_account and f(txo.script):
                yield txo

    def _filter_other_outputs(self, f):
        for txo in self.outputs:
            if not txo.is_my_account and f(txo.script):
                yield txo

    @property
    def my_claim_outputs(self):
        return self._filter_my_outputs(lambda s: s.is_claim_name)

    @property
    def my_update_outputs(self):
        return self._filter_my_outputs(lambda s: s.is_update_claim)

    @property
    def my_support_outputs(self):
        return self._filter_my_outputs(lambda s: s.is_support_claim)

    @property
    def other_support_outputs(self):
        return self._filter_other_outputs(lambda s: s.is_support_claim)

    @property
    def my_abandon_outputs(self):
        for txi in self.inputs:
            abandon = txi.txo_ref.txo
            if abandon is not None and abandon.is_my_account and abandon.script.is_claim_involved:
                is_update = False
                if abandon.script.is_claim_name or abandon.script.is_update_claim:
                    for update in self.my_update_outputs:
                        if abandon.claim_id == update.claim_id:
                            is_update = True
                            break
                if not is_update:
                    yield abandon
