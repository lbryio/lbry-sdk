import typing

REFLECTOR_V0 = 0
REFLECTOR_V1 = REFLECTOR_V0 + 0
REFLECTOR_V2 = REFLECTOR_V1 + 1


class ReflectorVersion(typing.Any[REFLECTOR_V2, REFLECTOR_V1]):
    """
    ReflectorVersion type to pass around client server sessions.
    """


class StreamDescriptorBlob(typing.Type['StreamDescriptorBlob']):
    """
    StreamDescriptorBlob identifies the blobs in transit are from a stream descriptor.
    """
    sd_blob: typing.Type['sd_blob'] = typing.Dict
    sd_hash: typing.Type['sd_hash'] = typing.AnyStr


class FileBlob(typing.Type['EncryptedFileBlob']):
    blob_hash: typing.Type['blob_hash'] = typing.AnyStr
    blob_hash_size: typing.Type['blob_hash_size'] = int


class Reflector(typing.Type['Reflector']):
    version = typing.Any['ReflectorVersion']
    blobs_to_send = typing.List[typing.Dict]
    blobs_needed = typing.List[typing.AnyStr]
    handshake_received = typing.Any[True, False]
    blobs_sent = typing.Any[int]

