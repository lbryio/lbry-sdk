import six
import lbrynet.schema
from lbrynet.schema.base import b58encode, b58decode, validate_b58_checksum
from lbrynet.schema.hashing import double_sha256, hash160
from lbrynet.schema.error import InvalidAddress
from lbrynet.schema.schema import ADDRESS_LENGTH, ADDRESS_PREFIXES, PUBKEY_ADDRESS, SCRIPT_ADDRESS


def validate_address_length(addr_bytes):
    if len(addr_bytes) != ADDRESS_LENGTH:
        raise InvalidAddress("Invalid address length: %i" % len(addr_bytes))


def validate_address_prefix(addr_bytes):
    if six.PY3:
        prefix = addr_bytes[0]
    else:
        prefix = ord(addr_bytes[0])
    if prefix not in ADDRESS_PREFIXES[lbrynet.schema.BLOCKCHAIN_NAME].values():
        raise InvalidAddress("Invalid address prefix: %.2X" % prefix)


def validate_lbrycrd_address_bytes(addr_bytes):
    validate_address_length(addr_bytes)
    validate_address_prefix(addr_bytes)
    validate_b58_checksum(addr_bytes)
    return addr_bytes


def decode_address(v):
    """decode and validate a b58 address"""
    return validate_lbrycrd_address_bytes(b58decode(v))


def encode_address(addr_bytes):
    """validate and encode an address as b58"""
    v = validate_lbrycrd_address_bytes(addr_bytes)
    return b58encode(v)


def hash_160_bytes_to_address(h160, addrtype=PUBKEY_ADDRESS):
    if addrtype == PUBKEY_ADDRESS:
        prefix = chr(ADDRESS_PREFIXES[lbrynet.schema.BLOCKCHAIN_NAME][PUBKEY_ADDRESS])
    elif addrtype == SCRIPT_ADDRESS:
        prefix = chr(ADDRESS_PREFIXES[lbrynet.schema.BLOCKCHAIN_NAME][SCRIPT_ADDRESS])
    else:
        raise Exception("Invalid address prefix")
    return b58encode(prefix + h160 + double_sha256(prefix + h160)[0:4])


def public_key_to_address(public_key):
    return hash_160_bytes_to_address(hash160(public_key))


def address_to_hash_160(addr):
    bytes = decode_address(addr)
    prefix, pubkey_bytes, addr_checksum = bytes[0], bytes[1:21], bytes[21:]
    if prefix == chr(ADDRESS_PREFIXES[lbrynet.schema.BLOCKCHAIN_NAME][PUBKEY_ADDRESS]):
        return PUBKEY_ADDRESS, pubkey_bytes
    return SCRIPT_ADDRESS, pubkey_bytes


def is_address(addr):
    try:
        addr_bytes = decode_address(addr)
        return True
    except InvalidAddress:
        return False
