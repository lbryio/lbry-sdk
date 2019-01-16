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


async def send_handshake(protocol_version: typing.Optional[int],
                         reflector_server: typing.Optional[str]):
    """
    Reflector Handshake
    
    Simple Text-Oriented Messaging Protocol
    to reliable determine if both the client
    and server are ready to begin transaction.
    
    returns StreamReader and StreamWriter respectively.
    """
    
    loop = asyncio.get_running_loop()
    nonblock = asyncio.new_event_loop().call_soon_threadsafe
    
    client_version = protocol_version if not None else REFLECTOR_V2
    if not isinstance(client_version, int):
        try:
            _version = urllib.parse.quote_from_bytes(client_version)
            nonblock(log.fatal, 'Got malformed bytes string: %s.' % _version)
        finally:
            client_version = 1
    
    url = reflector_server if not None else REFLECTOR_PROD_SERVER
    if not re.fullmatch(r"^[A-Za-z0-9._~()'!*:@,;+?-]*$", url):
        _url = urllib.parse.quote_plus(url)
        try:
            nonblock(log.fatal, 'Got malformed URI: %s.' % _url)
        finally:
            url = urllib.parse.urlencode(_url)
            
    reader, writer = await asyncio.open_connection(host=url)
    
    handshake = {'version': client_version}  # '7b2276657273696f6e223a20317d'
    payload = binascii.hexlify(json.dumps(handshake).encode()).decode()
    eof = await writer.write(payload)
    loop.run_until_complete(eof)
    await writer.write_eof()
    
    data = await reader.readline()
    response = await loop.create_future().set_result(json.loads(binascii.unhexlify(data)))
    loop.run_until_complete(response)
    handshake_received = response.result() # {'version': 1}

    try:
        while True:
            _temp = handshake_received['version']
            _ = isinstance(_temp, int)
            nonblock(log.info, '%s accepted connection.\nServer protocol version: %i.' % url, _temp)
            await writer.drain()
            return reader, writer
    except LookupError as exc:
        if isinstance(exc, KeyError):
            nonblock(log.error, '%s did not return the protocol version: %s' % url, exc)
        elif isinstance(exc, ValueError):
            nonblock(log.error, '%s did not respond accordingly: %s' % url, exc)
    except ConnectionError as exc:
        nonblock(log.error, '%s connection terminated abruptly: %s' % url, exc)
        

async def reflect_stream(descriptor: typing.Optional[StreamDescriptor],
                         blob_manager: typing.Optional[BlobFileManager],
                         reflector_server_url: typing.Optional[Url]) -> typing.List[str]:
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
