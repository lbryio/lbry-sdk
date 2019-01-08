import hashlib
import os

hash_class = hashlib.sha384
hash_length = hash_class().digest_size
hash_bits = hash_length * 8
alpha = 5
k = 8
replacement_cache_size = 8
rpc_timeout = 5
rpc_attempts = 5
rpc_attempts_pruning_window = 600
iterative_lookup_delay = rpc_timeout / 2
refresh_interval = 3600  # 1 hour
replicate_interval = refresh_interval
data_expiration = 86400  # 24 hours
token_secret_refresh_interval = 300  # 5 minutes
check_refresh_interval = refresh_interval / 5
max_datagram_size = 8192  # 8 KB
rpc_id_length = 20
protocol_version = 1
bottom_out_limit = 3
msg_size_limit = max_datagram_size - 26


def digest(data: bytes) -> bytes:
    h = hash_class()
    h.update(data)
    return h.digest()


def generate_id(num=None) -> bytes:
    if num is not None:
        return digest(str(num).encode())
    else:
        return digest(os.urandom(32))


def generate_rpc_id(num=None) -> bytes:
    return generate_id(num)[:rpc_id_length]
