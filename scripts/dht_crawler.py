import sys
import datetime
import logging
import asyncio
import os.path
import random
import time
import typing
from dataclasses import dataclass, astuple, replace

from aiohttp import web
from prometheus_client import Gauge, generate_latest as prom_generate_latest, Counter

import lbry.dht.error
from lbry.dht.constants import generate_id
from lbry.dht.node import Node
from lbry.dht.peer import make_kademlia_peer, PeerManager, decode_tcp_peer_from_compact_address
from lbry.dht.protocol.distance import Distance
from lbry.dht.protocol.iterative_find import FindValueResponse, FindNodeResponse, FindResponse
from lbry.extras.daemon.storage import SQLiteMixin
from lbry.conf import Config
from lbry.utils import resolve_host


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-4s %(name)s:%(lineno)d: %(message)s")
log = logging.getLogger(__name__)


class SDHashSamples:
    def __init__(self, samples_file_path):
        with open(samples_file_path, "rb") as sample_file:
            self._samples = sample_file.read()
        assert len(self._samples) % 48 == 0
        self.size = len(self._samples) // 48

    def read_samples(self, count=1):
        for _ in range(count):
            offset = 48 * random.randrange(0, self.size)
            yield self._samples[offset:offset + 48]


class PeerStorage(SQLiteMixin):
    CREATE_TABLES_QUERY = """
    PRAGMA JOURNAL_MODE=WAL;
    CREATE TABLE IF NOT EXISTS peer (
        peer_id INTEGER NOT NULL,
        node_id VARCHAR(96),
        address VARCHAR,
        udp_port INTEGER,
        tcp_port INTEGER,
        first_online DATETIME,
        errors INTEGER,
        last_churn INTEGER,
        added_on DATETIME NOT NULL,
        last_check DATETIME,
        last_seen DATETIME,
        latency INTEGER,
        PRIMARY KEY (peer_id)
    );
    CREATE TABLE IF NOT EXISTS connection (
        from_peer_id INTEGER NOT NULL,
        to_peer_id INTEGER NOT NULL,
        PRIMARY KEY (from_peer_id, to_peer_id),
        FOREIGN KEY(from_peer_id) REFERENCES peer (peer_id),
        FOREIGN KEY(to_peer_id) REFERENCES peer (peer_id)
    );
"""

    async def open(self):
        await super().open()
        self.db.writer_connection.row_factory = dict_row_factory

    async def all_peers(self):
        return [
            DHTPeer(**peer) for peer in await self.db.execute_fetchall(
                "select * from peer where latency > 0 or last_seen < datetime('now', '-1h')")
        ]

    async def save_peers(self, *peers):
        log.info("Saving graph nodes (peers) to DB")
        await self.db.executemany(
            "INSERT OR REPLACE INTO peer("
            "node_id, address, udp_port, tcp_port, first_online, errors, last_churn,"
            "added_on, last_check, last_seen, latency, peer_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [astuple(peer) for peer in peers]
        )
        log.info("Finished saving graph nodes (peers) to DB")

    async def save_connections(self, connections_map):
        log.info("Saving graph edges (connections) to DB")
        await self.db.executemany(
            "DELETE FROM connection WHERE from_peer_id = ?", [(key,) for key in connections_map])
        for from_peer_id in connections_map:
            await self.db.executemany(
                "INSERT INTO connection(from_peer_id, to_peer_id) VALUES(?,?)",
                [(from_peer_id, to_peer_id) for to_peer_id in connections_map[from_peer_id]])
        log.info("Finished saving graph edges (connections) to DB")


@dataclass(frozen=True)
class DHTPeer:
    node_id: str
    address: str
    udp_port: int
    tcp_port: int = None
    first_online: datetime.datetime = None
    errors: int = None
    last_churn: int = None
    added_on: datetime.datetime = None
    last_check: datetime.datetime = None
    last_seen: datetime.datetime = None
    latency: int = None
    peer_id: int = None

    @classmethod
    def from_kad_peer(cls, peer, peer_id):
        node_id = peer.node_id.hex() if peer.node_id else None
        return DHTPeer(
            node_id=node_id, address=peer.address, udp_port=peer.udp_port, tcp_port=peer.tcp_port,
            peer_id=peer_id, added_on=datetime.datetime.utcnow())

    def to_kad_peer(self):
        node_id = bytes.fromhex(self.node_id) if self.node_id else None
        return make_kademlia_peer(node_id, self.address, self.udp_port, self.tcp_port)


def new_node(address="0.0.0.0", udp_port=0, node_id=None):
    node_id = node_id or generate_id()
    loop = asyncio.get_event_loop()
    return Node(loop, PeerManager(loop), node_id, udp_port, udp_port, 3333, address)


class Crawler:
    unique_total_hosts_metric = Gauge(
        "unique_total_hosts", "Number of unique hosts seen in the last interval", namespace="dht_crawler_node",
        labelnames=("scope",)
    )
    reachable_hosts_metric = Gauge(
        "reachable_hosts", "Number of hosts that replied in the last interval", namespace="dht_crawler_node",
        labelnames=("scope",)
    )
    total_historic_hosts_metric = Gauge(
        "history_total_hosts", "Number of hosts seen since first run.", namespace="dht_crawler_node",
        labelnames=("scope",)
    )
    pending_check_hosts_metric = Gauge(
        "pending_hosts", "Number of hosts on queue to be checked.", namespace="dht_crawler_node",
        labelnames=("scope",)
    )
    hosts_with_errors_metric = Gauge(
        "error_hosts", "Number of hosts that raised errors during contact.", namespace="dht_crawler_node",
        labelnames=("scope",)
    )
    connections_found_metric = Gauge(
        "connections_found", "Number of hosts returned by the last successful contact.", namespace="dht_crawler_node",
        labelnames=("host", "port")
    )
    host_latency_metric = Gauge(
        "host_latency", "Time spent on the last request, in nanoseconds.", namespace="dht_crawler_node",
        labelnames=("host", "port")
    )
    probed_streams_metric = Counter(
        "probed_streams", "Amount of streams probed.", namespace="dht_crawler_node",
        labelnames=("scope",)
    )
    announced_streams_metric = Counter(
        "announced_streams", "Amount of streams where announcements were found.", namespace="dht_crawler_node",
        labelnames=("scope",)
    )
    working_streams_metric = Counter(
        "working_streams", "Amount of streams with reachable hosts.", namespace="dht_crawler_node",
        labelnames=("scope",)
    )

    def __init__(self, db_path: str, sd_hash_samples: SDHashSamples):
        self.node = new_node()
        self.db = PeerStorage(db_path)
        self.sd_hashes = sd_hash_samples
        self._memory_peers = {}
        self._reachable_by_node_id = {}
        self._connections = {}

    async def open(self):
        await self.db.open()
        self._memory_peers = {
            (peer.address, peer.udp_port): peer for peer in await self.db.all_peers()
        }
        self.refresh_reachable_set()

    def refresh_reachable_set(self):
        self._reachable_by_node_id = {
            bytes.fromhex(peer.node_id): peer for peer in self._memory_peers.values() if (peer.latency or 0) > 0
        }

    async def probe_files(self):
        if not self.sd_hashes:
            return
        while True:
            for sd_hash in self.sd_hashes.read_samples(10_000):
                self.refresh_reachable_set()
                distance = Distance(sd_hash)
                node_ids = list(self._reachable_by_node_id.keys())
                node_ids.sort(key=lambda node_id: distance(node_id))
                k_closest = [self._reachable_by_node_id[node_id] for node_id in node_ids[:8]]
                found = False
                working = False
                for response in asyncio.as_completed(
                        [self.request_peers(peer.address, peer.udp_port, peer.node_id, sd_hash) for peer in k_closest]):
                    response = await response
                    if response and response.found:
                        found = True
                        blob_peers = []
                        for compact_addr in response.found_compact_addresses:
                            try:
                                blob_peers.append(decode_tcp_peer_from_compact_address(compact_addr))
                            except ValueError as e:
                                log.error("Error decoding compact peers: %s", e)
                        for blob_peer in blob_peers:
                            response = await self.request_peers(blob_peer.address, blob_peer.tcp_port, blob_peer.node_id, sd_hash)
                            if response:
                                working = True
                                log.info("Found responsive peer for %s: %s:%d(%d)",
                                         sd_hash.hex()[:8], blob_peer.address,
                                         blob_peer.udp_port or -1, blob_peer.tcp_port or -1)
                            else:
                                log.info("Found dead peer for %s: %s:%d(%d)",
                                         sd_hash.hex()[:8], blob_peer.address,
                                         blob_peer.udp_port or -1, blob_peer.tcp_port or -1)
                self.probed_streams_metric.labels("global").inc()
                if found:
                    self.announced_streams_metric.labels("global").inc()
                if working:
                    self.working_streams_metric.labels("global").inc()
                log.info("Done querying stream %s for peers. Found: %s, working: %s", sd_hash.hex()[:8], found, working)
                await asyncio.sleep(.5)

    @property
    def refresh_limit(self):
        return datetime.datetime.utcnow() - datetime.timedelta(hours=1)

    @property
    def all_peers(self):
        return [
            peer for peer in self._memory_peers.values()
            if (peer.last_seen and peer.last_seen > self.refresh_limit) or (peer.latency or 0) > 0
        ]

    @property
    def active_peers_count(self):
        return len(self.all_peers)

    @property
    def checked_peers_count(self):
        return len([peer for peer in self.all_peers if peer.last_check and peer.last_check > self.refresh_limit])

    @property
    def unreachable_peers_count(self):
        return len([peer for peer in self.all_peers
                    if peer.last_check and peer.last_check > self.refresh_limit and not peer.latency])

    @property
    def peers_with_errors_count(self):
        return len([peer for peer in self.all_peers if (peer.errors or 0) > 0])

    def get_peers_needing_check(self):
        to_check = [peer for peer in self.all_peers if peer.last_check is None or peer.last_check < self.refresh_limit]
        return to_check

    def remove_expired_peers(self):
        for key, peer in list(self._memory_peers.items()):
            if (peer.latency or 0) < 1 and peer.last_seen < self.refresh_limit:
                del self._memory_peers[key]

    def add_peers(self, *peers):
        for peer in peers:
            db_peer = self.get_from_peer(peer)
            if db_peer and db_peer.node_id is None and peer.node_id is not None:
                db_peer = replace(db_peer, node_id=peer.node_id.hex())
            elif not db_peer:
                db_peer = DHTPeer.from_kad_peer(peer, len(self._memory_peers) + 1)
            db_peer = replace(db_peer, last_seen=datetime.datetime.utcnow())
            self._memory_peers[(peer.address, peer.udp_port)] = db_peer

    async def flush_to_db(self):
        await self.db.save_peers(*self._memory_peers.values())
        connections_to_save = self._connections
        self._connections = {}
        # await self.db.save_connections(connections_to_save)  heavy call
        self.remove_expired_peers()

    def get_from_peer(self, peer):
        return self._memory_peers.get((peer.address, peer.udp_port), None)

    def set_latency(self, peer, latency=None):
        if latency:
            self.host_latency_metric.labels(host=peer.address, port=peer.udp_port).set(latency)
        db_peer = self.get_from_peer(peer)
        if not db_peer:
            return
        db_peer = replace(db_peer, latency=latency)
        if not db_peer.node_id and peer.node_id:
            db_peer = replace(db_peer, node_id=peer.node_id.hex())
        if db_peer.first_online and latency is None:
            db_peer = replace(db_peer, last_churn=(datetime.datetime.utcnow() - db_peer.first_online).seconds)
        elif latency is not None and db_peer.first_online is None:
            db_peer = replace(db_peer, first_online=datetime.datetime.utcnow())
        db_peer = replace(db_peer, last_check=datetime.datetime.utcnow())
        self._memory_peers[(db_peer.address, db_peer.udp_port)] = db_peer

    def inc_errors(self, peer):
        db_peer = self.get_from_peer(peer)
        self._memory_peers[(peer.address, peer.node_id)] = replace(db_peer, errors=(db_peer.errors or 0) + 1)

    def associate_peers(self, peer, other_peers):
        self._connections[self.get_from_peer(peer).peer_id] = [
            self.get_from_peer(other_peer).peer_id for other_peer in other_peers]

    async def request_peers(self, host, port, node_id, key=None) -> typing.Optional[FindResponse]:
        key = key or node_id
        peer = make_kademlia_peer(key, await resolve_host(host, port, 'udp'), port)
        for attempt in range(3):
            try:
                req_start = time.perf_counter_ns()
                if key == node_id:
                    response = await self.node.protocol.get_rpc_peer(peer).find_node(key)
                    response = FindNodeResponse(key, response)
                    latency = time.perf_counter_ns() - req_start
                    self.set_latency(peer, latency)
                else:
                    response = await self.node.protocol.get_rpc_peer(peer).find_value(key)
                    response = FindValueResponse(key, response)
                await asyncio.sleep(0.05)
                return response
            except asyncio.TimeoutError:
                if key == node_id:
                    self.set_latency(peer, None)
                continue
            except lbry.dht.error.RemoteException as e:
                log.info('Peer errored: %s:%d attempt #%d - %s',
                         host, port, (attempt + 1), str(e))
                if key == node_id:
                    self.inc_errors(peer)
                    self.set_latency(peer, None)
                continue

    async def crawl_routing_table(self, host, port, node_id=None):
        start = time.time()
        log.debug("querying %s:%d", host, port)
        address = await resolve_host(host, port, 'udp')
        key = node_id or self.node.protocol.peer_manager.get_node_id_for_endpoint(address, port)
        peer = make_kademlia_peer(key, address, port)
        self.add_peers(peer)
        if not key:
            latency = None
            for _ in range(3):
                try:
                    ping_start = time.perf_counter_ns()
                    await self.node.protocol.get_rpc_peer(peer).ping()
                    await asyncio.sleep(0.05)
                    key = key or self.node.protocol.peer_manager.get_node_id_for_endpoint(address, port)
                    peer = make_kademlia_peer(key, address, port)
                    latency = time.perf_counter_ns() - ping_start
                    break
                except asyncio.TimeoutError:
                    pass
                except lbry.dht.error.RemoteException:
                    self.inc_errors(peer)
                    pass
            self.set_latency(peer, latency if peer.node_id else None)
            if not latency or not peer.node_id:
                if latency and not peer.node_id:
                    log.warning("No node id from %s:%d", host, port)
                return set()
        distance = Distance(key)
        max_distance = int.from_bytes(bytes([0xff] * 48), 'big')
        peers = set()
        factor = 2048
        for i in range(1000):
            response = await self.request_peers(address, port, key)
            new_peers = list(response.get_close_kademlia_peers(peer)) if response else None
            if not new_peers:
                break
            new_peers.sort(key=lambda peer: distance(peer.node_id))
            peers.update(new_peers)
            far_key = new_peers[-1].node_id
            if distance(far_key) <= distance(key):
                current_distance = distance(key)
                next_jump = current_distance + int(max_distance // factor)  # jump closer
                factor /= 2
                if factor > 8 and next_jump < max_distance:
                    key = int.from_bytes(peer.node_id, 'big') ^ next_jump
                    if key.bit_length() > 384:
                        break
                    key = key.to_bytes(48, 'big')
                else:
                    break
            else:
                key = far_key
                factor = 2048
        if peers:
            log.info("Done querying %s:%d in %.2f seconds: %d peers found over %d requests.",
                     host, port, (time.time() - start), len(peers), i)
        self.add_peers(*peers)
        if peers:
            self.connections_found_metric.labels(host=host, port=port).set(len(peers))
        self.associate_peers(peer, peers)
        return peers

    async def process(self):
        to_process = {}

        def submit(_peer):
            f = asyncio.ensure_future(
                self.crawl_routing_table(_peer.address, _peer.udp_port, bytes.fromhex(_peer.node_id)))
            to_process[_peer.peer_id] = f
            f.add_done_callback(lambda _: to_process.pop(_peer.peer_id))

        to_check = self.get_peers_needing_check()
        last_flush = datetime.datetime.utcnow()
        while True:
            for peer in to_check[:200]:
                if peer.peer_id not in to_process:
                    submit(peer)
                    await asyncio.sleep(.05)
            await asyncio.sleep(0)
            self.unique_total_hosts_metric.labels("global").set(self.checked_peers_count)
            self.reachable_hosts_metric.labels("global").set(self.checked_peers_count - self.unreachable_peers_count)
            self.total_historic_hosts_metric.labels("global").set(len(self._memory_peers))
            self.pending_check_hosts_metric.labels("global").set(len(to_check))
            self.hosts_with_errors_metric.labels("global").set(self.peers_with_errors_count)
            log.info("%d known, %d contacted recently, %d unreachable, %d error, %d processing, %d on queue",
                     self.active_peers_count, self.checked_peers_count, self.unreachable_peers_count,
                     self.peers_with_errors_count, len(to_process), len(to_check))
            if to_process:
                await asyncio.wait(to_process.values(), return_when=asyncio.FIRST_COMPLETED)
            to_check = self.get_peers_needing_check()
            if (datetime.datetime.utcnow() - last_flush).seconds > 60:
                log.info("flushing to db")
                await self.flush_to_db()
                last_flush = datetime.datetime.utcnow()
            while not to_check and not to_process:
                port = self.node.listening_port.get_extra_info('socket').getsockname()[1]
                self.node.stop()
                await self.node.start_listening()
                log.info("Idle, sleeping a minute. Port changed to %d", port)
                await asyncio.sleep(60.0)
                to_check = self.get_peers_needing_check()


class SimpleMetrics:
    def __init__(self, port):
        self.prometheus_port = port

    async def handle_metrics_get_request(self, _):
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


def dict_row_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        if col[0] in ('added_on', 'first_online', 'last_seen', 'last_check'):
            d[col[0]] = datetime.datetime.fromisoformat(row[idx]) if row[idx] else None
        else:
            d[col[0]] = row[idx]
    return d


async def test():
    db_path = "/tmp/peers.db" if len(sys.argv) == 1 else sys.argv[-1]
    asyncio.get_event_loop().set_debug(True)
    metrics = SimpleMetrics('8080')
    await metrics.start()
    conf = Config()
    hosting_samples = SDHashSamples("test.sample") if os.path.isfile("test.sample") else None
    crawler = Crawler(db_path, hosting_samples)
    await crawler.open()
    await crawler.flush_to_db()
    await crawler.node.start_listening()
    if crawler.active_peers_count < 100:
        probes = []
        for (host, port) in conf.known_dht_nodes:
            probes.append(asyncio.create_task(crawler.crawl_routing_table(host, port)))
        await asyncio.gather(*probes)
        await crawler.flush_to_db()
    await asyncio.gather(crawler.process(), crawler.probe_files())

if __name__ == '__main__':
    asyncio.run(test())
