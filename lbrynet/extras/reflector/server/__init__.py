from lbrynet.blob.blob_file import is_valid_blobhash
from lbrynet.p2p.Error import InvalidBlobHashError

BLOB_SIZE = 'blob_size'
BLOB_HASH = 'blob_hash'
SD_BLOB_SIZE = 'sd_blob_size'
SD_BLOB_HASH = 'sd_blob_hash'


def is_descriptor_request(message):
    if SD_BLOB_HASH not in message or SD_BLOB_SIZE not in message:
        return False
    if not is_valid_blobhash(message[SD_BLOB_HASH]):
        return InvalidBlobHashError(message[SD_BLOB_HASH])
    return True


def is_blob_request(message):
    if BLOB_HASH not in message or BLOB_SIZE not in message:
        return False
    if not is_valid_blobhash(message[BLOB_HASH]):
        return InvalidBlobHashError(message[BLOB_HASH])
    return True
