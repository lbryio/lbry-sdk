"""A simple script that attempts to directly download a single blob or stream from a given peer"""
import argparse
import logging
import sys
import os
import binascii
import asyncio
from twisted.internet import asyncioreactor
asyncioreactor.install()
from twisted.internet import reactor
from lbrynet.peer import PeerManager
from lbrynet.blob.blob_manager import BlobFileManager
from lbrynet.storage import SQLiteStorage

log = logging.getLogger()


def main(args=None):
    loop = asyncio.get_event_loop()
    reactor.callLater(0, loop.create_task, download_it('d5169241150022f996fa7cd6a9a1c421937276a3275eb912790bd07ba7aec1fac5fd45431d226b8fb402691e79aeb24b'))
    reactor.run()


async def download_it(blob_hash):
    loop = asyncio.get_event_loop()
    storage = SQLiteStorage(os.path.expanduser("~/Desktop/tmpblobs"))
    await storage.setup().asFuture(loop)
    blob_manager = BlobFileManager(loop, os.path.expanduser("~/Desktop/tmpblobs"), storage)
    peer_manager = PeerManager(loop)
    node_id = binascii.unhexlify(b'8fd0519d58ba24c995274c547a183e05cc169734810f26c8f308f0c6cd0d9e1bcb5c21bf3f2ff2a9cef382d801cbb1c4')
    peer = peer_manager.make_peer('85.17.24.157', node_id, udp_port=4444, tcp_port=4444)
    blob = blob_manager.get_blob(blob_hash)
    downloaded = await peer.request_blobs(30, 30, [blob])
    print(downloaded)
    reactor.stop()


if __name__ == '__main__':
    sys.exit(main())
