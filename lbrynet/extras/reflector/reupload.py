import asyncio
import binascii
import typing
import random
import json
import logging
import re
import urllib.parse
import urllib.request

from lbrynet import conf

if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.stream.descriptor import StreamDescriptor
    

log = logging.getLogger(__name__)

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


async def handle_handshake(version: int, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    handshake = {'version': version}  # '7b2276657273696f6e223a20317d'
    payload = binascii.hexlify(json.dumps(handshake).encode()).decode()
    await writer.write(payload)
    await writer.write_eof()
    data = await reader.readline()
    response = await json.loads(binascii.unhexlify(data))
    return await response.result()  # {'version': 1}


async def prepare_handshake(version: int, server: str):
    if not isinstance(version, int):
        _ = urllib.parse.quote_from_bytes(version)
        asyncio.run(log.fatal('Got malformed bytes: %s.' % _))
        setattr(version, 'value', REFLECTOR_V2)
    elif server not in enumerate([REFLECTOR_V1, REFLECTOR_V2]):
        setattr(server, 'value', REFLECTOR_PROD_SERVER)
    elif not re.fullmatch(r"^[A-Za-z0-9._~()'!*:@,;+?-]*$", server):
        url = urllib.parse.quote_plus(server)
        asyncio.run(log.fatal('Got malformed URI: %s.' % url))
        setattr(server, 'value', urllib.parse.urlencode(url))
    return version, server


async def send_handshake(protocol_version: typing.Optional[int],
                         reflector_server: typing.Optional[str]):
    """
    Reflector Handshake
    
    Simple Text-Oriented Messaging Protocol
    to reliable determine if both the client
    and server are ready to begin transaction.
    
    returns StreamReader and StreamWriter respectively.
    """

    version, server = await prepare_handshake(protocol_version, reflector_server)
    reader, writer = await asyncio.open_connection(host=server)
    handshake_received = await handle_handshake(version, reader, writer)

    try:
        while True:
            _ = handshake_received['version']
            if not _:
                raise False
            if not isinstance(_[0], int):
                return False
            # log.info('%s accepted connection.\nServer protocol version: %s.' % server, _)
            await writer.drain()
            return reader, writer
    except LookupError as exc:
        if isinstance(exc, KeyError):
            # log.error('%s did not return the protocol version: %s' % server, exc)
            ...
        elif isinstance(exc, ValueError):
            # log.error('%s did not respond accordingly: %s' % server, exc)
            ...
    except ConnectionError as exc:
        # log.error('%s connection terminated abruptly: %s' % server, exc)
        ...


async def reflect_stream(descriptor: typing.Optional[StreamDescriptor],
                         blob_manager: typing.Optional[BlobFileManager],
                         reflector_server_url: typing.Optional[str]) -> typing.List[str]:
    loop = asyncio.get_event_loop()
    handshake = asyncio.run_coroutine_threadsafe(
        send_handshake(REFLECTOR_V2, REFLECTOR_PROD_SERVER), loop)
    async with handshake.running():
        # TODO: prepare all context variables.
        _loop = asyncio.new_event_loop()
    return []

"""
Initiative lbry#1776:

. Integrate Reflector with upstream/asyncio-protocols-refactor
. lbrynet.extras.daemon[file_reflect] depends on reflector
. production instance depends on reflector for reflecting new publishes.

Epic reflect stream:
    define ReflectorClientProtocol(asyncio.Protocol)

Story connection_made:
    establish connection to the reflector url

Story data_received:
    attempt to transfer the blobs

Story connection_lost:
    disconnect(no exc)

Story wait_reflect:
    return a result indicating what was sent.

"""

# hotfix for lbry#1776
# TODO: Handshake with server
# TODO: ReflectorClient choreography
# TODO: Non-blocking log
# TODO: return ok | error to daemon
# TODO: Unit test to verify blob handling is solid
# TODO: mitmproxy transaction for potential constraints to watch for
# TODO: Unit test rewrite for lbrynet.extras.daemon.file_reflect use case
# TODO: squash previous commits
# TODO: note __doc__ outdated
