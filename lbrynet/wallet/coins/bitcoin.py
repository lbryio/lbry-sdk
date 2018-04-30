from six import int2byte
from binascii import unhexlify
from lbrynet.wallet.baseledger import BaseLedger
from lbrynet.wallet.basenetwork import BaseNetwork
from lbrynet.wallet.basescript import BaseInputScript, BaseOutputScript
from lbrynet.wallet.basetransaction import BaseTransaction, BaseInput, BaseOutput
from lbrynet.wallet.basecoin import BaseCoin


class Ledger(BaseLedger):
    network_class = BaseNetwork


class Input(BaseInput):
    script_class = BaseInputScript


class Output(BaseOutput):
    script_class = BaseOutputScript


class Transaction(BaseTransaction):
    input_class = BaseInput
    output_class = BaseOutput


class BTC(BaseCoin):
    name = 'Bitcoin'
    symbol = 'BTC'
    network = 'mainnet'

    ledger_class = Ledger
    transaction_class = Transaction

    pubkey_address_prefix = int2byte(0x00)
    script_address_prefix = int2byte(0x05)
    extended_public_key_prefix = unhexlify('0488b21e')
    extended_private_key_prefix = unhexlify('0488ade4')

    default_fee_per_byte = 50

    def __init__(self, ledger, fee_per_byte=default_fee_per_byte):
        super(BTC, self).__init__(ledger, fee_per_byte)
