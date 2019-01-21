import typing

REFLECTOR_V0 = 0
REFLECTOR_V1 = REFLECTOR_V0 + 0
REFLECTOR_V2 = REFLECTOR_V1 + 1


class ReflectorVersion(typing.Any[REFLECTOR_V2, REFLECTOR_V1]):
    """
    ReflectorVersion type to pass around client server sessions.
    """


class Reflector(typing.Type['Reflector']):
    """
    Representation of Reflector session
    """
    version = typing.Any['ReflectorVersion']
    blobs_to_send = typing.List[typing.Dict]
    blobs_needed = typing.List[typing.AnyStr]
    handshake_received = typing.Any[True, False]
    blobs_sent = typing.Any[int]
