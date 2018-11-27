import sys
import os
import asyncio
import logging
from aioupnp.upnp import UPnP
from lbrynet.extras import cli
from lbrynet.log_support import configure_console, disable_third_party_loggers
from twisted.internet import reactor
from lbrynet import conf
from lbrynet.extras.daemon.storage import SQLiteStorage
from lbrynet.extras.daemon.blob_manager import DiskBlobManager
from lbrynet.peer import PeerManager
from lbrynet.blob.blob_file import BlobFile
from lbrynet.dht.node import Node
from lbrynet.blob_exchange.async_client import download_single_blob


log = logging.getLogger("lbrynet")


async def download_blob(blob_hash: str):
    disable_third_party_loggers()
    configure_console()
    log.setLevel(logging.DEBUG)
    loop = asyncio.get_event_loop()
    conf.initialize_settings(True)

    data_dir = os.path.expanduser("~/.lbrynet")
    blob_dir = os.path.expanduser("~/.lbrynet/blobfiles")

    peer_manager = PeerManager(loop)
    storage = SQLiteStorage(data_dir)
    await storage.setup().asFuture(loop)

    u = await UPnP.discover()
    external_ip = await u.get_external_ip()

    node = Node(peer_manager, loop, conf.settings.get_node_id(), 4447, 4447, 3336, external_ip)
    blob_manager = DiskBlobManager(blob_dir, storage, node.protocol.data_store)
    await blob_manager.setup().asFuture(loop)
    log.info("joining dht")
    await node.join_network(interface='0.0.0.0', known_node_urls=[('lbrynet1.lbry.io', 4444)])
    log.info("joined dht")
    log.info("download blob")
    downloaded_from = await download_single_blob(node, BlobFile(blob_dir, blob_hash))
    log.info("downloaded: %s", downloaded_from)
    node.stop()
    reactor.callLater(0, reactor.stop)


def main():
    blob_hash = sys.argv[1]
    reactor.callLater(0, asyncio.create_task, download_blob(blob_hash))
    reactor.run()


if __name__ == "__main__":
    main()
