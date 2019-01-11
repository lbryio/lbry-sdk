import asyncio
import functools
from lbrynet.extras.reflector.client.blob import BlobProtocol


def blob_factory(blob_manager, blobs, *addr):
    loop = asyncio.get_running_loop()
    __done = loop.create_future()
    factory = functools.partial(BlobProtocol, blob_manager, blobs)
    protocol = loop.create_connection(factory, *addr)
    try:
        loop.run_until_complete(protocol)
        loop.run_until_complete(__done)
    finally:
        loop.close()
