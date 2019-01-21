import asyncio
import typing
import random

from lbrynet import conf
from lbrynet.extras.reflector.client import ReflectorClient

if typing.TYPE_CHECKING:
    from lbrynet.stream.descriptor import StreamDescriptor
    from lbrynet.blob.blob_manager import BlobFileManager


async def reflect_stream(loop: typing.Any[asyncio.AbstractEventLoop] = asyncio.AbstractEventLoop(),
                         blob_manager: typing.Any['BlobFileManager'] = None,
                         descriptor: typing.Any['StreamDescriptor'] = None,
                         blobs: typing.Any[typing.List] = None,
                         protocol: typing.Any['ReflectorClient'] = ReflectorClient,
                         reflector_server: typing.Optional[str] = None,
                         tcp_port: typing.Optional[int] = 5566,
                         version: typing.Optional[int] = 1) -> typing.List[str]:
    """
    reflects all stream descriptor blobs.
    returns reflected blobs.
    """
    if not reflector_server:
        reflector_server = random.choice(conf.get_config()['reflector_servers'])
    if blobs is not None:
        try:
            result = await asyncio.wait_for(loop.create_connection(
                lambda: protocol(version=version, blob_manager=blob_manager,
                                 descriptor=descriptor, blobs=blobs),
                reflector_server, tcp_port), loop=loop, timeout=30.0)
            return await result.result()
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            raise exc
    else:
        raise ValueError("No stream to reflect blobs from!")


async def reflect_blob_file(loop: typing.Any[asyncio.AbstractEventLoop] = asyncio.AbstractEventLoop(),
                            blob_manager: typing.Any['BlobFileManager'] = None,
                            blobs: typing.Any[typing.List] = None,
                            protocol: typing.Any['ReflectorClient'] = ReflectorClient,
                            reflector_server: typing.Optional[str] = None,
                            tcp_port: typing.Optional[int] = 5566,
                            version: typing.Optional[int] = 1) -> typing.List[str]:
    """
    reflects all lbry file blobs.
    returns reflected blobs.
    """
    if not reflector_server:
        reflector_server = random.choice(conf.get_config()['reflector_servers'])
    if blobs is not None:
        try:
            result = await asyncio.wait_for(loop.create_connection(
                lambda: protocol(version=version, blob_manager=blob_manager, blobs=blobs),
                reflector_server, tcp_port), loop=loop, timeout=30.0)
            return await result.result()
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            raise exc
    else:
        raise ValueError("No File to reflect Blobs from!")


async def reflect_blobs(loop: typing.Any[asyncio.AbstractEventLoop] = asyncio.AbstractEventLoop(),
                        blob_manager: typing.Any['BlobFileManager'] = None,
                        blobs: typing.Any[typing.List] = None,
                        protocol: typing.Any['ReflectorClient'] = ReflectorClient,
                        reflector_server: typing.Optional[str] = None,
                        tcp_port: typing.Optional[int] = 5566,
                        version: typing.Optional[int] = 1) -> typing.List[str]:
    """
    reflects all saved blobs.
    returns reflected blobs.
    """
    if reflector_server is None:
        reflector_server = random.choice(conf.get_config()['reflector_servers'])
    if blob_manager is not None:
        try:
            blobs = blob_manager.get_all_verified_blobs()
            result = await asyncio.wait_for(loop.create_connection(
                lambda: protocol(version=version, blob_manager=blob_manager, blobs=blobs),
                reflector_server, tcp_port), loop=loop, timeout=30.0)
            return await result.result()
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            raise exc
    else:
        raise ValueError("No Blob Manager to reflect Blobs from!")


async def reflect_blob_hashes(loop: typing.Any[asyncio.AbstractEventLoop] = asyncio.AbstractEventLoop(),
                              blob_manager: typing.Any['BlobFileManager'] = None,
                              blobs: typing.Any[typing.List] = None,
                              protocol: typing.Any['ReflectorClient'] = ReflectorClient,
                              reflector_server: typing.Optional[str] = None,
                              tcp_port: typing.Optional[int] = 5566,
                              version: typing.Optional[int] = 1) -> typing.List[str]:
    """
    reflects all blobs from their respective blob hash.
    returns reflected blobs.
    """
    if reflector_server is None:
        reflector_server = random.choice(conf.get_config()['reflector_servers'])
    if blobs is not None:
        try:
            result = await asyncio.wait_for(loop.create_connection(
                lambda: protocol(version=version, blob_manager=blob_manager, blobs=blobs),
                reflector_server, tcp_port), loop=loop, timeout=30.0)
            return await result.result()
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            raise exc
    else:
        raise ValueError("No Blobs to reflect from!")
