from six import int2byte
from binascii import unhexlify
from torba.baseledger import BaseLedger
from torba.basenetwork import BaseNetwork
from torba.basescript import BaseInputScript, BaseOutputScript
from torba.basetransaction import BaseTransaction, BaseInput, BaseOutput
from torba.basecoin import BaseCoin


class Ledger(BaseLedger):
    network_class = BaseNetwork


class Input(BaseInput):
    script_class = BaseInputScript


class Output(BaseOutput):
    script_class = BaseOutputScript


class Transaction(BaseTransaction):
    input_class = Input
    output_class = Output


class FTC(BaseCoin):
    name = 'Fakecoin'
    symbol = 'FTC'
    network = 'mainnet'

    ledger_class = Ledger
    transaction_class = Transaction

    pubkey_address_prefix = int2byte(0x00)
    script_address_prefix = int2byte(0x05)
    extended_public_key_prefix = unhexlify('0488b21e')
    extended_private_key_prefix = unhexlify('0488ade4')

    default_fee_per_byte = 50

    def __init__(self, ledger, fee_per_byte=default_fee_per_byte):
        super(FTC, self).__init__(ledger, fee_per_byte)
