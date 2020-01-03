from lbry.utils import get_lbry_hash_obj

MAX_BLOB_SIZE = 2 * 2 ** 20

# digest_size is in bytes, and blob hashes are hex encoded
BLOBHASH_LENGTH = get_lbry_hash_obj().digest_size * 2
