NULL_HASH32 = b'\x00'*32

CENT = 1000000
COIN = 100*CENT

TIMEOUT = 30.0

TXO_TYPES = {
    "stream": 1,
    "channel": 2,
    "support": 3,
    "purchase": 4,
    "collection": 5,
    "repost": 6,
}

CLAIM_TYPES = [
    TXO_TYPES['stream'],
    TXO_TYPES['channel'],
    TXO_TYPES['collection'],
    TXO_TYPES['repost'],
]
