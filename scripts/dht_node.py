import asyncio
import argparse
import logging
from typing import Optional

from lbry.dht.constants import generate_id
from lbry.dht.node import Node
from lbry.dht.peer import PeerManager
from lbry.extras.daemon.storage import SQLiteStorage
from lbry.conf import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-4s %(name)s:%(lineno)d: %(message)s")
log = logging.getLogger(__name__)


async def main(host: str, port: int, db_file_path: str, bootstrap_node: Optional[str]):
    loop = asyncio.get_event_loop()
    conf = Config()
    storage = SQLiteStorage(conf, db_file_path, loop, loop.time)
    if bootstrap_node:
        nodes = bootstrap_node.split(':')
        nodes = [(nodes[0], int(nodes[1]))]
    else:
        nodes = conf.known_dht_nodes
    await storage.open()
    node = Node(
        loop, PeerManager(loop), generate_id(), port, port, 3333, None,
        storage=storage
    )
    node.start(host, nodes)
    while True:
        await asyncio.sleep(10)
        log.info("Known peers: %d. Storing contact information for %d blobs from %d peers.",
                 len(node.protocol.routing_table.get_peers()), len(node.protocol.data_store),
                 len(node.protocol.data_store.get_storing_contacts()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Starts a single DHT node, which then can be used as a seed node or just a contributing node.")
    parser.add_argument("--host", default='0.0.0.0', type=str, help="Host to listen for requests. Default: 0.0.0.0")
    parser.add_argument("--port", default=4444, type=int, help="Port to listen for requests. Default: 4444")
    parser.add_argument("--db_file", default='/tmp/dht.db', type=str, help="DB file to save peers. Default: /tmp/dht.db")
    parser.add_argument("--bootstrap_node", default=None, type=str,
                        help="Node to connect for bootstraping this node. Leave unset to use the default ones. "
                             "Format: host:port Example: lbrynet1.lbry.com:4444")
    args = parser.parse_args()
    asyncio.run(main(args.host, args.port, args.db_file, args.bootstrap_node))
