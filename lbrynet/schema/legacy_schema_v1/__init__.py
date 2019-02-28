V_0_0_1 = "_0_0_1"
V_0_0_2 = "_0_0_2"
V_0_0_3 = "_0_0_3"
V_0_1_0 = "_0_1_0"


VERSION_MAP = {
    V_0_0_1: 1,
    V_0_0_2: 2,
    V_0_0_3: 3,
    V_0_1_0: 4,
}

VERSION_NAMES = {
    1: V_0_0_1,
    2: V_0_0_2,
    3: V_0_0_3,
    4: V_0_1_0
}

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

VERSION = "version"
STREAM_TYPE = "streamType"
CERTIFICATE_TYPE = "certificateType"
CLAIM_TYPE = "claimType"
SIGNATURE = "publisherSignature"

CLAIM_TYPES = {
    STREAM_TYPE: "stream",
    CERTIFICATE_TYPE: "certificate"
}

CLAIM_TYPE_NAMES = {
    1: "stream",
    2: "certificate"
}

LBRY_SD_HASH = "lbry_sd_hash"
LBRY_SD_HASH_LENGTH = 48

SOURCE_TYPES = {
    LBRY_SD_HASH: 1
}

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
