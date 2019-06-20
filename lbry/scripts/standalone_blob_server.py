import sys
import os
import asyncio
from lbrynet.blob.blob_manager import BlobManager
from lbrynet.blob_exchange.server import BlobServer
from lbrynet.schema.address import decode_address
from lbrynet.extras.daemon.storage import SQLiteStorage


async def main(address: str):
    try:
        decode_address(address)
    except:
        print(f"'{address}' is not a valid lbrycrd address")
        return 1
    loop = asyncio.get_running_loop()

    storage = SQLiteStorage(os.path.expanduser("~/.lbrynet/lbrynet.sqlite"))
    await storage.open()
    blob_manager = BlobManager(loop, os.path.expanduser("~/.lbrynet/blobfiles"), storage)
    await blob_manager.setup()

    server = await loop.create_server(
        lambda: BlobServer(loop, blob_manager, address),
        '0.0.0.0', 4444)
    try:
        async with server:
            await server.serve_forever()
    finally:
        await storage.close()

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
