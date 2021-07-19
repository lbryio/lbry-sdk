"""A simple script that attempts to directly download a single blob.

To Do:
------
Currently `lbrynet blob get <hash>` does not work to download single blobs
which are not already present in the system. The function locks up and
never returns.
It only works for blobs that are in the `blobfiles` directory already.

This bug is reported in lbryio/lbry-sdk, issue #2070.

Maybe this script can be investigated, and certain parts can be added to
`lbry.extras.daemon.daemon.jsonrpc_blob_get`
in order to solve the previous issue, and finally download single blobs
from the network (peers or reflector servers).
"""
import sys
import os
import asyncio
import socket
import ipaddress
import lbry.wallet
from lbry.conf import Config
from lbry.extras.daemon.storage import SQLiteStorage
from lbry.blob.blob_manager import BlobManager
from lbry.blob_exchange.client import BlobExchangeClientProtocol, request_blob
import logging

log = logging.getLogger("lbry")
log.addHandler(logging.StreamHandler())
log.setLevel(logging.DEBUG)


async def main(blob_hash: str, url: str):
    conf = Config()
    loop = asyncio.get_running_loop()
    host_url, port = url.split(":")
    try:
        host = None
        if ipaddress.ip_address(host_url):
            host = host_url
    except ValueError:
        host = None
    if not host:
        host_info = await loop.getaddrinfo(
            host_url, 'https',
            proto=socket.IPPROTO_TCP,
        )
        host = host_info[0][4][0]

    storage = SQLiteStorage(conf, os.path.join(conf.data_dir, "lbrynet.sqlite"))
    blob_manager = BlobManager(loop, os.path.join(conf.data_dir, "blobfiles"), storage, conf)
    await storage.open()
    await blob_manager.setup()

    blob = blob_manager.get_blob(blob_hash)
    success, keep = await request_blob(loop, blob, host, int(port), conf.peer_connect_timeout,
                                       conf.blob_download_timeout)
    print(f"{'downloaded' if success else 'failed to download'} {blob_hash} from {host}:{port}\n"
          f"keep connection: {keep}")
    if blob.get_is_verified():
        await blob_manager.delete_blobs([blob.blob_hash])
        print(f"deleted {blob_hash}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: download_blob_from_peer.py <blob_hash> [host_url:port]")
        sys.exit(1)

    url = 'reflector.lbry.com:5567'
    if len(sys.argv) > 2:
        url = sys.argv[2]
    asyncio.run(main(sys.argv[1], url))
