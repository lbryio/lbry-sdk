import struct

from torba.server.script import ScriptPubKey, _match_ops, OpCodes
from torba.server.util import cachedproperty
from torba.server.hash import hash_to_hex_str, HASHX_LEN
from hashlib import sha256
from torba.server.coins import Coin, CoinError

from lbrynet.extras.wallet.server.opcodes import decode_claim_script, opcodes as lbry_opcodes


class LBC(Coin):
    from .session import LBRYElectrumX
    from .block_processor import LBRYBlockProcessor
    from .tx import LBRYDeserializer
    from .daemon import LBCDaemon
    from .db import LBRYDB
    DAEMON = LBCDaemon
    SESSIONCLS = LBRYElectrumX
    BLOCK_PROCESSOR = LBRYBlockProcessor
    DB = LBRYDB
    DESERIALIZER = LBRYDeserializer
    NAME = "LBRY"
    SHORTNAME = "LBC"
    NET = "mainnet"
    BASIC_HEADER_SIZE = 112
    CHUNK_SIZE = 96
    XPUB_VERBYTES = bytes.fromhex("019C354f")
    XPRV_VERBYTES = bytes.fromhex("019C3118")
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
        decoded = decode_claim_script(script)
        if not decoded:
            return None
        ops = []
        for op, data, _ in decoded[1]:
            if not data:
                ops.append(op)
            else:
                ops.append((op, data,))
        match = _match_ops
        TO_ADDRESS_OPS = [OpCodes.OP_DUP, OpCodes.OP_HASH160, -1,
                          OpCodes.OP_EQUALVERIFY, OpCodes.OP_CHECKSIG]
        TO_P2SH_OPS = [OpCodes.OP_HASH160, -1, OpCodes.OP_EQUAL]
        TO_PUBKEY_OPS = [-1, OpCodes.OP_CHECKSIG]

        if match(ops, TO_ADDRESS_OPS):
            return cls.P2PKH_address_from_hash160(ops[2][-1])
        if match(ops, TO_P2SH_OPS):
            return cls.P2SH_address_from_hash160(ops[1][-1])
        if match(ops, TO_PUBKEY_OPS):
            return cls.P2PKH_address_from_pubkey(ops[0][-1])
        if ops and ops[0] == OpCodes.OP_RETURN:
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
            lbry_opcodes.OP_CLAIM_NAME,
            lbry_opcodes.OP_SUPPORT_CLAIM,
            lbry_opcodes.OP_UPDATE_CLAIM
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
