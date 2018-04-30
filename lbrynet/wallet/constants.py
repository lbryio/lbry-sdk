PROTOCOL_VERSION = '0.10'   # protocol version requested
NEW_SEED_VERSION = 11       # lbryum versions >= 2.0
OLD_SEED_VERSION = 4        # lbryum versions < 2.0

# The hash of the mnemonic seed must begin with this
SEED_PREFIX = '01'  # Electrum standard wallet
SEED_PREFIX_2FA = '101'  # extended seed for two-factor authentication


COINBASE_MATURITY = 100
CENT = 1000000
COIN = 100*CENT

RECOMMENDED_CLAIMTRIE_HASH_CONFIRMS = 1

NO_SIGNATURE = 'ff'

NULL_HASH = '0000000000000000000000000000000000000000000000000000000000000000'
CLAIM_ID_SIZE = 20

DEFAULT_PORTS = {'t': '50001', 's': '50002', 'h': '8081', 'g': '8082'}
NODES_RETRY_INTERVAL = 60
SERVER_RETRY_INTERVAL = 10
MAX_BATCH_QUERY_SIZE = 500
proxy_modes = ['socks4', 'socks5', 'http']
