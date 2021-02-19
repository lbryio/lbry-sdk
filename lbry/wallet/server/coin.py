import re
import struct
from typing import List
from hashlib import sha256
from decimal import Decimal
from collections import namedtuple

import lbry.wallet.server.tx as lib_tx
from lbry.wallet.script import OutputScript, OP_CLAIM_NAME, OP_UPDATE_CLAIM, OP_SUPPORT_CLAIM
from lbry.wallet.server.tx import DeserializerSegWit
from lbry.wallet.server.util import cachedproperty, subclasses
from lbry.wallet.server.hash import Base58, hash160, double_sha256, hash_to_hex_str, HASHX_LEN
from lbry.wallet.server.daemon import Daemon, LBCDaemon
from lbry.wallet.server.script import ScriptPubKey, OpCodes
from lbry.wallet.server.leveldb import LevelDB
from lbry.wallet.server.session import LBRYElectrumX, LBRYSessionManager
# from lbry.wallet.server.db.writer import LBRYLevelDB
from lbry.wallet.server.block_processor import LBRYBlockProcessor


Block = namedtuple("Block", "raw header transactions")
OP_RETURN = OpCodes.OP_RETURN


class CoinError(Exception):
    """Exception raised for coin-related errors."""


class Coin:
    """Base class of coin hierarchy."""

    REORG_LIMIT = 200
    # Not sure if these are coin-specific
    RPC_URL_REGEX = re.compile('.+@(\\[[0-9a-fA-F:]+\\]|[^:]+)(:[0-9]+)?')
    VALUE_PER_COIN = 100000000
    CHUNK_SIZE = 2016
    BASIC_HEADER_SIZE = 80
    STATIC_BLOCK_HEADERS = True
    SESSIONCLS = LBRYElectrumX
    DESERIALIZER = lib_tx.Deserializer
    DAEMON = Daemon
    BLOCK_PROCESSOR = LBRYBlockProcessor
    SESSION_MANAGER = LBRYSessionManager
    DB = LevelDB
    HEADER_VALUES = [
        'version', 'prev_block_hash', 'merkle_root', 'timestamp', 'bits', 'nonce'
    ]
    HEADER_UNPACK = struct.Struct('< I 32s 32s I I I').unpack_from
    MEMPOOL_HISTOGRAM_REFRESH_SECS = 500
    XPUB_VERBYTES = bytes('????', 'utf-8')
    XPRV_VERBYTES = bytes('????', 'utf-8')
    ENCODE_CHECK = Base58.encode_check
    DECODE_CHECK = Base58.decode_check
    # Peer discovery
    PEER_DEFAULT_PORTS = {'t': '50001', 's': '50002'}
    PEERS: List[str] = []

    @classmethod
    def lookup_coin_class(cls, name, net):
        """Return a coin class given name and network.

        Raise an exception if unrecognised."""
        req_attrs = ['TX_COUNT', 'TX_COUNT_HEIGHT', 'TX_PER_BLOCK']
        for coin in subclasses(Coin):
            if (coin.NAME.lower() == name.lower() and
                    coin.NET.lower() == net.lower()):
                coin_req_attrs = req_attrs.copy()
                missing = [attr for attr in coin_req_attrs
                           if not hasattr(coin, attr)]
                if missing:
                    raise CoinError(f'coin {name} missing {missing} attributes')
                return coin
        raise CoinError(f'unknown coin {name} and network {net} combination')

    @classmethod
    def sanitize_url(cls, url):
        # Remove surrounding ws and trailing /s
        url = url.strip().rstrip('/')
        match = cls.RPC_URL_REGEX.match(url)
        if not match:
            raise CoinError(f'invalid daemon URL: "{url}"')
        if match.groups()[1] is None:
            url += f':{cls.RPC_PORT:d}'
        if not url.startswith('http://') and not url.startswith('https://'):
            url = 'http://' + url
        return url + '/'

    @classmethod
    def genesis_block(cls, block):
        """Check the Genesis block is the right one for this coin.

        Return the block less its unspendable coinbase.
        """
        header = cls.block_header(block, 0)
        header_hex_hash = hash_to_hex_str(cls.header_hash(header))
        if header_hex_hash != cls.GENESIS_HASH:
            raise CoinError(f'genesis block has hash {header_hex_hash} expected {cls.GENESIS_HASH}')

        return header + bytes(1)

    @classmethod
    def hashX_from_script(cls, script):
        """Returns a hashX from a script, or None if the script is provably
        unspendable so the output can be dropped.
        """
        if script and script[0] == OP_RETURN:
            return None
        return sha256(script).digest()[:HASHX_LEN]

    @staticmethod
    def lookup_xverbytes(verbytes):
        """Return a (is_xpub, coin_class) pair given xpub/xprv verbytes."""
        # Order means BTC testnet will override NMC testnet
        for coin in subclasses(Coin):
            if verbytes == coin.XPUB_VERBYTES:
                return True, coin
            if verbytes == coin.XPRV_VERBYTES:
                return False, coin
        raise CoinError('version bytes unrecognised')

    @classmethod
    def address_to_hashX(cls, address):
        """Return a hashX given a coin address."""
        return cls.hashX_from_script(cls.pay_to_address_script(address))

    @classmethod
    def P2PKH_address_from_hash160(cls, hash160):
        """Return a P2PKH address given a public key."""
        assert len(hash160) == 20
        return cls.ENCODE_CHECK(cls.P2PKH_VERBYTE + hash160)

    @classmethod
    def P2PKH_address_from_pubkey(cls, pubkey):
        """Return a coin address given a public key."""
        return cls.P2PKH_address_from_hash160(hash160(pubkey))

    @classmethod
    def P2SH_address_from_hash160(cls, hash160):
        """Return a coin address given a hash160."""
        assert len(hash160) == 20
        return cls.ENCODE_CHECK(cls.P2SH_VERBYTES[0] + hash160)

    @classmethod
    def hash160_to_P2PKH_script(cls, hash160):
        return ScriptPubKey.P2PKH_script(hash160)

    @classmethod
    def hash160_to_P2PKH_hashX(cls, hash160):
        return cls.hashX_from_script(cls.hash160_to_P2PKH_script(hash160))

    @classmethod
    def pay_to_address_script(cls, address):
        """Return a pubkey script that pays to a pubkey hash.

        Pass the address (either P2PKH or P2SH) in base58 form.
        """
        raw = cls.DECODE_CHECK(address)

        # Require version byte(s) plus hash160.
        verbyte = -1
        verlen = len(raw) - 20
        if verlen > 0:
            verbyte, hash160 = raw[:verlen], raw[verlen:]

        if verbyte == cls.P2PKH_VERBYTE:
            return cls.hash160_to_P2PKH_script(hash160)
        if verbyte in cls.P2SH_VERBYTES:
            return ScriptPubKey.P2SH_script(hash160)

        raise CoinError(f'invalid address: {address}')

    @classmethod
    def privkey_WIF(cls, privkey_bytes, compressed):
        """Return the private key encoded in Wallet Import Format."""
        payload = bytearray(cls.WIF_BYTE) + privkey_bytes
        if compressed:
            payload.append(0x01)
        return cls.ENCODE_CHECK(payload)

    @classmethod
    def header_hash(cls, header):
        """Given a header return hash"""
        return double_sha256(header)

    @classmethod
    def header_prevhash(cls, header):
        """Given a header return previous hash"""
        return header[4:36]

    @classmethod
    def static_header_offset(cls, height):
        """Given a header height return its offset in the headers file.

        If header sizes change at some point, this is the only code
        that needs updating."""
        assert cls.STATIC_BLOCK_HEADERS
        return height * cls.BASIC_HEADER_SIZE

    @classmethod
    def static_header_len(cls, height):
        """Given a header height return its length."""
        return (cls.static_header_offset(height + 1)
                - cls.static_header_offset(height))

    @classmethod
    def block_header(cls, block, height):
        """Returns the block header given a block and its height."""
        return block[:cls.static_header_len(height)]

    @classmethod
    def block(cls, raw_block, height):
        """Return a Block namedtuple given a raw block and its height."""
        header = cls.block_header(raw_block, height)
        txs = cls.DESERIALIZER(raw_block, start=len(header)).read_tx_block()
        return Block(raw_block, header, txs)

    @classmethod
    def decimal_value(cls, value):
        """Return the number of standard coin units as a Decimal given a
        quantity of smallest units.

        For example 1 BTC is returned for 100 million satoshis.
        """
        return Decimal(value) / cls.VALUE_PER_COIN

    @classmethod
    def electrum_header(cls, header, height):
        h = dict(zip(cls.HEADER_VALUES, cls.HEADER_UNPACK(header)))
        # Add the height that is not present in the header itself
        h['block_height'] = height
        # Convert bytes to str
        h['prev_block_hash'] = hash_to_hex_str(h['prev_block_hash'])
        h['merkle_root'] = hash_to_hex_str(h['merkle_root'])
        return h


class LBC(Coin):
    DAEMON = LBCDaemon
    SESSIONCLS = LBRYElectrumX
    BLOCK_PROCESSOR = LBRYBlockProcessor
    SESSION_MANAGER = LBRYSessionManager
    DESERIALIZER = DeserializerSegWit
    DB = LevelDB
    NAME = "LBRY"
    SHORTNAME = "LBC"
    NET = "mainnet"
    BASIC_HEADER_SIZE = 112
    CHUNK_SIZE = 96
    XPUB_VERBYTES = bytes.fromhex("0488b21e")
    XPRV_VERBYTES = bytes.fromhex("0488ade4")
    P2PKH_VERBYTE = bytes.fromhex("55")
    P2SH_VERBYTES = bytes.fromhex("7A")
    WIF_BYTE = bytes.fromhex("1C")
    GENESIS_HASH = ('9c89283ba0f3227f6c03b70216b9f665'
                    'f0118d5e0fa729cedf4fb34d6a34f463')
    TX_COUNT = 2716936
    TX_COUNT_HEIGHT = 329554
    TX_PER_BLOCK = 1
    RPC_PORT = 9245
    REORG_LIMIT = 200
    PEERS = [
    ]

    @classmethod
    def genesis_block(cls, block):
        '''Check the Genesis block is the right one for this coin.

        Return the block less its unspendable coinbase.
        '''
        header = cls.block_header(block, 0)
        header_hex_hash = hash_to_hex_str(cls.header_hash(header))
        if header_hex_hash != cls.GENESIS_HASH:
            raise CoinError(f'genesis block has hash {header_hex_hash} expected {cls.GENESIS_HASH}')

        return block

    @classmethod
    def electrum_header(cls, header, height):
        version, = struct.unpack('<I', header[:4])
        timestamp, bits, nonce = struct.unpack('<III', header[100:112])
        return {
            'version': version,
            'prev_block_hash': hash_to_hex_str(header[4:36]),
            'merkle_root': hash_to_hex_str(header[36:68]),
            'claim_trie_root': hash_to_hex_str(header[68:100]),
            'timestamp': timestamp,
            'bits': bits,
            'nonce': nonce,
            'block_height': height,
            }

    @cachedproperty
    def address_handlers(self):
        return ScriptPubKey.PayToHandlers(
            address=self.P2PKH_address_from_hash160,
            script_hash=self.P2SH_address_from_hash160,
            pubkey=self.P2PKH_address_from_pubkey,
            unspendable=lambda: None,
            strange=self.claim_address_handler,
        )

    @classmethod
    def address_from_script(cls, script):
        '''Given a pk_script, return the address it pays to, or None.'''
        return ScriptPubKey.pay_to(cls.address_handlers, script)

    @classmethod
    def claim_address_handler(cls, script):
        '''Parse a claim script, returns the address
        '''
        output = OutputScript(script)
        if output.is_pay_pubkey_hash:
            return cls.P2PKH_address_from_hash160(output.values['pubkey_hash'])
        if output.is_pay_script_hash:
            return cls.P2SH_address_from_hash160(output.values['script_hash'])
        if output.is_pay_pubkey:
            return cls.P2PKH_address_from_pubkey(output.values['pubkey'])
        if output.is_return_data:
            return None
        return None

    @classmethod
    def hashX_from_script(cls, script):
        '''
        Overrides electrumx hashX from script by extracting addresses from claim scripts.
        '''
        if script and script[0] == OpCodes.OP_RETURN or not script:
            return None
        if script[0] in [
            OP_CLAIM_NAME,
            OP_UPDATE_CLAIM,
            OP_SUPPORT_CLAIM,
        ]:
            return cls.address_to_hashX(cls.claim_address_handler(script))
        else:
            return sha256(script).digest()[:HASHX_LEN]


class LBCRegTest(LBC):
    NET = "regtest"
    GENESIS_HASH = '6e3fcf1299d4ec5d79c3a4c91d624a4acf9e2e173d95a1a0504f677669687556'
    XPUB_VERBYTES = bytes.fromhex('043587cf')
    XPRV_VERBYTES = bytes.fromhex('04358394')
    P2PKH_VERBYTE = bytes.fromhex("6f")
    P2SH_VERBYTES = bytes.fromhex("c4")


class LBCTestNet(LBCRegTest):
    NET = "testnet"
    GENESIS_HASH = '9c89283ba0f3227f6c03b70216b9f665f0118d5e0fa729cedf4fb34d6a34f463'
