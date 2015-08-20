from lbrynet.core.cryptoutils import get_lbry_hash_obj
import random


blobhash_length = get_lbry_hash_obj().digest_size * 2  # digest_size is in bytes, and blob hashes are hex encoded


def generate_id(num=None):
    h = get_lbry_hash_obj()
    if num is not None:
        h.update(str(num))
    else:
        h.update(str(random.getrandbits(512)))
    return h.digest()


def is_valid_blobhash(blobhash):
    """
    @param blobhash: string, the blobhash to check

    @return: Whether the blobhash is the correct length and contains only valid characters (0-9, a-f)
    """
    if len(blobhash) != blobhash_length:
        return False
    for l in blobhash:
        if l not in "0123456789abcdef":
            return False
    return True