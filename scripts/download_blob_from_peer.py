import sys
import os
import asyncio
import socket
from lbrynet.conf import Config
from lbrynet.extras.daemon.storage import SQLiteStorage
from lbrynet.blob.blob_manager import BlobFileManager
from lbrynet.blob_exchange.client import BlobExchangeClientProtocol, request_blob
import logging

log = logging.getLogger("lbrynet")
log.addHandler(logging.StreamHandler())
log.setLevel(logging.DEBUG)


async def main(blob_hash: str, url: str):
    conf = Config()
    loop = asyncio.get_running_loop()
    host_url, port = url.split(":")
    host_info = await loop.getaddrinfo(
        host_url, 'https',
        proto=socket.IPPROTO_TCP,
    )
    host = host_info[0][4][0]

    storage = SQLiteStorage(conf, os.path.join(conf.data_dir, "lbrynet.sqlite"))
    blob_manager = BlobFileManager(loop, os.path.join(conf.data_dir, "blobfiles"), storage)
    await storage.open()
    await blob_manager.setup()

    blob = blob_manager.get_blob(blob_hash)
    protocol = BlobExchangeClientProtocol(loop, conf.blob_download_timeout)
    success, keep = await request_blob(loop, blob, protocol, host, int(port), conf.peer_connect_timeout)
    print(success, keep)
    if blob.get_is_verified():
        await blob_manager.delete_blobs([blob.blob_hash])


if __name__ == "__main__":  # usage: python download_blob_from_peer.py <blob_hash> [host url:port]
    url = 'reflector.lbry.io:5567'
    if len(sys.argv) > 2:
        url = sys.argv[2]
    asyncio.run(main(sys.argv[1], url))
