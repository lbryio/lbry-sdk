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


def version_is_greater_than(version1, version2):
    """
    handles differing numbers of subversions, ie 0.3.10 > 0.3.9.9
    """

    v1, v2 = version1.split("."), version2.split(".")
    r = True
    if len(v2) > len(v1):
        for j in range(len(v2) - len(v1)):
            v1.append("0")
    elif len(v2) < len(v1):
        for j in range(len(v1) - len(v2)):
            v2.append("0")
    for c in range(len(v1)):
        if int(v2[c]) > int(v1[c]):
            r = False
            break
        elif c == len(v1) - 1 and int(v1[c]) == int(v2[c]):
            r = False
    return r