import struct
from binascii import hexlify, unhexlify
from typing import List, Iterable, Optional

import ecdsa
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import load_der_public_key
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
from ecdsa.util import sigencode_der

from torba.client.basetransaction import BaseTransaction, BaseInput, BaseOutput
from torba.client.hash import hash160, sha256, Base58
from lbrynet.schema.claim import Claim
from lbrynet.wallet.account import Account
from lbrynet.wallet.script import InputScript, OutputScript


class Input(BaseInput):
    script: InputScript
    script_class = InputScript


class Output(BaseOutput):
    script: OutputScript
    script_class = OutputScript

    __slots__ = '_claim', 'channel', 'private_key'

    def __init__(self, *args, channel: Optional['Output'] = None,
                 private_key: Optional[str] = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._claim = None
        self.channel = channel
        self.private_key = private_key

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
    def claim_id(self) -> str:
        if self.script.is_claim_name:
            claim_id = hash160(self.tx_ref.hash + struct.pack('>I', self.position))
        elif self.script.is_update_claim or self.script.is_support_claim:
            claim_id = self.script.values['claim_id']
        else:
            raise ValueError('No claim_id associated.')
        return hexlify(claim_id[::-1]).decode()

    @property
    def claim_name(self) -> str:
        if self.script.is_claim_involved:
            return self.script.values['claim_name'].decode()
        raise ValueError('No claim_name associated.')

    @property
    def claim(self) -> Claim:
        if self.is_claim:
            if self._claim is None:
                self._claim = Claim.from_bytes(self.script.values['claim'])
            return self._claim
        raise ValueError('Only claim name and claim update have the claim payload.')

    @property
    def permanent_url(self) -> str:
        if self.script.is_claim_involved:
            if self.channel is not None:
                return "{}#{}/{}".format(
                    self.channel.claim_name,
                    self.channel.claim_id,
                    self.claim_name
                )
            return f"{self.claim_name}#{self.claim_id}"
        raise ValueError('No claim associated.')

    @property
    def has_private_key(self):
        return self.private_key is not None

    def is_signed_by(self, channel: 'Output', ledger):
        if self.claim.unsigned_payload:
            digest = sha256(b''.join([
                Base58.decode(self.get_address(ledger)),
                self.claim.unsigned_payload,
                self.claim.certificate_id
            ]))
            public_key = load_der_public_key(channel.claim.channel.public_key_bytes, default_backend())
            hash = hashes.SHA256()
            signature = hexlify(self.claim.signature)
            r = int(signature[:int(len(signature)/2)], 16)
            s = int(signature[int(len(signature)/2):], 16)
            encoded_sig = sigencode_der(r, s, len(signature)*4)
            public_key.verify(encoded_sig, digest, ec.ECDSA(Prehashed(hash)))
            return True
        else:
            digest = sha256(b''.join([
                self.certificate_id.encode(),
                first_input_txid_nout.encode(),
                self.to_bytes()
            ])).digest()

    def sign(self, channel: 'Output'):
        digest = sha256(b''.join([
            certificate_id.encode(),
            first_input_txid_nout.encode(),
            self.to_bytes()
        ])).digest()
        private_key = ecdsa.SigningKey.from_pem(private_key_text, hashfunc="sha256")
        self.signature = private_key.sign_digest_deterministic(digest, hashfunc="sha256")
        self.certificate_id = certificate_id
        self.script.values['claim'] = self._claim.to_bytes()

    @classmethod
    def pay_claim_name_pubkey_hash(
            cls, amount: int, claim_name: str, claim: Claim, pubkey_hash: bytes) -> 'Output':
        script = cls.script_class.pay_claim_name_pubkey_hash(
            claim_name.encode(), claim.to_bytes(), pubkey_hash)
        txo = cls(amount, script)
        txo._claim = claim
        return txo

    @classmethod
    def pay_update_claim_pubkey_hash(
            cls, amount: int, claim_name: str, claim_id: str, claim: Claim, pubkey_hash: bytes) -> 'Output':
        script = cls.script_class.pay_update_claim_pubkey_hash(
            claim_name.encode(), unhexlify(claim_id)[::-1], claim, pubkey_hash)
        txo = cls(amount, script)
        txo._claim = claim
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

    @classmethod
    def pay(cls, amount: int, address: bytes, funding_accounts: List[Account], change_account: Account):
        ledger = cls.ensure_all_have_same_ledger(funding_accounts, change_account)
        output = Output.pay_pubkey_hash(amount, ledger.address_to_hash160(address))
        return cls.create([], [output], funding_accounts, change_account)

    @classmethod
    def claim(cls, name: str, claim: Claim, amount: int, holding_address: bytes,
              funding_accounts: List[Account], change_account: Account):
        ledger = cls.ensure_all_have_same_ledger(funding_accounts, change_account)
        claim_output = Output.pay_claim_name_pubkey_hash(
            amount, name, claim, ledger.address_to_hash160(holding_address)
        )
        return cls.create([], [claim_output], funding_accounts, change_account)

    @classmethod
    def purchase(cls, claim: Output, amount: int, merchant_address: bytes,
              funding_accounts: List[Account], change_account: Account):
        ledger = cls.ensure_all_have_same_ledger(funding_accounts, change_account)
        claim_output = Output.purchase_claim_pubkey_hash(
            amount, claim.claim_id, ledger.address_to_hash160(merchant_address)
        )
        return cls.create([], [claim_output], funding_accounts, change_account)

    @classmethod
    def update(cls, previous_claim: Output, claim: Claim, amount: int, holding_address: bytes,
               funding_accounts: List[Account], change_account: Account):
        ledger = cls.ensure_all_have_same_ledger(funding_accounts, change_account)
        updated_claim = Output.pay_update_claim_pubkey_hash(
            amount, previous_claim.claim_name, previous_claim.claim_id,
            claim, ledger.address_to_hash160(holding_address)
        )
        return cls.create([Input.spend(previous_claim)], [updated_claim], funding_accounts, change_account)

    @classmethod
    def support(cls, claim_name: str, claim_id: str, amount: int, holding_address: bytes,
                funding_accounts: List[Account], change_account: Account):
        ledger = cls.ensure_all_have_same_ledger(funding_accounts, change_account)
        output = Output.pay_support_pubkey_hash(
            amount, claim_name, claim_id, ledger.address_to_hash160(holding_address)
        )
        return cls.create([], [output], funding_accounts, change_account)

    @classmethod
    def abandon(cls, claims: Iterable[Output], funding_accounts: Iterable[Account], change_account: Account):
        return cls.create([Input.spend(txo) for txo in claims], [], funding_accounts, change_account)

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
