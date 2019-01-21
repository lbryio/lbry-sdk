import asyncio
import typing
import random

from lbrynet import conf
from lbrynet.extras.reflector.client import ReflectorClient
from lbrynet.extras.reflector.client import ReflectorClientVersionError
from lbrynet.extras.reflector.client import ReflectorRequestError
from lbrynet.extras.reflector.client import ReflectorRequestDecodeError
from lbrynet.extras.reflector.client import IncompleteResponse
from lbrynet.extras.reflector.client import REFLECTOR_V2

if typing.TYPE_CHECKING:
    from lbrynet.stream.descriptor import StreamDescriptor
    from lbrynet.blob.blob_file import BlobFile
    from lbrynet.blob.blob_manager import BlobFileManager
    from asyncio.events import AbstractEventLoop


async def reflect_stream(loop: typing.Any['AbstractEventLoop'] = asyncio.AbstractEventLoop(),
                         descriptor: typing.Any['StreamDescriptor'] = None,
                         protocol: typing.Any['ReflectorClientProtocol'] = ReflectorClient,
                         reflector_server: typing.Optional[str] = None,
                         tcp_port: typing.Optional[int] = 5566,
                         version: typing.Optional[int] = REFLECTOR_V2) -> typing.List:
    """
    reuploads all stream descriptor blobs.
    returns reflector response.
    """
    if not reflector_server:
        reflector_server = random.choice(conf.get_config()['reflector_servers'])
    if not tcp_port:
        tcp_port = 5566
    if descriptor is not None:
        try:
            blobs = descriptor.blobs.copy()
            result = await asyncio.wait_for(loop.create_connection(
                lambda: protocol(version=version, blobs=blobs), reflector_server, tcp_port
            ), loop=loop, timeout=30.0).set_result(protocol().reflect_blobs())
            return await result.result()
        except (asyncio.TimeoutError, asyncio.CancelledError, ReflectorRequestDecodeError,
                ReflectorClientVersionError, ReflectorRequestError, IncompleteResponse) as exc:
            raise exc
    else:
        raise ValueError("Must have stream descriptor to reflect stream!")


async def reflect_blob_file(loop: typing.Any['AbstractEventLoop'] = asyncio.AbstractEventLoop(),
                            blob_file: typing.Any['BlobFile'] = None,
                            protocol: typing.Any['ReflectorClientProtocol'] = ReflectorClient,
                            reflector_server: typing.Optional[str] = None,
                            tcp_port: typing.Optional[int] = 5566,
                            version: typing.Optional[int] = REFLECTOR_V2) -> typing.List:
    """
    reuploads all blobfile blobs.
    returns reflected blobs
    """
    if not reflector_server:
        reflector_server = random.choice(conf.get_config()['reflector_servers'])
    if not tcp_port:
        tcp_port = 5566
    if blob_file is not None:
        try:
            blobs = blob_file.get_is_verified()
            result = await asyncio.wait_for(loop.create_connection(
                lambda: protocol(version=version, blobs=blobs), reflector_server, tcp_port
            ), loop=loop, timeout=30.0).set_result(protocol().reflect_blobs())
            return await result.result()
        except (asyncio.TimeoutError, asyncio.CancelledError, ReflectorRequestDecodeError,
                ReflectorClientVersionError, ReflectorRequestError, IncompleteResponse) as exc:
            raise exc
    else:
        raise ValueError("No blobfile to reflect blobs from!")


async def reflect_blobs(loop: typing.Any['AbstractEventLoop'] = asyncio.AbstractEventLoop(),
                        blob_manager: typing.Any['BlobFileManager'] = None,
                        protocol: typing.Any['ReflectorClientProtocol'] = ReflectorClient,
                        reflector_server: typing.Optional[str] = None,
                        tcp_port: typing.Optional[int] = 5566,
                        version: typing.Optional[int] = REFLECTOR_V2) -> typing.List:
    """
    reuploads all saved blobs.
    returns reflected blobs.
    """
    if reflector_server is None:
        reflector_server = random.choice(conf.get_config()['reflector_servers'])
    if blob_manager is not None:
        try:
            blobs = blob_manager.get_all_verified_blobs()
            result = await asyncio.wait_for(loop.create_connection(
                lambda: protocol(version=version, blobs=blobs), reflector_server, tcp_port
            ), loop=loop, timeout=30.0).set_result(protocol().reflect_blobs())
            return await result.result()
        except (asyncio.TimeoutError, asyncio.CancelledError, ReflectorRequestDecodeError,
                ReflectorClientVersionError, ReflectorRequestError, IncompleteResponse) as exc:
            raise exc
    else:
        raise ValueError("No BlobFileManager to get blobs from!")


async def reflect_blob_hashes(loop: typing.Any['AbstractEventLoop'] = asyncio.AbstractEventLoop(),
                        blob_manager: typing.Any['BlobFileManager'] = None,
                        protocol: typing.Any['ReflectorClientProtocol'] = ReflectorClient,
                        reflector_server: typing.Optional[str] = None,
                        tcp_port: typing.Optional[int] = 5566,
                        version: typing.Optional[int] = REFLECTOR_V2) -> typing.List:
    """
    reuploads all blobs from blob_hashes
    returns reflected blobs.
    """
    if reflector_server is None:
        reflector_server = random.choice(conf.get_config()['reflector_servers'])
    if blob_manager is not None:
        try:
            blobs = blob_manager.get_all_verified_blobs()
            result = await asyncio.wait_for(loop.create_connection(
                lambda: protocol(version=version, blobs=blobs), reflector_server, tcp_port
            ), loop=loop, timeout=30.0).set_result(protocol().reflect_blobs())
            return await result.result()
        except (asyncio.TimeoutError, asyncio.CancelledError, ReflectorRequestDecodeError,
                ReflectorClientVersionError, ReflectorRequestError, IncompleteResponse) as exc:
            raise exc
    else:
        raise ValueError("No BlobFileManager to get blobs from!")
