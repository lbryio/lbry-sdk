import struct

from torba.basetransaction import BaseTransaction, BaseInput, BaseOutput
from torba.hash import hash160

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
        output = self._outputs[output_index]
        assert output.script.is_claim_name(), 'Not a name claim.'
        return claim_id_hash(self.hash, output_index)
