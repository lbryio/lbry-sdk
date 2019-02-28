LBC = "LBC"
BTC = "BTC"
USD = "USD"

CURRENCY_MAP = {
    LBC: 1,
    BTC: 2,
    USD: 3
}

CURRENCY_NAMES = {
    1: LBC,
    2: BTC,
    3: USD
}

ADDRESS_LENGTH = 25
ADDRESS_CHECKSUM_LENGTH = 4
NIST256p = "NIST256p"
NIST384p = "NIST384p"
SECP256k1 = "SECP256k1"

ECDSA_CURVES = {
    NIST256p: 1,
    NIST384p: 2,
    SECP256k1: 3
}

CURVE_NAMES = {
    1: NIST256p,
    2: NIST384p,
    3: SECP256k1
}

SHA256 = "sha256"
SHA384 = "sha384"


B58_CHARS = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
assert len(B58_CHARS) == 58

PUBKEY_ADDRESS = 0
SCRIPT_ADDRESS = 5

ADDRESS_PREFIXES = {
    "lbrycrd_main": {
        PUBKEY_ADDRESS: 85,
        SCRIPT_ADDRESS: 122
    },
    "lbrycrd_regtest": {
        PUBKEY_ADDRESS: 111,
        SCRIPT_ADDRESS: 196
    },
    "lbrycrd_testnet": {
        PUBKEY_ADDRESS: 111,
        SCRIPT_ADDRESS: 196
    },
}
