import struct
from binascii import hexlify, unhexlify
from typing import List, Iterable  # pylint: disable=unused-import

from .account import Account  # pylint: disable=unused-import
from torba.basetransaction import BaseTransaction, BaseInput, BaseOutput
from torba.hash import hash160

from lbryschema.claim import ClaimDict  # pylint: disable=unused-import
from .script import InputScript, OutputScript


class Input(BaseInput):
    script: InputScript
    script_class = InputScript


class Output(BaseOutput):
    script: OutputScript
    script_class = OutputScript

    def get_fee(self, ledger):
        name_fee = 0
        if self.script.is_claim_name:
            name_fee = len(self.script.values['claim_name']) * ledger.fee_per_name_char
        return max(name_fee, super().get_fee(ledger))

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
    def claim(self) -> bytes:
        if self.script.is_claim_involved:
            return self.script.values['claim']
        raise ValueError('No claim associated.')

    @classmethod
    def pay_claim_name_pubkey_hash(
            cls, amount: int, claim_name: str, claim: bytes, pubkey_hash: bytes) -> 'Output':
        script = cls.script_class.pay_claim_name_pubkey_hash(
            claim_name.encode(), claim, pubkey_hash)
        return cls(amount, script)

    @classmethod
    def purchase_claim_pubkey_hash(cls, amount: int, claim_id: str, pubkey_hash: bytes) -> 'Output':
        script = cls.script_class.purchase_claim_pubkey_hash(unhexlify(claim_id)[::-1], pubkey_hash)
        return cls(amount, script)

    @classmethod
    def pay_update_claim_pubkey_hash(
            cls, amount: int, claim_name: str, claim_id: str, claim: bytes, pubkey_hash: bytes) -> 'Output':
        script = cls.script_class.pay_update_claim_pubkey_hash(
            claim_name.encode(), unhexlify(claim_id)[::-1], claim, pubkey_hash)
        return cls(amount, script)


class Transaction(BaseTransaction):

    input_class = Input
    output_class = Output

    @classmethod
    def pay(cls, amount: int, address: bytes, funding_accounts: List[Account], change_account: Account):
        ledger = cls.ensure_all_have_same_ledger(funding_accounts, change_account)
        hash_of_address = ledger.address_to_hash160(address)

        output = Output.pay_pubkey_hash(amount, hash_of_address)

        return cls.create([], [output], funding_accounts, change_account)

    @classmethod
    def claim(cls, name: str, meta: ClaimDict, amount: int, holding_address: bytes,
              funding_accounts: List[Account], change_account: Account):
        ledger = cls.ensure_all_have_same_ledger(funding_accounts, change_account)
        claim_output = Output.pay_claim_name_pubkey_hash(
            amount, name, meta.serialized, ledger.address_to_hash160(holding_address)
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
    def update(cls, previous_claim: Output, meta: ClaimDict, amount: int, holding_address: bytes,
               funding_accounts: List[Account], change_account: Account):
        ledger = cls.ensure_all_have_same_ledger(funding_accounts, change_account)
        updated_claim = Output.pay_update_claim_pubkey_hash(
            amount, previous_claim.claim_name, previous_claim.claim_id,
            meta.serialized, ledger.address_to_hash160(holding_address)
        )
        return cls.create([Input.spend(previous_claim)], [updated_claim], funding_accounts, change_account)

    @classmethod
    def abandon(cls, claims: Iterable[Output], funding_accounts: Iterable[Account], change_account: Account):
        return cls.create([Input.spend(txo) for txo in claims], [], funding_accounts, change_account)
