import hashlib
from cryptography.hazmat.backends import default_backend


backend = default_backend()


def get_lbry_hash_obj():
    return hashlib.sha384()
