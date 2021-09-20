import typing
import struct
from typing import Union, Tuple, NamedTuple
from lbry.wallet.server.db import DB_PREFIXES


ACTIVATED_CLAIM_TXO_TYPE = 1
ACTIVATED_SUPPORT_TXO_TYPE = 2


def length_encoded_name(name: str) -> bytes:
    encoded = name.encode('utf-8')
    return len(encoded).to_bytes(2, byteorder='big') + encoded


class PrefixRow:
    prefix: bytes
    key_struct: struct.Struct
    value_struct: struct.Struct
    key_part_lambdas = []

    @classmethod
    def pack_partial_key(cls, *args) -> bytes:
        return cls.prefix + cls.key_part_lambdas[len(args)](*args)

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


class ClaimToTXOKey(typing.NamedTuple):
    claim_hash: bytes


class ClaimToTXOValue(typing.NamedTuple):
    tx_num: int
    position: int
    root_tx_num: int
    root_position: int
    amount: int
    # activation: int
    channel_signature_is_valid: bool
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


class ClaimToChannelKey(typing.NamedTuple):
    claim_hash: bytes
    tx_num: int
    position: int


class ClaimToChannelValue(typing.NamedTuple):
    signing_hash: bytes


class ChannelToClaimKey(typing.NamedTuple):
    signing_hash: bytes
    name: str
    tx_num: int
    position: int


class ChannelToClaimValue(typing.NamedTuple):
    claim_hash: bytes


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
    txo_type: int
    tx_num: int
    position: int

    @property
    def is_support(self) -> bool:
        return self.txo_type == ACTIVATED_SUPPORT_TXO_TYPE

    @property
    def is_claim(self) -> bool:
        return self.txo_type == ACTIVATED_CLAIM_TXO_TYPE


class PendingActivationValue(typing.NamedTuple):
    claim_hash: bytes
    name: str


class ActivationKey(typing.NamedTuple):
    txo_type: int
    tx_num: int
    position: int


class ActivationValue(typing.NamedTuple):
    height: int
    claim_hash: bytes
    name: str


class ActiveAmountKey(typing.NamedTuple):
    claim_hash: bytes
    txo_type: int
    activation_height: int
    tx_num: int
    position: int


class ActiveAmountValue(typing.NamedTuple):
    amount: int


class EffectiveAmountKey(typing.NamedTuple):
    name: str
    effective_amount: int
    tx_num: int
    position: int


class EffectiveAmountValue(typing.NamedTuple):
    claim_hash: bytes


class RepostKey(typing.NamedTuple):
    claim_hash: bytes


class RepostValue(typing.NamedTuple):
    reposted_claim_hash: bytes


class RepostedKey(typing.NamedTuple):
    reposted_claim_hash: bytes
    tx_num: int
    position: int


class RepostedValue(typing.NamedTuple):
    claim_hash: bytes


class ActiveAmountPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.active_amount.value
    key_struct = struct.Struct(b'>20sBLLH')
    value_struct = struct.Struct(b'>Q')
    key_part_lambdas = [
        lambda: b'',
        struct.Struct(b'>20s').pack,
        struct.Struct(b'>20sB').pack,
        struct.Struct(b'>20sBL').pack,
        struct.Struct(b'>20sBLL').pack,
        struct.Struct(b'>20sBLLH').pack
    ]

    @classmethod
    def pack_key(cls, claim_hash: bytes, txo_type: int, activation_height: int, tx_num: int, position: int):
        return super().pack_key(claim_hash, txo_type, activation_height, tx_num, position)

    @classmethod
    def unpack_key(cls, key: bytes) -> ActiveAmountKey:
        return ActiveAmountKey(*super().unpack_key(key))

    @classmethod
    def unpack_value(cls, data: bytes) -> ActiveAmountValue:
        return ActiveAmountValue(*super().unpack_value(data))

    @classmethod
    def pack_value(cls, amount: int) -> bytes:
        return cls.value_struct.pack(amount)

    @classmethod
    def pack_item(cls, claim_hash: bytes, txo_type: int, activation_height: int, tx_num: int, position: int, amount: int):
        return cls.pack_key(claim_hash, txo_type, activation_height, tx_num, position), cls.pack_value(amount)


class ClaimToTXOPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.claim_to_txo.value
    key_struct = struct.Struct(b'>20s')
    value_struct = struct.Struct(b'>LHLHQB')
    key_part_lambdas = [
        lambda: b'',
        struct.Struct(b'>20s').pack
    ]

    @classmethod
    def pack_key(cls, claim_hash: bytes):
        return super().pack_key(
            claim_hash
        )

    @classmethod
    def unpack_key(cls, key: bytes) -> ClaimToTXOKey:
        assert key[:1] == cls.prefix and len(key) == 21
        return ClaimToTXOKey(key[1:])

    @classmethod
    def unpack_value(cls, data: bytes) -> ClaimToTXOValue:
        tx_num, position, root_tx_num, root_position, amount, channel_signature_is_valid = cls.value_struct.unpack(
            data[:21]
        )
        name_len = int.from_bytes(data[21:23], byteorder='big')
        name = data[23:23 + name_len].decode()
        return ClaimToTXOValue(
            tx_num, position, root_tx_num, root_position, amount, bool(channel_signature_is_valid), name
        )

    @classmethod
    def pack_value(cls, tx_num: int, position: int, root_tx_num: int, root_position: int, amount: int,
                   channel_signature_is_valid: bool, name: str) -> bytes:
        return cls.value_struct.pack(
            tx_num, position, root_tx_num, root_position, amount, int(channel_signature_is_valid)
        ) + length_encoded_name(name)

    @classmethod
    def pack_item(cls, claim_hash: bytes, tx_num: int, position: int, root_tx_num: int, root_position: int,
                  amount: int, channel_signature_is_valid: bool, name: str):
        return cls.pack_key(claim_hash), \
               cls.pack_value(tx_num, position, root_tx_num, root_position, amount, channel_signature_is_valid, name)


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


def shortid_key_helper(struct_fmt):
    packer = struct.Struct(struct_fmt).pack
    def wrapper(name, *args):
        return length_encoded_name(name) + packer(*args)
    return wrapper


def shortid_key_partial_claim_helper(name: str, partial_claim_hash: bytes):
    assert len(partial_claim_hash) <= 20
    return length_encoded_name(name) + partial_claim_hash


class ClaimShortIDPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.claim_short_id_prefix.value
    key_struct = struct.Struct(b'>20sLH')
    value_struct = struct.Struct(b'>LH')
    key_part_lambdas = [
        lambda: b'',
        length_encoded_name,
        shortid_key_partial_claim_helper,
        shortid_key_helper(b'>20sL'),
        shortid_key_helper(b'>20sLH'),
    ]

    @classmethod
    def pack_key(cls, name: str, claim_hash: bytes, root_tx_num: int, root_position: int):
        return cls.prefix + length_encoded_name(name) + cls.key_struct.pack(claim_hash, root_tx_num, root_position)

    @classmethod
    def pack_value(cls, tx_num: int, position: int):
        return super().pack_value(tx_num, position)

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
                  tx_num: int, position: int):
        return cls.pack_key(name, claim_hash, root_tx_num, root_position), \
               cls.pack_value(tx_num, position)


class ClaimToChannelPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.claim_to_channel.value
    key_struct = struct.Struct(b'>20sLH')
    value_struct = struct.Struct(b'>20s')

    key_part_lambdas = [
        lambda: b'',
        struct.Struct(b'>20s').pack,
        struct.Struct(b'>20sL').pack,
        struct.Struct(b'>20sLH').pack
    ]

    @classmethod
    def pack_key(cls, claim_hash: bytes, tx_num: int, position: int):
        return super().pack_key(claim_hash, tx_num, position)

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
    def pack_item(cls, claim_hash: bytes, tx_num: int, position: int, signing_hash: bytes):
        return cls.pack_key(claim_hash, tx_num, position), cls.pack_value(signing_hash)


def channel_to_claim_helper(struct_fmt):
    packer = struct.Struct(struct_fmt).pack

    def wrapper(signing_hash: bytes, name: str, *args):
        return signing_hash + length_encoded_name(name) + packer(*args)

    return wrapper


class ChannelToClaimPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.channel_to_claim.value
    key_struct = struct.Struct(b'>LH')
    value_struct = struct.Struct(b'>20s')

    key_part_lambdas = [
        lambda: b'',
        struct.Struct(b'>20s').pack,
        channel_to_claim_helper(b''),
        channel_to_claim_helper(b'>s'),
        channel_to_claim_helper(b'>L'),
        channel_to_claim_helper(b'>LH'),
    ]

    @classmethod
    def pack_key(cls, signing_hash: bytes, name: str, tx_num: int, position: int):
        return cls.prefix + signing_hash + length_encoded_name(name) + cls.key_struct.pack(
            tx_num, position
        )

    @classmethod
    def unpack_key(cls, key: bytes) -> ChannelToClaimKey:
        assert key[:1] == cls.prefix
        signing_hash = key[1:21]
        name_len = int.from_bytes(key[21:23], byteorder='big')
        name = key[23:23 + name_len].decode()
        tx_num, position = cls.key_struct.unpack(key[23 + name_len:])
        return ChannelToClaimKey(
            signing_hash, name, tx_num, position
        )

    @classmethod
    def pack_value(cls, claim_hash: bytes) -> bytes:
        return super().pack_value(claim_hash)

    @classmethod
    def unpack_value(cls, data: bytes) -> ChannelToClaimValue:
        return ChannelToClaimValue(*cls.value_struct.unpack(data))

    @classmethod
    def pack_item(cls, signing_hash: bytes, name: str, tx_num: int, position: int,
                  claim_hash: bytes):
        return cls.pack_key(signing_hash, name, tx_num, position), \
               cls.pack_value(claim_hash)


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
    key_part_lambdas = [
        lambda: b'',
        struct.Struct(b'>L').pack,
        struct.Struct(b'>LL').pack,
        struct.Struct(b'>LLH').pack,
    ]

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


class PendingActivationPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.pending_activation.value
    key_struct = struct.Struct(b'>LBLH')
    key_part_lambdas = [
        lambda: b'',
        struct.Struct(b'>L').pack,
        struct.Struct(b'>LB').pack,
        struct.Struct(b'>LBL').pack,
        struct.Struct(b'>LBLH').pack
    ]

    @classmethod
    def pack_key(cls, height: int, txo_type: int, tx_num: int, position: int):
        return super().pack_key(height, txo_type, tx_num, position)

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
    def pack_item(cls, height: int, txo_type: int, tx_num: int, position: int, claim_hash: bytes, name: str):
        return cls.pack_key(height, txo_type, tx_num, position), \
               cls.pack_value(claim_hash, name)


class ActivatedPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.activated_claim_and_support.value
    key_struct = struct.Struct(b'>BLH')
    value_struct = struct.Struct(b'>L20s')
    key_part_lambdas = [
        lambda: b'',
        struct.Struct(b'>B').pack,
        struct.Struct(b'>BL').pack,
        struct.Struct(b'>BLH').pack
    ]

    @classmethod
    def pack_key(cls, txo_type: int, tx_num: int, position: int):
        return super().pack_key(txo_type, tx_num, position)

    @classmethod
    def unpack_key(cls, key: bytes) -> ActivationKey:
        return ActivationKey(*super().unpack_key(key))

    @classmethod
    def pack_value(cls, height: int, claim_hash: bytes, name: str) -> bytes:
        return cls.value_struct.pack(height, claim_hash) + length_encoded_name(name)

    @classmethod
    def unpack_value(cls, data: bytes) -> ActivationValue:
        height, claim_hash = cls.value_struct.unpack(data[:24])
        name_len = int.from_bytes(data[24:26], byteorder='big')
        name = data[26:26 + name_len].decode()
        return ActivationValue(height, claim_hash, name)

    @classmethod
    def pack_item(cls, txo_type: int, tx_num: int, position: int, height: int, claim_hash: bytes, name: str):
        return cls.pack_key(txo_type, tx_num, position), \
               cls.pack_value(height, claim_hash, name)


def effective_amount_helper(struct_fmt):
    packer = struct.Struct(struct_fmt).pack

    def wrapper(name, *args):
        if not args:
            return length_encoded_name(name)
        if len(args) == 1:
            return length_encoded_name(name) + packer(0xffffffffffffffff - args[0])
        return length_encoded_name(name) + packer(0xffffffffffffffff - args[0], *args[1:])

    return wrapper


class EffectiveAmountPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.claim_effective_amount_prefix.value
    key_struct = struct.Struct(b'>QLH')
    value_struct = struct.Struct(b'>20s')
    key_part_lambdas = [
        lambda: b'',
        length_encoded_name,
        shortid_key_helper(b'>Q'),
        shortid_key_helper(b'>QL'),
        shortid_key_helper(b'>QLH'),
    ]

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
        return EffectiveAmountKey(name, 0xffffffffffffffff - ones_comp_effective_amount, tx_num, position)

    @classmethod
    def unpack_value(cls, data: bytes) -> EffectiveAmountValue:
        return EffectiveAmountValue(*super().unpack_value(data))

    @classmethod
    def pack_value(cls, claim_hash: bytes) -> bytes:
        return super().pack_value(claim_hash)

    @classmethod
    def pack_item(cls, name: str, effective_amount: int, tx_num: int, position: int, claim_hash: bytes):
        return cls.pack_key(name, effective_amount, tx_num, position), cls.pack_value(claim_hash)


class RepostPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.repost.value

    @classmethod
    def pack_key(cls, claim_hash: bytes):
        return cls.prefix + claim_hash

    @classmethod
    def unpack_key(cls, key: bytes) -> RepostKey:
        assert key[0] == cls.prefix
        assert len(key) == 21
        return RepostKey[1:]

    @classmethod
    def pack_value(cls, reposted_claim_hash: bytes) -> bytes:
        return reposted_claim_hash

    @classmethod
    def unpack_value(cls, data: bytes) -> RepostValue:
        return RepostValue(data)

    @classmethod
    def pack_item(cls, claim_hash: bytes, reposted_claim_hash: bytes):
        return cls.pack_key(claim_hash), cls.pack_value(reposted_claim_hash)


class RepostedPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.reposted_claim.value
    key_struct = struct.Struct(b'>20sLH')
    value_struct = struct.Struct(b'>20s')
    key_part_lambdas = [
        lambda: b'',
        struct.Struct(b'>20s').pack,
        struct.Struct(b'>20sL').pack,
        struct.Struct(b'>20sLH').pack
    ]

    @classmethod
    def pack_key(cls, reposted_claim_hash: bytes, tx_num: int, position: int):
        return super().pack_key(reposted_claim_hash, tx_num, position)

    @classmethod
    def unpack_key(cls, key: bytes) -> RepostedKey:
        return RepostedKey(*super().unpack_key(key))

    @classmethod
    def pack_value(cls, claim_hash: bytes) -> bytes:
        return super().pack_value(claim_hash)

    @classmethod
    def unpack_value(cls, data: bytes) -> RepostedValue:
        return RepostedValue(*super().unpack_value(data))

    @classmethod
    def pack_item(cls, reposted_claim_hash: bytes, tx_num: int, position: int, claim_hash: bytes):
        return cls.pack_key(reposted_claim_hash, tx_num, position), cls.pack_value(claim_hash)


class UndoPrefixRow(PrefixRow):
    prefix = DB_PREFIXES.undo_claimtrie.value
    key_struct = struct.Struct(b'>Q')

    @classmethod
    def pack_key(cls, height: int):
        return super().pack_key(height)

    @classmethod
    def unpack_key(cls, key: bytes) -> int:
        assert key[:1] == cls.prefix
        height, = cls.key_struct.unpack(key[1:])
        return height

    @classmethod
    def pack_value(cls, undo_ops: bytes) -> bytes:
        return undo_ops

    @classmethod
    def unpack_value(cls, data: bytes) -> bytes:
        return data

    @classmethod
    def pack_item(cls, height: int, undo_ops: bytes):
        return cls.pack_key(height), cls.pack_value(undo_ops)


class Prefixes:
    claim_to_support = ClaimToSupportPrefixRow
    support_to_claim = SupportToClaimPrefixRow

    claim_to_txo = ClaimToTXOPrefixRow
    txo_to_claim = TXOToClaimPrefixRow

    claim_to_channel = ClaimToChannelPrefixRow
    channel_to_claim = ChannelToClaimPrefixRow

    claim_short_id = ClaimShortIDPrefixRow
    claim_expiration = ClaimExpirationPrefixRow

    claim_takeover = ClaimTakeoverPrefixRow
    pending_activation = PendingActivationPrefixRow
    activated = ActivatedPrefixRow
    active_amount = ActiveAmountPrefixRow

    effective_amount = EffectiveAmountPrefixRow

    repost = RepostPrefixRow
    reposted_claim = RepostedPrefixRow

    undo = UndoPrefixRow


ROW_TYPES = {
    Prefixes.claim_to_support.prefix: Prefixes.claim_to_support,
    Prefixes.support_to_claim.prefix: Prefixes.support_to_claim,
    Prefixes.claim_to_txo.prefix: Prefixes.claim_to_txo,
    Prefixes.txo_to_claim.prefix: Prefixes.txo_to_claim,
    Prefixes.claim_to_channel.prefix: Prefixes.claim_to_channel,
    Prefixes.channel_to_claim.prefix: Prefixes.channel_to_claim,
    Prefixes.claim_short_id.prefix: Prefixes.claim_short_id,
    Prefixes.claim_expiration.prefix: Prefixes.claim_expiration,
    Prefixes.claim_takeover.prefix: Prefixes.claim_takeover,
    Prefixes.pending_activation.prefix: Prefixes.pending_activation,
    Prefixes.activated.prefix: Prefixes.activated,
    Prefixes.active_amount.prefix: Prefixes.active_amount,
    Prefixes.effective_amount.prefix: Prefixes.effective_amount,
    Prefixes.repost.prefix: Prefixes.repost,
    Prefixes.reposted_claim.prefix: Prefixes.reposted_claim,
    Prefixes.undo.prefix: Prefixes.undo
}


def auto_decode_item(key: bytes, value: bytes) -> Union[Tuple[NamedTuple, NamedTuple], Tuple[bytes, bytes]]:
    try:
        return ROW_TYPES[key[:1]].unpack_item(key, value)
    except KeyError:
        return key, value
