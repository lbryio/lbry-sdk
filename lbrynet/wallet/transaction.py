import struct
from binascii import hexlify, unhexlify
from typing import List, Iterable, Optional

from .account import Account
from torba.basetransaction import BaseTransaction, BaseInput, BaseOutput
from torba.hash import hash160

from lbryschema.claim import ClaimDict
from .script import InputScript, OutputScript


class Input(BaseInput):
    script: InputScript
    script_class = InputScript


class Output(BaseOutput):
    script: OutputScript
    script_class = OutputScript

    __slots__ = '_claim_dict', 'channel', 'signature'

    def __init__(self, *args, channel: Optional['Output'] = None,
                 signature: Optional[str] = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._claim_dict = None
        self.channel = channel
        self.signature = signature

    def update_annotations(self, annotated):
        super().update_annotations(annotated)
        self.channel = annotated.channel if annotated else None
        self.signature = annotated.signature if annotated else None

    def get_fee(self, ledger):
        name_fee = 0
        if self.script.is_name:
            name_fee = len(self.script.values['name']) * ledger.fee_per_name_char
        return max(name_fee, super().get_fee(ledger))

    @property
    def claim_id(self) -> str:
        if self.script.is_name:
            claim_id = hash160(self.tx_ref.hash + struct.pack('>I', self.position))
        elif self.script.is_update_claim or self.script.is_support_claim:
            claim_id = self.script.values['claim_id']
        else:
            raise ValueError('No claim_id associated.')
        return hexlify(claim_id[::-1]).decode()

    @property
    def name(self) -> str:
        if self.script.is_claim_involved:
            return self.script.values['name'].decode()
        raise ValueError('No name associated.')

    @property
    def claim(self) -> ClaimDict:
        if self.script.is_name or self.script.is_update_claim:
            return ClaimDict.deserialize(self.script.values['claim'])
        raise ValueError('Only claim name and claim update have the claim payload.')

    @property
    def claim_dict(self) -> dict:
        if self._claim_dict is None:
            self._claim_dict = self.claim.claim_dict
        return self._claim_dict

    @property
    def permanent_url(self) -> str:
        if self.script.is_claim_involved:
            if self.channel is not None:
                return "{0}#{1}/{2}".format(
                    self.channel.name,
                    self.channel.claim_id,
                    self.name
                )
            return "{}#{}".format(self.name, self.claim_id)
        raise ValueError('No claim associated.')

    @property
    def has_signature(self):
        return self.signature is not None

    @classmethod
    def pay_name_pubkey_hash(
            cls, amount: int, name: str, claim: bytes, pubkey_hash: bytes) -> 'Output':
        script = cls.script_class.pay_name_pubkey_hash(
            name.encode(), claim, pubkey_hash)
        return cls(amount, script)

    @classmethod
    def purchase_claim_pubkey_hash(cls, amount: int, claim_id: str, pubkey_hash: bytes) -> 'Output':
        script = cls.script_class.purchase_claim_pubkey_hash(unhexlify(claim_id)[::-1], pubkey_hash)
        return cls(amount, script)

    @classmethod
    def pay_update_claim_pubkey_hash(
            cls, amount: int, name: str, claim_id: str, claim: bytes, pubkey_hash: bytes) -> 'Output':
        script = cls.script_class.pay_update_claim_pubkey_hash(
            name.encode(), unhexlify(claim_id)[::-1], claim, pubkey_hash)
        return cls(amount, script)

    @classmethod
    def pay_support_pubkey_hash(cls, amount: int, name: str, claim_id: str, pubkey_hash: bytes) -> 'Output':
        script = cls.script_class.pay_support_pubkey_hash(name.encode(), unhexlify(claim_id)[::-1], pubkey_hash)
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
    def claim(cls, name: str, meta: ClaimDict, amount: int, holding_address: bytes,
              funding_accounts: List[Account], change_account: Account):
        ledger = cls.ensure_all_have_same_ledger(funding_accounts, change_account)
        claim_output = Output.pay_name_pubkey_hash(
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
            amount, previous_claim.name, previous_claim.claim_id,
            meta.serialized, ledger.address_to_hash160(holding_address)
        )
        return cls.create([Input.spend(previous_claim)], [updated_claim], funding_accounts, change_account)

    @classmethod
    def support(cls, name: str, claim_id: str, amount: int, holding_address: bytes,
                funding_accounts: List[Account], change_account: Account):
        ledger = cls.ensure_all_have_same_ledger(funding_accounts, change_account)
        output = Output.pay_support_pubkey_hash(
            amount, name, claim_id, ledger.address_to_hash160(holding_address)
        )
        return cls.create([], [output], funding_accounts, change_account)

    @classmethod
    def abandon(cls, claims: Iterable[Output], funding_accounts: Iterable[Account], change_account: Account):
        return cls.create([Input.spend(txo) for txo in claims], [], funding_accounts, change_account)

    def _filter_my_outputs(self, f):
        for txo in self.outputs:
            if txo.is_my_account and f(txo.script):
                yield txo

    @property
    def my_claim_outputs(self):
        return self._filter_my_outputs(lambda s: s.is_name)

    @property
    def my_update_outputs(self):
        return self._filter_my_outputs(lambda s: s.is_update_claim)

    @property
    def my_support_outputs(self):
        return self._filter_my_outputs(lambda s: s.is_support_claim)

    @property
    def my_abandon_outputs(self):
        for txi in self.inputs:
            abandon = txi.txo_ref.txo
            if abandon is not None and abandon.is_my_account and abandon.script.is_claim_involved:
                is_update = False
                if abandon.script.is_name or abandon.script.is_update_claim:
                    for update in self.my_update_outputs:
                        if abandon.claim_id == update.claim_id:
                            is_update = True
                            break
                if not is_update:
                    yield abandon
