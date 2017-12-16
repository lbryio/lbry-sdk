"""
Reflector is a protocol to re-host lbry blobs and streams
Client queries and server responses follow, all dicts are encoded as json

############# Handshake request and response #############
Upon connecting, the client sends a version handshake:
{
    'version': int,
}

The server replies with the same version
{
    'version': int,
}

############# Stream descriptor requests and responses #############
(if sending blobs directly this is skipped)
If the client is reflecting a whole stream, they send a stream descriptor request:
{
    'sd_blob_hash': str,
    'sd_blob_size': int
}

The server indicates if it's aware of this stream already by requesting (or not requesting)
the stream descriptor blob. If the server has a validated copy of the sd blob, it will
include the needed_blobs field (a list of blob hashes missing from reflector) in the response.
If the server does not have the sd blob the needed_blobs field will not be included, as the
server does not know what blobs it is missing - so the client should send all of the blobs
in the stream.
{
    'send_sd_blob': bool
    'needed_blobs': list, conditional
}

The client may begin the file transfer of the sd blob if send_sd_blob was True.
If the client sends the blob, after receiving it the server indicates if the
transfer was successful:
{
    'received_sd_blob': bool
}
If the transfer was not successful (False), the blob is added to the needed_blobs queue

############# Blob requests and responses #############
A client with blobs to reflect (either populated by the client or by the stream descriptor
response) queries if the server is ready to begin transferring a blob
{
    'blob_hash': str,
    'blob_size': int
}

The server replies, send_blob will be False if the server has a validated copy of the blob:
{
    'send_blob': bool
}

The client may begin the raw blob file transfer if the server replied True.
If the client sends the blob, the server replies:
{
    'received_blob': bool
}
If the transfer was not successful (False), the blob is re-added to the needed_blobs queue

Blob requests continue for each of the blobs the client has queued to send, when completed
the client disconnects.
"""

from lbrynet.reflector.server.server import ReflectorServerFactory as ServerFactory
from lbrynet.reflector.client.client import EncryptedFileReflectorClientFactory as ClientFactory
from lbrynet.reflector.client.blob import BlobReflectorClientFactory as BlobClientFactory
