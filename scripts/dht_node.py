import asyncio
import argparse
import logging
import csv
import os.path
from io import StringIO
from typing import Optional
from aiohttp import web
from prometheus_client import generate_latest as prom_generate_latest

from lbry.dht.constants import generate_id
from lbry.dht.node import Node
from lbry.dht.peer import PeerManager
from lbry.extras.daemon.storage import SQLiteStorage
from lbry.conf import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-4s %(name)s:%(lineno)d: %(message)s")
log = logging.getLogger(__name__)


class SimpleMetrics:
    def __init__(self, port, node):
        self.prometheus_port = port
        self.dht_node: Node = node

    async def handle_metrics_get_request(self, _):
        try:
            return web.Response(
                text=prom_generate_latest().decode(),
                content_type='text/plain; version=0.0.4'
            )
        except Exception:
            log.exception('could not generate prometheus data')
            raise

    async def handle_peers_csv(self, _):
        out = StringIO()
        writer = csv.DictWriter(out, fieldnames=["ip", "port", "dht_id"])
        writer.writeheader()
        for peer in self.dht_node.protocol.routing_table.get_peers():
            writer.writerow({"ip": peer.address, "port": peer.udp_port, "dht_id": peer.node_id.hex()})
        return web.Response(text=out.getvalue(), content_type='text/csv')

    async def handle_blobs_csv(self, _):
        out = StringIO()
        writer = csv.DictWriter(out, fieldnames=["blob_hash"])
        writer.writeheader()
        for blob in self.dht_node.protocol.data_store.keys():
            writer.writerow({"blob_hash": blob.hex()})
        return web.Response(text=out.getvalue(), content_type='text/csv')

    async def start(self):
        prom_app = web.Application()
        prom_app.router.add_get('/metrics', self.handle_metrics_get_request)
        if self.dht_node:
            prom_app.router.add_get('/peers.csv', self.handle_peers_csv)
            prom_app.router.add_get('/blobs.csv', self.handle_blobs_csv)
        metrics_runner = web.AppRunner(prom_app)
        await metrics_runner.setup()
        prom_site = web.TCPSite(metrics_runner, "0.0.0.0", self.prometheus_port)
        await prom_site.start()


async def main(host: str, port: int, db_file_path: str, bootstrap_node: Optional[str], prometheus_port: int, export: bool):
    loop = asyncio.get_event_loop()
    conf = Config()
    if not db_file_path.startswith(':memory:'):
        node_id_file_path = db_file_path + 'node_id'
        if os.path.exists(node_id_file_path):
            with open(node_id_file_path, 'rb') as node_id_file:
                node_id = node_id_file.read()
        else:
            with open(node_id_file_path, 'wb') as node_id_file:
                node_id = generate_id()
                node_id_file.write(node_id)

    storage = SQLiteStorage(conf, db_file_path, loop, loop.time)
    if bootstrap_node:
        nodes = bootstrap_node.split(':')
        nodes = [(nodes[0], int(nodes[1]))]
    else:
        nodes = conf.known_dht_nodes
    await storage.open()
    node = Node(
        loop, PeerManager(loop), node_id, port, port, 3333, None,
        storage=storage, is_bootstrap_node=True
    )
    if prometheus_port > 0:
        metrics = SimpleMetrics(prometheus_port, node if export else None)
        await metrics.start()
    node.start(host, nodes)
    log.info("Peer with id %s started", node_id.hex())
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
    parser.add_argument("--metrics_port", default=0, type=int, help="Port for Prometheus metrics. 0 to disable. Default: 0")
    parser.add_argument("--enable_csv_export", action='store_true', help="Enable CSV endpoints on metrics server.")
    args = parser.parse_args()
    asyncio.run(main(args.host, args.port, args.db_file, args.bootstrap_node, args.metrics_port, args.enable_csv_export))
