from binascii import unhexlify
from string import hexdigits
from typing import TYPE_CHECKING, Type

from lbry.crypto.hash import hash160, double_sha256
from lbry.crypto.base58 import Base58
from lbry.schema.url import URL
from .header import Headers, UnvalidatedHeaders
from .checkpoints import HASHES
from .dewies import lbc_to_dewies


if TYPE_CHECKING:
    from lbry.conf import Config


class Ledger:
    name = 'LBRY Credits'
    symbol = 'LBC'
    network_name = 'mainnet'

    headers_class = Headers

    secret_prefix = bytes((0x1c,))
    pubkey_address_prefix = bytes((0x55,))
    script_address_prefix = bytes((0x7a,))
    extended_public_key_prefix = unhexlify('0488b21e')
    extended_private_key_prefix = unhexlify('0488ade4')

    max_target = 0x0000ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = '9c89283ba0f3227f6c03b70216b9f665f0118d5e0fa729cedf4fb34d6a34f463'
    genesis_bits = 0x1f00ffff
    target_timespan = 150

    fee_per_byte = 50
    fee_per_name_char = 200000

    checkpoints = HASHES

    def __init__(self, conf: 'Config'):
        self.conf = conf
        self.coin_selection_strategy = None

    @classmethod
    def get_id(cls):
        return '{}_{}'.format(cls.symbol.lower(), cls.network_name.lower())

    @staticmethod
    def address_to_hash160(address) -> bytes:
        return Base58.decode(address)[1:21]

    @classmethod
    def pubkey_hash_to_address(cls, h160):
        raw_address = cls.pubkey_address_prefix + h160
        return Base58.encode(bytearray(raw_address + double_sha256(raw_address)[0:4]))

    @classmethod
    def public_key_to_address(cls, public_key):
        return cls.pubkey_hash_to_address(hash160(public_key))

    @classmethod
    def script_hash_to_address(cls, h160):
        raw_address = cls.script_address_prefix + h160
        return Base58.encode(bytearray(raw_address + double_sha256(raw_address)[0:4]))

    @staticmethod
    def private_key_to_wif(private_key):
        return b'\x1c' + private_key + b'\x01'

    @classmethod
    def is_valid_address(cls, address):
        decoded = Base58.decode_check(address)
        return decoded[0] == cls.pubkey_address_prefix[0]

    @classmethod
    def valid_address_or_error(cls, address):
        try:
            assert cls.is_valid_address(address)
        except:
            raise Exception(f"'{address}' is not a valid address")

    @staticmethod
    def valid_claim_id(claim_id: str):
        if not len(claim_id) == 40:
            raise Exception(f"Incorrect claimid length: {len(claim_id)}")
        if set(claim_id).difference(hexdigits):
            raise Exception("Claim id is not hex encoded")

    @staticmethod
    def valid_channel_name_or_error(name: str):
        try:
            if not name:
                raise Exception("Channel name cannot be blank.")
            parsed = URL.parse(name)
            if not parsed.has_channel:
                raise Exception("Channel names must start with '@' symbol.")
            if parsed.channel.name != name:
                raise Exception("Channel name has invalid character")
        except (TypeError, ValueError):
            raise Exception("Invalid channel name.")

    @staticmethod
    def valid_stream_name_or_error(name: str):
        try:
            if not name:
                raise Exception('Stream name cannot be blank.')
            parsed = URL.parse(name)
            if parsed.has_channel:
                raise Exception(
                    "Stream names cannot start with '@' symbol. This is reserved for channels claims."
                )
            if not parsed.has_stream or parsed.stream.name != name:
                raise Exception('Stream name has invalid characters.')
        except (TypeError, ValueError):
            raise Exception("Invalid stream name.")

    @staticmethod
    def valid_collection_name_or_error(name: str):
        try:
            if not name:
                raise Exception('Collection name cannot be blank.')
            parsed = URL.parse(name)
            if parsed.has_channel:
                raise Exception(
                    "Collection names cannot start with '@' symbol. This is reserved for channels claims."
                )
            if not parsed.has_stream or parsed.stream.name != name:
                raise Exception('Collection name has invalid characters.')
        except (TypeError, ValueError):
            raise Exception("Invalid collection name.")

    @staticmethod
    def get_dewies_or_error(argument: str, lbc: str, positive_value=False):
        try:
            dewies = lbc_to_dewies(lbc)
            if positive_value and dewies <= 0:
                raise ValueError(f"'{argument}' value must be greater than 0.0")
            return dewies
        except ValueError as e:
            raise ValueError(f"Invalid value for '{argument}': {e.args[0]}")

    def get_fee_address(self, kwargs: dict, claim_address: str) -> str:
        if 'fee_address' in kwargs:
            self.valid_address_or_error(kwargs['fee_address'])
            return kwargs['fee_address']
        if 'fee_currency' in kwargs or 'fee_amount' in kwargs:
            return claim_address


class TestNetLedger(Ledger):
    network_name = 'testnet'
    pubkey_address_prefix = bytes((111,))
    script_address_prefix = bytes((196,))
    extended_public_key_prefix = unhexlify('043587cf')
    extended_private_key_prefix = unhexlify('04358394')
    checkpoints = {}


class RegTestLedger(Ledger):
    network_name = 'regtest'
    headers_class = UnvalidatedHeaders
    pubkey_address_prefix = bytes((111,))
    script_address_prefix = bytes((196,))
    extended_public_key_prefix = unhexlify('043587cf')
    extended_private_key_prefix = unhexlify('04358394')

    max_target = 0x7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = '6e3fcf1299d4ec5d79c3a4c91d624a4acf9e2e173d95a1a0504f677669687556'
    genesis_bits = 0x207fffff
    target_timespan = 1
    checkpoints = {}


def ledger_class_from_name(name) -> Type[Ledger]:
    return {
        Ledger.network_name: Ledger,
        TestNetLedger.network_name: TestNetLedger,
        RegTestLedger.network_name: RegTestLedger
    }[name]
