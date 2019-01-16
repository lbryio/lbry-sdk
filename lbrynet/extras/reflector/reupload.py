import asyncio
import typing
import random
import json
import logging
import re

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


# TODO: verify if using binascii.hexlify() is supposed to be used instead.
async def send_handshake(
        protocol_version: typing.Optional[int],
        reflector_server_url: typing.Optional[str]):
    """
    Reflector Handshake
    
    Simple Text-Oriented Messaging Protocol
    to reliable determine if both the client
    and server are ready to begin transaction.
    
    returns StreamReader and StreamWriter respectively
    """
    
    loop = asyncio.get_running_loop()
    received_server_version = loop.get_task_factory()
    
    client_version = protocol_version if not None else REFLECTOR_V2
    if not isinstance(client_version, int):
        try:
            import urllib.parse
            _version = urllib.parse.quote_from_bytes(client_version)
            loop.call_soon_threadsafe(log.fatal, 'Got malformed bytes string: %s' % _version)
        finally:
            client_version = 1
    
    url = reflector_server_url if not None else REFLECTOR_PROD_SERVER
    if not re.fullmatch(r"^[A-Za-z0-9._~()'!*:@,;+?-]*$", url):
        import urllib.parse
        _url = urllib.parse.quote_plus(url)
        try:
            loop.call_soon_threadsafe(log.fatal, 'Got malformed URI: %s' % _url)
        finally:
            url = urllib.parse.urlencode(_url)
            
    reader, writer = await asyncio.open_connection(host=url)
    
    try:
        writer.write(json.dumps(
            f"{'server': {client_version!r},}".strip()).encode('utf-8') + b'\n')
        data = await reader.readline()
        _temp = json.loads(data.decode('utf-8'))['version']
        asyncio.run_coroutine_threadsafe(
            received_server_version().set_result(_temp), loop)
        loop.call_soon_threadsafe(log.info, '%s accepted connection.' % url)
    except KeyError:
        loop.call_soon_threadsafe(
            log.error, '%s did not return the protocol version.' % url)
        return asyncio.run_coroutine_threadsafe(
            received_server_version().cancel(), loop)
    except ValueError:
        loop.call_soon_threadsafe(
            log.error, '%s did not respond according to protocol specification.' % url)
        return asyncio.run_coroutine_threadsafe(
            received_server_version().cancel(), loop)
    except ConnectionError:
        loop.call_soon_threadsafe(
            log.error, '%s connection terminated abruptly.' % url)
        return asyncio.run_coroutine_threadsafe(
            received_server_version().cancel(), loop)
    finally:
        await writer.drain()
        if received_server_version().cancelled():
            return None
        loop.call_soon_threadsafe(
            log.info, 'Server protocol version: %i' % received_server_version.result)
        return reader, writer


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
