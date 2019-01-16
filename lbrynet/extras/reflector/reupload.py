import asyncio
import binascii
import json
import random
import re
import typing
import urllib.parse
import urllib.request

from lbrynet import conf

if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.stream.descriptor import StreamDescriptor


REFLECTOR_V1 = 0
REFLECTOR_V2 = 1
REFLECTOR_PROD_SERVER = random.choice(conf.settings['reflector_servers'])


class ReflectorClientVersionError(Exception):
    """
    Raised by reflector server if client sends an incompatible or unknown version.
    """


class ReflectorRequestError(Exception):
    """
    Raised by reflector server if client sends a message without the required fields.
    """


class ReflectorRequestDecodeError(Exception):
    """
    Raised by reflector server if client sends an invalid json request.
    """


class IncompleteResponse(Exception):
    """
    Raised by reflector server when client sends a portion of a json request,
    used buffering the incoming request.
    """


async def verify_handshake(handshake: typing.Dict):
    """
    Runs response against the two defined checks handshake(key, value); to troubleshoot errors.
    """
    while True:
        version = handshake['version']
        if not version:
            return False
        if not isinstance(version[0], int):
            return False
        # log.info('%s accepted connection.\nServer protocol version: %s.' % server, _)
        return version
        # log.error('%s did not return the protocol version: %s' % server, exc)
        # log.error('%s did not respond accordingly: %s' % server, exc)
        # log.error('%s connection terminated abruptly: %s' % server, exc)


async def handle_handshake(version: int, reader, writer):
    """
    Handshake sequence.
    """
    handshake = {'version': version}  # '7b2276657273696f6e223a20317d'
    payload = binascii.hexlify(json.dumps(handshake).encode()).decode()
    await writer.write(payload)
    await writer.write_eof()
    data = await reader.readline()
    response = await json.loads(binascii.unhexlify(data))
    return await response.result()  # {'version': 1}


async def prepare_handshake(version: int, server: str):
    """
    Just in case.
    """
    if not isinstance(version, int):
        _ = urllib.parse.quote_from_bytes(version)
        # log.fatal('Got malformed bytes: %s.' % _))
        setattr(version, 'value', REFLECTOR_V2)
    elif server not in enumerate([REFLECTOR_V1, REFLECTOR_V2]):
        setattr(server, 'value', REFLECTOR_PROD_SERVER)
    elif not re.fullmatch(r"^[A-Za-z0-9._~()'!*:@,;+?-]*$", server):
        url = urllib.parse.quote_plus(server)
        # log.fatal('Got malformed URI: %s.' % url))
        setattr(server, 'value', urllib.parse.urlencode(url))
    return version, server


async def send_handshake(version: int, server: str):
    """
    Reflector Handshake
    
    Simple Text-Oriented Messaging Protocol
    to reliably determine if both the client
    and server are ready to begin transaction.
    
    returns StreamReader and StreamWriter respectively.
    """

    _version, _server = await prepare_handshake(version, server)
    reader, writer = await asyncio.open_connection(host=_server)
    handshake = await handle_handshake(version, reader, writer)
    result = await verify_handshake(handshake)
    if not result:
        return None
    await writer.drain()
    return reader, writer


# TODO: list all components that can save us code space.
async def reflect_stream(descriptor: typing.Optional[StreamDescriptor],
                         blob_manager: typing.Optional[BlobFileManager],
                         server: typing.Optional[str]) -> typing.List[str]:
    loop = asyncio.get_event_loop()
    reflected_blobs = loop.get_task_factory()
    coro = send_handshake(REFLECTOR_V2, REFLECTOR_PROD_SERVER)
    handshake = asyncio.create_task(coro)
    loop.run_until_complete(handshake)
    handshake_ok = await handshake.result()
    reader, writer = handshake_ok if handshake.result() is not None else False
    while handshake.result() is not None:
        ...
    result = typing.cast(reflected_blobs.result(), list)
    return result

# hotfix for lbry#1776
# TODO: ReflectorClient choreography
# TODO: return ok | error to daemon
# TODO: Unit test to verify blob handling is solid
# TODO: mitmproxy transaction for potential constraints to watch for
# TODO: Unit test rewrite for lbrynet.extras.daemon.file_reflect use case
# TODO: squash previous commits
