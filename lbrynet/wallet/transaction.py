import struct
from binascii import hexlify
from typing import List

from twisted.internet import defer

from torba.baseaccount import BaseAccount
from torba.basetransaction import BaseTransaction, BaseInput, BaseOutput
from torba.hash import hash160

from lbryschema.claim import ClaimDict
from .script import InputScript, OutputScript


def claim_id_hash(txid, n):
    return hash160(txid + struct.pack('>I', n))


class Input(BaseInput):
    script_class = InputScript


class Output(BaseOutput):
    script_class = OutputScript

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
    def claim(cls, name, meta, amount, holding_address, funding_accounts, change_account):
        # type: (bytes, ClaimDict, int, bytes, List[BaseAccount], BaseAccount) -> defer.Deferred
        ledger = cls.ensure_all_have_same_ledger(funding_accounts, change_account)
        claim_output = Output.pay_claim_name_pubkey_hash(
            amount, name, hexlify(meta.serialized), ledger.address_to_hash160(holding_address)
        )
        return cls.pay([claim_output], funding_accounts, change_account)
