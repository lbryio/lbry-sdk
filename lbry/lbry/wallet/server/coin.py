import struct

from lbry.wallet.script import OutputScript
from torba.server.script import ScriptPubKey, OpCodes
from torba.server.util import cachedproperty
from torba.server.hash import hash_to_hex_str, HASHX_LEN
from hashlib import sha256
from torba.server.coins import Coin, CoinError


class LBC(Coin):
    from .session import LBRYElectrumX
    from .block_processor import LBRYBlockProcessor
    from .daemon import LBCDaemon
    from .db import LBRYDB
    DAEMON = LBCDaemon
    SESSIONCLS = LBRYElectrumX
    BLOCK_PROCESSOR = LBRYBlockProcessor
    DB = LBRYDB
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
            raise CoinError('genesis block has hash {} expected {}'
                            .format(header_hex_hash, cls.GENESIS_HASH))

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
        '''Given a pk_script, return the adddress it pays to, or None.'''
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
        if script and script[0] == OpCodes.OP_RETURN:
            return None
        if script[0] in [
            OutputScript.OP_CLAIM_NAME,
            OutputScript.OP_UPDATE_CLAIM,
            OutputScript.OP_SUPPORT_CLAIM,
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
