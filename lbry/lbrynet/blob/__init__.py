from lbrynet.cryptoutils import get_lbry_hash_obj

MAX_BLOB_SIZE = 2 * 2 ** 20

# digest_size is in bytes, and blob hashes are hex encoded
blobhash_length = get_lbry_hash_obj().digest_size * 2
