from six import int2byte
from binascii import unhexlify

from torba.basecoin import BaseCoin

from .ledger import MainNetLedger, TestNetLedger, RegTestLedger
from .transaction import Transaction


class LBC(BaseCoin):
    name = 'LBRY Credits'
    symbol = 'LBC'
    network = 'mainnet'

    ledger_class = MainNetLedger
    transaction_class = Transaction

    secret_prefix = int2byte(0x1c)
    pubkey_address_prefix = int2byte(0x55)
    script_address_prefix = int2byte(0x7a)
    extended_public_key_prefix = unhexlify('019c354f')
    extended_private_key_prefix = unhexlify('019c3118')

    default_fee_per_byte = 50
    default_fee_per_name_char = 200000

    def __init__(self, ledger, fee_per_byte=default_fee_per_byte,
                 fee_per_name_char=default_fee_per_name_char):
        super(LBC, self).__init__(ledger, fee_per_byte)
        self.fee_per_name_char = fee_per_name_char

    def to_dict(self):
        coin_dict = super(LBC, self).to_dict()
        coin_dict['fee_per_name_char'] = self.fee_per_name_char
        return coin_dict

    def get_transaction_base_fee(self, tx):
        """ Fee for the transaction header and all outputs; without inputs. """
        return max(
            super(LBC, self).get_transaction_base_fee(tx),
            self.get_transaction_claim_name_fee(tx)
        )

    def get_transaction_claim_name_fee(self, tx):
        fee = 0
        for output in tx.outputs:
            if output.script.is_claim_name:
                fee += len(output.script.values['claim_name']) * self.fee_per_name_char
        return fee


class LBCTestNet(LBC):
    network = 'testnet'
    ledger_class = TestNetLedger
    pubkey_address_prefix = int2byte(111)
    script_address_prefix = int2byte(196)
    extended_public_key_prefix = unhexlify('043587cf')
    extended_private_key_prefix = unhexlify('04358394')


class LBCRegTest(LBC):
    network = 'regtest'
    ledger_class = RegTestLedger
    pubkey_address_prefix = int2byte(111)
    script_address_prefix = int2byte(196)
    extended_public_key_prefix = unhexlify('043587cf')
    extended_private_key_prefix = unhexlify('04358394')
