import struct
from typing import List, Iterable  # pylint: disable=unused-import

from twisted.internet import defer  # pylint: disable=unused-import

from .account import Account  # pylint: disable=unused-import
from torba.basetransaction import BaseTransaction, BaseInput, BaseOutput
from torba.hash import hash160

from lbryschema.claim import ClaimDict  # pylint: disable=unused-import
from .script import InputScript, OutputScript


def claim_id_hash(tx_hash, n):
    return hash160(tx_hash + struct.pack('>I', n))


class Input(BaseInput):
    script_class = InputScript


class Output(BaseOutput):
    script_class = OutputScript

    def get_fee(self, ledger):
        name_fee = 0
        if self.script.is_claim_name:
            name_fee = len(self.script.values['claim_name']) * ledger.fee_per_name_char
        return max(name_fee, super().get_fee(ledger))

    @classmethod
    def pay_claim_name_pubkey_hash(cls, amount, claim_name, claim, pubkey_hash):
        script = cls.script_class.pay_claim_name_pubkey_hash(claim_name, claim, pubkey_hash)
        return cls(amount, script)


class Transaction(BaseTransaction):

    input_class = Input
    output_class = Output

    def get_claim_id(self, output_index):
        output = self.outputs[output_index]  # type: Output
        assert output.script.is_claim_name, 'Not a name claim.'
        return claim_id_hash(self.hash, output_index)

    @classmethod
    def claim(cls, name, meta, amount, holding_address, funding_accounts, change_account, spend=None):
        # type: (bytes, ClaimDict, int, bytes, List[Account], Account) -> defer.Deferred
        ledger = cls.ensure_all_have_same_ledger(funding_accounts, change_account)
        claim_output = Output.pay_claim_name_pubkey_hash(
            amount, name, meta.serialized, ledger.address_to_hash160(holding_address)
        )
        return cls.create(spend or [], [claim_output], funding_accounts, change_account)

    @classmethod
    def abandon(cls, claims: Iterable[Output], funding_accounts: Iterable[Account], change_account: Account):
        return cls.create([Input.spend(txo) for txo in claims], [], funding_accounts, change_account)
