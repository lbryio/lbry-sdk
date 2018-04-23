from lbrynet import __version__
LBRYUM_VERSION = __version__
PROTOCOL_VERSION = '0.10'   # protocol version requested
NEW_SEED_VERSION = 11       # lbryum versions >= 2.0
OLD_SEED_VERSION = 4        # lbryum versions < 2.0

# The hash of the mnemonic seed must begin with this
SEED_PREFIX = '01'  # Electrum standard wallet
SEED_PREFIX_2FA = '101'  # extended seed for two-factor authentication


MAXIMUM_FEE_PER_BYTE = 50
MAXIMUM_FEE_PER_NAME_CHAR = 200000
COINBASE_MATURITY = 100
CENT = 1000000
COIN = 100*CENT

# supported types of transaction outputs
TYPE_ADDRESS = 1
TYPE_PUBKEY = 2
TYPE_SCRIPT = 4
TYPE_CLAIM = 8
TYPE_SUPPORT = 16
TYPE_UPDATE = 32

# claim related constants
EXPIRATION_BLOCKS = 262974
RECOMMENDED_CLAIMTRIE_HASH_CONFIRMS = 1

NO_SIGNATURE = 'ff'

NULL_HASH = '0000000000000000000000000000000000000000000000000000000000000000'
HEADER_SIZE = 112
BLOCKS_PER_CHUNK = 96
CLAIM_ID_SIZE = 20

HEADERS_URL = "https://s3.amazonaws.com/lbry-blockchain-headers/blockchain_headers_latest"

DEFAULT_PORTS = {'t': '50001', 's': '50002', 'h': '8081', 'g': '8082'}
NODES_RETRY_INTERVAL = 60
SERVER_RETRY_INTERVAL = 10
MAX_BATCH_QUERY_SIZE = 500
proxy_modes = ['socks4', 'socks5', 'http']

# Chain Properties
# see: https://github.com/lbryio/lbrycrd/blob/master/src/chainparams.cpp
MAIN_CHAIN = 'main'
TESTNET_CHAIN = 'testnet'
REGTEST_CHAIN = 'regtest'
CHAINS = {
    MAIN_CHAIN: {
        'pubkey_address': 0,
        'script_address': 5,
        'pubkey_address_prefix': 85,
        'script_address_prefix': 122,
        'genesis_hash': '9c89283ba0f3227f6c03b70216b9f665f0118d5e0fa729cedf4fb34d6a34f463',
        'max_target': 0x0000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,
        'genesis_bits': 0x1f00ffff,
        'target_timespan': 150
    },
    TESTNET_CHAIN: {
        'pubkey_address': 0,
        'script_address': 5,
        'pubkey_address_prefix': 111,
        'script_address_prefix': 196,
        'genesis_hash': '9c89283ba0f3227f6c03b70216b9f665f0118d5e0fa729cedf4fb34d6a34f463',
        'max_target': 0x0000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,
        'genesis_bits': 0x1f00ffff,
        'target_timespan': 150
    },
    REGTEST_CHAIN: {
        'pubkey_address': 0,
        'script_address': 5,
        'pubkey_address_prefix': 111,
        'script_address_prefix': 196,
        'genesis_hash': '6e3fcf1299d4ec5d79c3a4c91d624a4acf9e2e173d95a1a0504f677669687556',
        'max_target': 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,
        'genesis_bits': 0x207fffff,
        'target_timespan': 1
    }
}
