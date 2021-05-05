import typing
import struct
from lbry.wallet.server.db import DB_PREFIXES


def length_encoded_name(name: str) -> bytes:
    encoded = name.encode('utf-8')
    return len(encoded).to_bytes(2, byteorder='big') + encoded


class PrefixRow:
    prefix: bytes
    key_struct: struct.Struct
    value_struct: struct.Struct

    @classmethod
    def pack_key(cls, *args) -> bytes:
        return cls.prefix + cls.key_struct.pack(*args)

    @classmethod
    def pack_value(cls, *args) -> bytes:
        return cls.value_struct.pack(*args)

    @classmethod
    def unpack_key(cls, key: bytes):
        assert key[:1] == cls.prefix
        return cls.key_struct.unpack(key[1:])

    @classmethod
    def unpack_value(cls, data: bytes):
        return cls.value_struct.unpack(data)

    @classmethod
    def unpack_item(cls, key: bytes, value: bytes):
        return cls.unpack_key(key), cls.unpack_value(value)


class EffectiveAmountKey(typing.NamedTuple):
    name: str
    effective_amount: int
    tx_num: int
    position: int


class EffectiveAmountValue(typing.NamedTuple):
    claim_hash: bytes
    root_tx_num: int
    root_position: int
    activation: int


class ClaimToTXOKey(typing.NamedTuple):
    claim_hash: bytes
    tx_num: int
    position: int


class ClaimToTXOValue(typing.NamedTuple):
    root_tx_num: int
    root_position: int
    amount: int
    activation: int
    name: str


class TXOToClaimKey(typing.NamedTuple):
    tx_num: int
    position: int


class TXOToClaimValue(typing.NamedTuple):
    claim_hash: bytes
    name: str


class ClaimShortIDKey(typing.NamedTuple):
    name: str
    claim_hash: bytes
    root_tx_num: int
    root_position: int


class ClaimShortIDValue(typing.NamedTuple):
    tx_num: int
    position: int
    activation: int


class ClaimToChannelKey(typing.NamedTuple):
    claim_hash: bytes


class ClaimToChannelValue(typing.NamedTuple):
    signing_hash: bytes


class ChannelToClaimKey(typing.NamedTuple):
    signing_hash: bytes
    name: str
    effective_amount: int
    tx_num: int
    position: int


class ChannelToClaimValue(typing.NamedTuple):
    claim_hash: bytes
    claims_in_channel: int


class ClaimToSupportKey(typing.NamedTuple):
    claim_hash: bytes
    tx_num: int
    position: int


class ClaimToSupportValue(typing.NamedTuple):
    amount: int


class SupportToClaimKey(typing.NamedTuple):
    tx_num: int
    position: int


class SupportToClaimValue(typing.NamedTuple):
    claim_hash: bytes


class ClaimExpirationKey(typing.NamedTuple):
    expiration: int
    tx_num: int
    position: int


class ClaimExpirationValue(typing.NamedTuple):
    claim_hash: bytes
    name: str


class ClaimTakeoverKey(typing.NamedTuple):
    name: str


class ClaimTakeoverValue(typing.NamedTuple):
    claim_hash: bytes
    height: int


class PendingActivationKey(typing.NamedTuple):
    height: int
    tx_num: int
    position: int


class PendingActivationValue(typing.NamedTuple):
    claim_hash: bytes
    name: str


class EffectiveAmountPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.claim_effective_amount_prefix.value
    key_struct = struct.Struct(b'>QLH')
    value_struct = struct.Struct(b'>20sLHL')

    @classmethod
    def pack_key(cls, name: str, effective_amount: int, tx_num: int, position: int):
        return cls.prefix + length_encoded_name(name) + cls.key_struct.pack(
            0xffffffffffffffff - effective_amount, tx_num, position
        )

    @classmethod
    def unpack_key(cls, key: bytes) -> EffectiveAmountKey:
        assert key[:1] == cls.prefix
        name_len = int.from_bytes(key[1:3], byteorder='big')
        name = key[3:3 + name_len].decode()
        ones_comp_effective_amount, tx_num, position = cls.key_struct.unpack(key[3 + name_len:])
        return EffectiveAmountKey(
            name, 0xffffffffffffffff - ones_comp_effective_amount, tx_num, position
        )

    @classmethod
    def unpack_value(cls, data: bytes) -> EffectiveAmountValue:
        return EffectiveAmountValue(*super().unpack_value(data))

    @classmethod
    def pack_value(cls, claim_hash: bytes, root_tx_num: int, root_position: int, activation: int) -> bytes:
        return super().pack_value(claim_hash, root_tx_num, root_position, activation)

    @classmethod
    def pack_item(cls, name: str, effective_amount: int, tx_num: int, position: int, claim_hash: bytes,
                  root_tx_num: int, root_position: int, activation: int):
        return cls.pack_key(name, effective_amount, tx_num, position), \
               cls.pack_value(claim_hash, root_tx_num, root_position, activation)


class ClaimToTXOPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.claim_to_txo.value
    key_struct = struct.Struct(b'>20sLH')
    value_struct = struct.Struct(b'>LHQL')

    @classmethod
    def pack_key(cls, claim_hash: bytes, tx_num: int, position: int):
        return super().pack_key(
            claim_hash, 0xffffffff - tx_num, 0xffff - position
        )

    @classmethod
    def unpack_key(cls, key: bytes) -> ClaimToTXOKey:
        assert key[:1] == cls.prefix
        claim_hash, ones_comp_tx_num, ones_comp_position = cls.key_struct.unpack(key[1:])
        return ClaimToTXOKey(
            claim_hash, 0xffffffff - ones_comp_tx_num, 0xffff - ones_comp_position
        )

    @classmethod
    def unpack_value(cls, data: bytes) -> ClaimToTXOValue:
        root_tx_num, root_position, amount, activation = cls.value_struct.unpack(data[:18])
        name_len = int.from_bytes(data[18:20], byteorder='big')
        name = data[20:20 + name_len].decode()
        return ClaimToTXOValue(root_tx_num, root_position, amount, activation, name)

    @classmethod
    def pack_value(cls, root_tx_num: int, root_position: int, amount: int, activation: int, name: str) -> bytes:
        return cls.value_struct.pack(root_tx_num, root_position, amount, activation) + length_encoded_name(name)

    @classmethod
    def pack_item(cls, claim_hash: bytes, tx_num: int, position: int, root_tx_num: int, root_position: int,
                  amount: int, activation: int, name: str):
        return cls.pack_key(claim_hash, tx_num, position), \
               cls.pack_value(root_tx_num, root_position, amount, activation, name)


class TXOToClaimPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.txo_to_claim.value
    key_struct = struct.Struct(b'>LH')
    value_struct = struct.Struct(b'>20s')

    @classmethod
    def pack_key(cls, tx_num: int, position: int):
        return super().pack_key(tx_num, position)

    @classmethod
    def unpack_key(cls, key: bytes) -> TXOToClaimKey:
        return TXOToClaimKey(*super().unpack_key(key))

    @classmethod
    def unpack_value(cls, data: bytes) -> TXOToClaimValue:
        claim_hash, = cls.value_struct.unpack(data[:20])
        name_len = int.from_bytes(data[20:22], byteorder='big')
        name = data[22:22 + name_len].decode()
        return TXOToClaimValue(claim_hash, name)

    @classmethod
    def pack_value(cls, claim_hash: bytes, name: str) -> bytes:
        return cls.value_struct.pack(claim_hash) + length_encoded_name(name)

    @classmethod
    def pack_item(cls, tx_num: int, position: int, claim_hash: bytes, name: str):
        return cls.pack_key(tx_num, position), \
               cls.pack_value(claim_hash, name)


class ClaimShortIDPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.claim_short_id_prefix.value
    key_struct = struct.Struct(b'>20sLH')
    value_struct = struct.Struct(b'>LHL')

    @classmethod
    def pack_key(cls, name: str, claim_hash: bytes, root_tx_num: int, root_position: int):
        return cls.prefix + length_encoded_name(name) + cls.key_struct.pack(claim_hash, root_tx_num, root_position)

    @classmethod
    def pack_value(cls, tx_num: int, position: int, activation: int):
        return super().pack_value(tx_num, position, activation)

    @classmethod
    def unpack_key(cls, key: bytes) -> ClaimShortIDKey:
        assert key[:1] == cls.prefix
        name_len = int.from_bytes(key[1:3], byteorder='big')
        name = key[3:3 + name_len].decode()
        return ClaimShortIDKey(name, *cls.key_struct.unpack(key[3 + name_len:]))

    @classmethod
    def unpack_value(cls, data: bytes) -> ClaimShortIDValue:
        return ClaimShortIDValue(*super().unpack_value(data))

    @classmethod
    def pack_item(cls, name: str, claim_hash: bytes, root_tx_num: int, root_position: int,
                  tx_num: int, position: int, activation: int):
        return cls.pack_key(name, claim_hash, root_tx_num, root_position), \
               cls.pack_value(tx_num, position, activation)


class ClaimToChannelPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.claim_to_channel.value
    key_struct = struct.Struct(b'>20s')
    value_struct = struct.Struct(b'>20s')

    @classmethod
    def pack_key(cls, claim_hash: bytes):
        return super().pack_key(claim_hash)

    @classmethod
    def pack_value(cls, signing_hash: bytes):
        return super().pack_value(signing_hash)

    @classmethod
    def unpack_key(cls, key: bytes) -> ClaimToChannelKey:
        return ClaimToChannelKey(*super().unpack_key(key))

    @classmethod
    def unpack_value(cls, data: bytes) -> ClaimToChannelValue:
        return ClaimToChannelValue(*super().unpack_value(data))

    @classmethod
    def pack_item(cls, claim_hash: bytes, signing_hash: bytes):
        return cls.pack_key(claim_hash), cls.pack_value(signing_hash)


class ChannelToClaimPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.channel_to_claim.value
    key_struct = struct.Struct(b'>QLH')
    value_struct = struct.Struct(b'>20sL')

    @classmethod
    def pack_key(cls, signing_hash: bytes, name: str, effective_amount: int, tx_num: int, position: int):
        return cls.prefix + signing_hash + length_encoded_name(name) + cls.key_struct.pack(
            0xffffffffffffffff - effective_amount, tx_num, position
        )

    @classmethod
    def unpack_key(cls, key: bytes) -> ChannelToClaimKey:
        assert key[:1] == cls.prefix
        signing_hash = key[1:21]
        name_len = int.from_bytes(key[21:23], byteorder='big')
        name = key[23:23 + name_len].decode()
        ones_comp_effective_amount, tx_num, position = cls.key_struct.unpack(key[23 + name_len:])
        return ChannelToClaimKey(
            signing_hash, name, 0xffffffffffffffff - ones_comp_effective_amount, tx_num, position
        )

    @classmethod
    def pack_value(cls, claim_hash: bytes, claims_in_channel: int) -> bytes:
        return super().pack_value(claim_hash, claims_in_channel)

    @classmethod
    def unpack_value(cls, data: bytes) -> ChannelToClaimValue:
        return ChannelToClaimValue(*cls.value_struct.unpack(data))

    @classmethod
    def pack_item(cls, signing_hash: bytes, name: str, effective_amount: int, tx_num: int, position: int,
                  claim_hash: bytes, claims_in_channel: int):
        return cls.pack_key(signing_hash, name, effective_amount, tx_num, position), \
               cls.pack_value(claim_hash, claims_in_channel)


class ClaimToSupportPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.claim_to_support.value
    key_struct = struct.Struct(b'>20sLH')
    value_struct = struct.Struct(b'>Q')

    @classmethod
    def pack_key(cls, claim_hash: bytes, tx_num: int, position: int):
        return super().pack_key(claim_hash, tx_num, position)

    @classmethod
    def unpack_key(cls, key: bytes) -> ClaimToSupportKey:
        return ClaimToSupportKey(*super().unpack_key(key))

    @classmethod
    def pack_value(cls, amount: int) -> bytes:
        return super().pack_value(amount)

    @classmethod
    def unpack_value(cls, data: bytes) -> ClaimToSupportValue:
        return ClaimToSupportValue(*super().unpack_value(data))

    @classmethod
    def pack_item(cls, claim_hash: bytes, tx_num: int, position: int, amount: int):
        return cls.pack_key(claim_hash, tx_num, position), \
               cls.pack_value(amount)


class SupportToClaimPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.support_to_claim.value
    key_struct = struct.Struct(b'>LH')
    value_struct = struct.Struct(b'>20s')

    @classmethod
    def pack_key(cls, tx_num: int, position: int):
        return super().pack_key(tx_num, position)

    @classmethod
    def unpack_key(cls, key: bytes) -> SupportToClaimKey:
        return SupportToClaimKey(*super().unpack_key(key))

    @classmethod
    def pack_value(cls, claim_hash: bytes) -> bytes:
        return super().pack_value(claim_hash)

    @classmethod
    def unpack_value(cls, data: bytes) -> SupportToClaimValue:
        return SupportToClaimValue(*super().unpack_value(data))

    @classmethod
    def pack_item(cls, tx_num: int, position: int, claim_hash: bytes):
        return cls.pack_key(tx_num, position), \
               cls.pack_value(claim_hash)


class ClaimExpirationPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.claim_expiration.value
    key_struct = struct.Struct(b'>LLH')
    value_struct = struct.Struct(b'>20s')

    @classmethod
    def pack_key(cls, expiration: int, tx_num: int, position: int) -> bytes:
        return super().pack_key(expiration, tx_num, position)

    @classmethod
    def pack_value(cls, claim_hash: bytes, name: str) -> bytes:
        return cls.value_struct.pack(claim_hash) + length_encoded_name(name)

    @classmethod
    def pack_item(cls, expiration: int, tx_num: int, position: int, claim_hash: bytes, name: str) -> typing.Tuple[bytes, bytes]:
        return cls.pack_key(expiration, tx_num, position), cls.pack_value(claim_hash, name)

    @classmethod
    def unpack_key(cls, key: bytes) -> ClaimExpirationKey:
        return ClaimExpirationKey(*super().unpack_key(key))

    @classmethod
    def unpack_value(cls, data: bytes) -> ClaimExpirationValue:
        name_len = int.from_bytes(data[20:22], byteorder='big')
        name = data[22:22 + name_len].decode()
        claim_id, = cls.value_struct.unpack(data[:20])
        return ClaimExpirationValue(claim_id, name)

    @classmethod
    def unpack_item(cls, key: bytes, value: bytes) -> typing.Tuple[ClaimExpirationKey, ClaimExpirationValue]:
        return cls.unpack_key(key), cls.unpack_value(value)


class ClaimTakeoverPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.claim_takeover.value
    value_struct = struct.Struct(b'>20sL')

    @classmethod
    def pack_key(cls, name: str):
        return cls.prefix + length_encoded_name(name)

    @classmethod
    def pack_value(cls, claim_hash: bytes, takeover_height: int):
        return super().pack_value(claim_hash, takeover_height)

    @classmethod
    def unpack_key(cls, key: bytes) -> ClaimTakeoverKey:
        assert key[:1] == cls.prefix
        name_len = int.from_bytes(key[1:3], byteorder='big')
        name = key[3:3 + name_len].decode()
        return ClaimTakeoverKey(name)

    @classmethod
    def unpack_value(cls, data: bytes) -> ClaimTakeoverValue:
        return ClaimTakeoverValue(*super().unpack_value(data))

    @classmethod
    def pack_item(cls, name: str, claim_hash: bytes, takeover_height: int):
        return cls.pack_key(name), cls.pack_value(claim_hash, takeover_height)


class PendingClaimActivationPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.pending_activation.value
    key_struct = struct.Struct(b'>LLH')

    @classmethod
    def pack_key(cls, height: int, tx_num: int, position: int):
        return super().pack_key(height, tx_num, position)

    @classmethod
    def unpack_key(cls, key: bytes) -> PendingActivationKey:
        return PendingActivationKey(*super().unpack_key(key))

    @classmethod
    def pack_value(cls, claim_hash: bytes, name: str) -> bytes:
        return claim_hash + length_encoded_name(name)

    @classmethod
    def unpack_value(cls, data: bytes) -> PendingActivationValue:
        claim_hash = data[:20]
        name_len = int.from_bytes(data[20:22], byteorder='big')
        name = data[22:22 + name_len].decode()
        return PendingActivationValue(claim_hash, name)

    @classmethod
    def pack_item(cls, height: int, tx_num: int, position: int, claim_hash: bytes, name: str):
        return cls.pack_key(height, tx_num, position), \
               cls.pack_value(claim_hash, name)


class Prefixes:
    claim_to_support = ClaimToSupportPrefixRow
    support_to_claim = SupportToClaimPrefixRow

    claim_to_txo = ClaimToTXOPrefixRow
    txo_to_claim = TXOToClaimPrefixRow

    claim_to_channel = ClaimToChannelPrefixRow
    channel_to_claim = ChannelToClaimPrefixRow

    claim_short_id = ClaimShortIDPrefixRow
    claim_effective_amount = EffectiveAmountPrefixRow
    claim_expiration = ClaimExpirationPrefixRow

    claim_takeover = ClaimTakeoverPrefixRow
    pending_activation = PendingClaimActivationPrefixRow

    # undo_claimtrie = b'M'
