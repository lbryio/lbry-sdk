import datetime
import logging
import asyncio
import time
import typing

from aiohttp import web
from prometheus_client import Gauge, Counter, generate_latest as prom_generate_latest

import lbry.dht.error
from lbry.dht.constants import generate_id
from lbry.dht.node import Node
from lbry.dht.peer import make_kademlia_peer, PeerManager
from lbry.dht.protocol.distance import Distance
from lbry.extras.daemon.storage import SQLiteMixin
from lbry.conf import Config
from lbry.utils import resolve_host


from sqlalchemy.orm import declarative_base, relationship
import sqlalchemy as sqla


@sqla.event.listens_for(sqla.engine.Engine, "connect")
def set_sqlite_pragma(dbapi_connection, _):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-4s %(name)s:%(lineno)d: %(message)s")
log = logging.getLogger(__name__)
Base = declarative_base()


class DHTPeer(Base):
    __tablename__ = "peer"
    peer_id = sqla.Column(sqla.Integer(), sqla.Identity(), primary_key=True)
    node_id = sqla.Column(sqla.String(96))
    address = sqla.Column(sqla.String())
    udp_port = sqla.Column(sqla.Integer())
    tcp_port = sqla.Column(sqla.Integer())
    first_online = sqla.Column(sqla.DateTime())
    errors = sqla.Column(sqla.Integer(), default=0)
    last_churn = sqla.Column(sqla.Integer())
    added_on = sqla.Column(sqla.DateTime(), nullable=False, default=datetime.datetime.utcnow)
    last_check = sqla.Column(sqla.DateTime())
    last_seen = sqla.Column(sqla.DateTime())
    latency = sqla.Column(sqla.Integer())
    endpoint_unique = sqla.UniqueConstraint("node_id", "udp_port")

    @classmethod
    def from_kad_peer(cls, peer):
        node_id = peer.node_id.hex() if peer.node_id else None
        return DHTPeer(node_id=node_id, address=peer.address, udp_port=peer.udp_port, tcp_port=peer.tcp_port)

    def to_kad_peer(self):
        node_id = bytes.fromhex(self.node_id) if self.node_id else None
        return make_kademlia_peer(node_id, self.address, self.udp_port, self.tcp_port)


class DHTConnection(Base):
    __tablename__ = "connection"
    from_peer_id = sqla.Column(sqla.Integer(), sqla.ForeignKey("peer.peer_id"), primary_key=True)
    connected_by = relationship("DHTPeer", backref="known_by", primaryjoin=(DHTPeer.peer_id == from_peer_id))
    to_peer_id = sqla.Column(sqla.Integer(), sqla.ForeignKey("peer.peer_id"), primary_key=True)
    connected_to = relationship("DHTPeer", backref="connections", primaryjoin=(DHTPeer.peer_id == to_peer_id))


def new_node(address="0.0.0.0", udp_port=4444, node_id=None):
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
    def __init__(self, db_path: str):
        self.node = new_node()
        self.semaphore = asyncio.Semaphore(200)
        engine = sqla.create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)
        session = sqla.orm.sessionmaker(engine, autocommit=False, autoflush=False, expire_on_commit=False)
        self.db = session()
        self._memory_peers = {
            (peer.address, peer.udp_port): peer for peer in self.db.query(DHTPeer).all()
        }

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

    def add_peers(self, *peers):
        db_peers = []
        for peer in peers:
            db_peer = self.get_from_peer(peer)
            if db_peer and db_peer.node_id is None and peer.node_id:
                db_peer.node_id = peer.node_id.hex()
            elif not db_peer:
                db_peer = DHTPeer.from_kad_peer(peer)
                self._memory_peers[(peer.address, peer.udp_port)] = db_peer
            db_peer.last_seen = datetime.datetime.utcnow()
            db_peers.append(db_peer)

    def flush_to_db(self):
        self.db.add_all(self._memory_peers.values())
        self.db.commit()

    def get_from_peer(self, peer):
        return self._memory_peers.get((peer.address, peer.udp_port), None)

    def set_latency(self, peer, latency=None):
        if latency:
            self.host_latency_metric.labels(host=peer.address, port=peer.udp_port).set(latency)
        db_peer = self.get_from_peer(peer)
        db_peer.latency = latency
        if not db_peer.node_id and peer.node_id:
            db_peer.node_id = peer.node_id.hex()
        if db_peer.first_online and latency is None:
            db_peer.last_churn = (datetime.datetime.utcnow() - db_peer.first_online).seconds
        elif latency is not None and db_peer.first_online is None:
            db_peer.first_online = datetime.datetime.utcnow()
        db_peer.last_check = datetime.datetime.utcnow()

    def inc_errors(self, peer):
        db_peer = self.get_from_peer(peer)
        db_peer.errors = (db_peer.errors or 0) + 1

    def associate_peers(self, target_peer_id, db_peer_ids):
        return # todo

    async def request_peers(self, host, port, key) -> typing.List['KademliaPeer']:
        async with self.semaphore:
            peer = make_kademlia_peer(None, await resolve_host(host, port, 'udp'), port)
            for attempt in range(3):
                try:
                    req_start = time.perf_counter_ns()
                    response = await self.node.protocol.get_rpc_peer(peer).find_node(key)
                    latency = time.perf_counter_ns() - req_start
                    self.set_latency(make_kademlia_peer(key, host, port), latency)
                    return [make_kademlia_peer(*peer_tuple) for peer_tuple in response]
                except asyncio.TimeoutError:
                    self.set_latency(make_kademlia_peer(key, host, port), None)
                    continue
                except lbry.dht.error.RemoteException as e:
                    log.info('Peer errored: %s:%d attempt #%d - %s',
                             host, port, (attempt + 1), str(e))
                    self.inc_errors(peer)
                    self.set_latency(make_kademlia_peer(key, host, port), None)
                    continue
        return []

    async def crawl_routing_table(self, host, port, node_id=None):
        start = time.time()
        log.info("querying %s:%d", host, port)
        address = await resolve_host(host, port, 'udp')
        self.add_peers(make_kademlia_peer(None, address, port))
        key = node_id or self.node.protocol.peer_manager.get_node_id_for_endpoint(address, port)
        if not key:
            latency = None
            for _ in range(3):
                try:
                    ping_start = time.perf_counter_ns()
                    async with self.semaphore:
                        await self.node.protocol.get_rpc_peer(make_kademlia_peer(None, address, port)).ping()
                        key = key or self.node.protocol.peer_manager.get_node_id_for_endpoint(address, port)
                    latency = time.perf_counter_ns() - ping_start
                    break
                except asyncio.TimeoutError:
                    pass
                except lbry.dht.error.RemoteException:
                    self.inc_errors(make_kademlia_peer(None, address, port))
                    pass
            self.set_latency(make_kademlia_peer(key, address, port), latency if key else None)
            if not latency or not key:
                if latency and not key:
                    log.warning("No node id from %s:%d", host, port)
                return set()
        node_id = key
        distance = Distance(key)
        max_distance = int.from_bytes(bytes([0xff] * 48), 'big')
        peers = set()
        factor = 2048
        for i in range(200):
            new_peers = await self.request_peers(address, port, key)
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
                    key = int.from_bytes(node_id, 'big') ^ next_jump
                    if key.bit_length() > 384:
                        break
                    key = key.to_bytes(48, 'big')
                else:
                    break
            else:
                key = far_key
                factor = 2048
        log.info("Done querying %s:%d in %.2f seconds: %d peers found over %d requests.",
                 host, port, (time.time() - start), len(peers), i)
        self.add_peers(*peers)
        self.connections_found_metric.labels(host=host, port=port).set(len(peers))
        #self.associate_peers(this_peer_id, db_peer_ids)
        self.db.commit()
        return peers

    async def process(self):
        to_process = {}

        def submit(_peer):
            f = asyncio.ensure_future(
                self.crawl_routing_table(_peer.address, peer.udp_port, bytes.fromhex(peer.node_id)))
            to_process[_peer] = f
            f.add_done_callback(lambda _: to_process.pop(_peer))

        to_check = self.get_peers_needing_check()
        last_flush = datetime.datetime.utcnow()
        while True:
            for peer in to_check:
                if peer not in to_process:
                    submit(peer)
                    await asyncio.sleep(.1)
                if len(to_process) > 100:
                    break
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
                self.flush_to_db()
                last_flush = datetime.datetime.utcnow()
            while not to_check and not to_process:
                log.info("Idle, sleeping a minute.")
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


async def test():
    metrics = SimpleMetrics('7070')
    await metrics.start()
    crawler = Crawler("/tmp/a.db")
    await crawler.node.start_listening()
    conf = Config()
    if crawler.active_peers_count < 100:
        for (host, port) in conf.known_dht_nodes:
            await crawler.crawl_routing_table(host, port)
    await crawler.process()

if __name__ == '__main__':
    asyncio.run(test())
