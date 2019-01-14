import asyncio


class ReflectorClientVersionError(Exception):
    """
    Raised by reflector server if client sends an incompatible or unknown version
    """


class ReflectorRequestError(Exception):
    """
    Raised by reflector server if client sends a message without the required fields
    """


class ReflectorRequestDecodeError(Exception):
    """
    Raised by reflector server if client sends an invalid json request
    """


class IncompleteResponse(Exception):
    """
    Raised by reflector server when client sends a portion of a json request,
    used buffering the incoming request
    """

# TODO: event-driven consumer


MAXIMUM_QUERY_SIZE = 200
SEND_SD_BLOB = 'send_sd_blob'
SEND_BLOB = 'send_blob'
RECEIVED_SD_BLOB = 'received_sd_blob'
RECEIVED_BLOB = 'received_blob'
NEEDED_BLOBS = 'needed_blobs'
VERSION = 'version'
BLOB_SIZE = 'blob_size'
BLOB_HASH = 'blob_hash'
SD_BLOB_SIZE = 'sd_blob_size'
SD_BLOB_HASH = 'sd_blob_hash'


class Server(asyncio.AbstractServer):
    ...

