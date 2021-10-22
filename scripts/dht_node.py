import asyncio
import argparse
import logging
from typing import Optional
from aiohttp import web
from prometheus_client import generate_latest as prom_generate_latest, Gauge

from lbry.dht.constants import generate_id
from lbry.dht.node import Node
from lbry.dht.peer import PeerManager
from lbry.extras.daemon.storage import SQLiteStorage
from lbry.conf import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-4s %(name)s:%(lineno)d: %(message)s")
log = logging.getLogger(__name__)
BLOBS_STORED = Gauge(
    "blobs_stored", "Number of blob info received", namespace="dht_node",
    labelnames=("method",)
)
PEERS = Gauge(
    "known_peers", "Number of peers on routing table", namespace="dht_node",
    labelnames=("method",)
)


class SimpleMetrics:
    def __init__(self, port):
        self.prometheus_port = port

    async def handle_metrics_get_request(self, request: web.Request):
        try:
            return web.Response(
                text=prom_generate_latest().decode(),
                content_type='text/plain; version=0.0.4'
            )
        except Exception:
            log.exception('could not generate prometheus data')
            raise

    async def start(self):
        prom_app = web.Application()
        prom_app.router.add_get('/metrics', self.handle_metrics_get_request)
        metrics_runner = web.AppRunner(prom_app)
        await metrics_runner.setup()
        prom_site = web.TCPSite(metrics_runner, "0.0.0.0", self.prometheus_port)
        await prom_site.start()


async def main(host: str, port: int, db_file_path: str, bootstrap_node: Optional[str], prometheus_port: int):
    if prometheus_port > 0:
        metrics = SimpleMetrics(prometheus_port)
        await metrics.start()
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
        PEERS.labels('main').set(len(node.protocol.routing_table.get_peers()))
        BLOBS_STORED.labels('main').set(len(node.protocol.data_store.get_storing_contacts()))
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
    parser.add_argument("--prometheus_port", default=0, type=int, help="Port for Prometheus metrics. 0 to disable. Default: 0")
    args = parser.parse_args()
    asyncio.run(main(args.host, args.port, args.db_file, args.bootstrap_node, args.prometheus_port))
