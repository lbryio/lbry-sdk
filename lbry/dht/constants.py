import hashlib
import os

HASH_CLASS = hashlib.sha384  # pylint: disable=invalid-name
HASH_LENGTH = HASH_CLASS().digest_size
HASH_BITS = HASH_LENGTH * 8
ALPHA = 5
K = 8
SPLIT_BUCKETS_UNDER_INDEX = 1
REPLACEMENT_CACHE_SIZE = 8
RPC_TIMEOUT = 5.0
RPC_ATTEMPTS = 5
RPC_ATTEMPTS_PRUNING_WINDOW = 600
ITERATIVE_LOOKUP_DELAY = RPC_TIMEOUT / 2.0  # TODO: use config val / 2 if rpc timeout is provided
REFRESH_INTERVAL = 3600  # 1 hour
REPLICATE_INTERVAL = REFRESH_INTERVAL
DATA_EXPIRATION = 86400  # 24 hours
TOKEN_SECRET_REFRESH_INTERVAL = 300  # 5 minutes
MAYBE_PING_DELAY = 300  # 5 minutes
CHECK_REFRESH_INTERVAL = REFRESH_INTERVAL / 5
RPC_ID_LENGTH = 20
PROTOCOL_VERSION = 1
MSG_SIZE_LIMIT = 1400


def digest(data: bytes) -> bytes:
    h = HASH_CLASS()
    h.update(data)
    return h.digest()


def generate_id(num=None) -> bytes:
    if num is not None:
        return digest(str(num).encode())
    else:
        return digest(os.urandom(32))


def generate_rpc_id(num=None) -> bytes:
    return generate_id(num)[:RPC_ID_LENGTH]
