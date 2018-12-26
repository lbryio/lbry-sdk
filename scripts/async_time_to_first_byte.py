import sys
import os
import binascii
import asyncio
import logging
import datetime
import shutil
import tempfile
from aioupnp.upnp import UPnP
from lbrynet.extras import cli
from lbrynet.log_support import configure_console, disable_third_party_loggers
from lbrynet import conf
from lbrynet.storage import SQLiteStorage
from lbrynet.blob.blob_manager import BlobFileManager
from lbrynet.peer import PeerManager
from lbrynet.dht.node import Node
from lbrynet.stream.downloader import StreamDownloader
from twisted.internet import reactor

log = logging.getLogger("lbrynet")


async def download_stream(sd_hash: str, tmp_dir):
    disable_third_party_loggers()
    configure_console()
    log.setLevel(logging.INFO)
    loop = asyncio.get_event_loop()
    conf.initialize_settings(True)

    peer_manager = PeerManager(loop)
    storage = SQLiteStorage(tmp_dir)
    await storage.setup().asFuture(loop)
    log.info("set up db, finding external ip")
    u = await UPnP.discover()
    external_ip = await u.get_external_ip()

    log.info("got external ip")
    node = Node(peer_manager, loop, conf.settings.get_node_id(), 4444, 4444, 3333, external_ip)
    blob_manager = BlobFileManager(loop, tmp_dir, storage) #, node.protocol.data_store)
    await blob_manager.setup()
    # log.info("joining dht")
    # await node.join_network(interface='0.0.0.0', known_node_urls=[('lbrynet1.lbry.io', 4444)])
    # log.info("joined dht")
    log.info("download stream")
    start = loop.time()

    peer = peer_manager.make_peer(
        '85.17.24.157',
        binascii.unhexlify(b'8fd0519d58ba24c995274c547a183e05cc169734810f26c8f308f0c6cd0d9e1bcb5c21bf3f2ff2a9cef382d801cbb1c4'),
        udp_port=4444,
        tcp_port=4444
    )
    # peer = peer_manager.make_peer(
    #     '35.153.147.111',
    #     binascii.unhexlify(b'ba033064a814214b2cfaf383138d3e96cff9c542be4c5dc97fcb8df3a90a63c001d23834880b84fd773dc03921a86446'),
    #     udp_port=4444,
    #     tcp_port=3333
    # )

    downloader = StreamDownloader(loop, blob_manager, node, sd_hash, 30, 3, download_dir=tmp_dir, file_name='what.mp4')
    # downloader.download()
    downloader.add_peer(peer)
    await downloader.first_bytes_written.wait()
    print(f"Time to first bytes written: {datetime.timedelta(seconds=loop.time() - start)}")
    await downloader.download_finished.wait()
    print(f"Time to finished: {datetime.timedelta(seconds=loop.time() - start)}")
    node.stop()
    reactor.stop()


def main():
    # if len(sys.argv) == 2:
    #     blob_hash = sys.argv[1]
    # else:
    blob_hash = 'd5169241150022f996fa7cd6a9a1c421937276a3275eb912790bd07ba7aec1fac5fd45431d226b8fb402691e79aeb24b'
    # temp_dir = tempfile.mkdtemp()
    # try:
    loop = asyncio.get_event_loop()
    reactor.callLater(0, lambda: loop.create_task(download_stream(blob_hash, "/home/jack/Desktop/tmpblobs")))
    reactor.run()
    # finally:
    #     shutil.rmtree(temp_dir)


if __name__ == "__main__":
    main()
