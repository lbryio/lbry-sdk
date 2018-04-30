import six
from typing import Dict, Type
from .hash import hash160, double_sha256, Base58


class CoinRegistry(type):
    coins = {}  # type: Dict[str, Type[BaseCoin]]

    def __new__(mcs, name, bases, attrs):
        cls = super(CoinRegistry, mcs).__new__(mcs, name, bases, attrs)  # type: Type[BaseCoin]
        if not (name == 'BaseCoin' and not bases):
            coin_id = cls.get_id()
            assert coin_id not in mcs.coins, 'Coin with id "{}" already registered.'.format(coin_id)
            mcs.coins[coin_id] = cls
            assert cls.ledger_class.coin_class is None, (
                "Ledger ({}) which this coin ({}) references is already referenced by another "
                "coin ({}). One to one relationship between a coin and a ledger is strictly and "
                "automatically enforced. Make sure that coin_class=None in the ledger and that "
                "another Coin isn't already referencing this Ledger."
            ).format(cls.ledger_class.__name__, name, cls.ledger_class.coin_class.__name__)
            # create back reference from ledger to the coin
            cls.ledger_class.coin_class = cls
        return cls

    @classmethod
    def get_coin_class(mcs, coin_id):  # type: (str) -> Type[BaseCoin]
        return mcs.coins[coin_id]

    @classmethod
    def get_ledger_class(mcs, coin_id):  # type: (str) -> Type[BaseLedger]
        return mcs.coins[coin_id].ledger_class


class BaseCoin(six.with_metaclass(CoinRegistry)):

    name = None
    symbol = None
    network = None

    ledger_class = None  # type: Type[BaseLedger]
    transaction_class = None  # type: Type[BaseTransaction]

    secret_prefix = None
    pubkey_address_prefix = None
    script_address_prefix = None
    extended_public_key_prefix = None
    extended_private_key_prefix = None

    def __init__(self, ledger, fee_per_byte):
        self.ledger = ledger
        self.fee_per_byte = fee_per_byte

    @classmethod
    def get_id(cls):
        return '{}_{}'.format(cls.symbol.lower(), cls.network.lower())

    def to_dict(self):
        return {'fee_per_byte': self.fee_per_byte}

    def get_input_output_fee(self, io):
        """ Fee based on size of the input / output. """
        return self.fee_per_byte * io.size

    def get_transaction_base_fee(self, tx):
        """ Fee for the transaction header and all outputs; without inputs. """
        return self.fee_per_byte * tx.base_size

    def hash160_to_address(self, h160):
        raw_address = self.pubkey_address_prefix + h160
        return Base58.encode(raw_address + double_sha256(raw_address)[0:4])

    @staticmethod
    def address_to_hash160(address):
        bytes = Base58.decode(address)
        prefix, pubkey_bytes, addr_checksum = bytes[0], bytes[1:21], bytes[21:]
        return pubkey_bytes

    def public_key_to_address(self, public_key):
        return self.hash160_to_address(hash160(public_key))

    @staticmethod
    def private_key_to_wif(private_key):
        return b'\x1c' + private_key + b'\x01'
