import sys
import os
import asyncio
import logging

from lbry.blob_exchange.client import request_blob
from lbry.utils import resolve_host

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)-4s %(name)s:%(lineno)d: %(message)s")
from lbry.blob.blob_manager import BlobManager
from lbry.blob_exchange.server import BlobServer
from lbry.extras.daemon.storage import SQLiteStorage
from lbry.wallet import Ledger
from lbry.conf import Config


async def main(address: str):
    if not Ledger.is_pubkey_address(address):
        print(f"'{address}' is not a valid lbrycrd address")
        return 1
    loop = asyncio.get_running_loop()
    conf = Config()

    async def ensure_blob(blob):
        upstream_host, upstream_port = conf.fixed_peers[0]
        upstream_host = await resolve_host(upstream_host, upstream_port, 'tcp')
        success, proto = await request_blob(loop, blob, upstream_host, int(upstream_port), conf.peer_connect_timeout,
                                            conf.blob_download_timeout)
        print(success, proto)
        if proto:
            proto.close()

    storage = SQLiteStorage(conf, os.path.expanduser("/tmp/lbrynet.sqlite"))
    await storage.open()
    blob_manager = BlobManager(loop, os.path.expanduser("/tmp/blobfiles"), storage, conf)
    await blob_manager.setup()

    server = BlobServer(loop, blob_manager, address, blob_callback=ensure_blob)
    try:
        server.start_server(6666, '0.0.0.0')
        while True:
            await asyncio.sleep(1)
    finally:
        await storage.close()

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
