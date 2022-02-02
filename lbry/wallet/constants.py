NULL_HASH32 = b'\x00'*32

CENT = 1000000
COIN = 100*CENT
DUST = 1000

TIMEOUT = 30.0

TXO_TYPES = {
    "other": 0,
    "stream": 1,
    "channel": 2,
    "support": 3,
    "purchase": 4,
    "collection": 5,
    "repost": 6,
}

CLAIM_TYPE_NAMES = [
    'stream',
    'channel',
    'collection',
    'repost',
]

CLAIM_TYPES = [
    TXO_TYPES[name] for name in CLAIM_TYPE_NAMES
]
