import datetime
import logging
import asyncio
import time
import typing

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
        return DHTPeer(node_id=peer.node_id, address=peer.address, udp_port=peer.udp_port, tcp_port=peer.tcp_port)

    def to_kad_peer(self):
        return make_kademlia_peer(self.node_id, self.address, self.udp_port, self.tcp_port)


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
    def __init__(self, db_path: str):
        self.node = new_node()
        self.semaphore = asyncio.Semaphore(20)
        engine = sqla.create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)
        session = sqla.orm.sessionmaker(engine, autocommit=False, autoflush=False, expire_on_commit=False)
        self.db = session()

    @property
    def refresh_limit(self):
        return datetime.datetime.utcnow() - datetime.timedelta(hours=1)

    @property
    def active_peers_query(self):
        return self.db.query(DHTPeer).filter(sqla.or_(DHTPeer.last_seen > self.refresh_limit, DHTPeer.latency > 0))

    @property
    def all_peers(self):
        return set([peer.to_kad_peer() for peer in self.active_peers_query.all()])

    @property
    def checked_peers_count(self):
        return self.active_peers_query.filter(DHTPeer.last_check > self.refresh_limit).count()

    @property
    def unreachable_peers_count(self):
        return self.active_peers_query.filter(DHTPeer.latency == None, DHTPeer.last_check > self.refresh_limit).count()

    @property
    def peers_with_errors_count(self):
        return self.active_peers_query.filter(DHTPeer.errors > 0).count()

    def get_peers_needing_check(self):
        return set([peer.to_kad_peer() for peer in self.active_peers_query.filter(
            sqla.or_(DHTPeer.last_check == None,
                     DHTPeer.last_check < self.refresh_limit)).order_by(DHTPeer.last_seen.desc()).all()])

    def add_peers(self, *peers):
        db_peers = []
        for peer in peers:
            db_peer = self.get_from_peer(peer)
            if db_peer and db_peer.node_id is None and peer.node_id:
                db_peer.node_id = peer.node_id
            elif not db_peer:
                db_peer = DHTPeer.from_kad_peer(peer)
            self.db.add(db_peer)
            db_peers.append(db_peer)
        self.db.flush()
        return [dbp.peer_id for dbp in db_peers]

    def get_from_peer(self, peer):
        return self.db.query(DHTPeer).filter(DHTPeer.address==peer.address, DHTPeer.udp_port==peer.udp_port).first()

    def set_latency(self, peer, latency=None):
        db_peer = self.get_from_peer(peer)
        db_peer.latency = latency
        if not db_peer.node_id:
            db_peer.node_id = peer.node_id
        if db_peer.first_online and latency is None:
            db_peer.last_churn = (datetime.datetime.utcnow() - db_peer.first_online).seconds
        elif latency is not None and db_peer.first_online is None:
            db_peer.first_online = datetime.datetime.utcnow()
        db_peer.last_check = datetime.datetime.utcnow()
        self.db.add(db_peer)

    def inc_errors(self, peer):
        db_peer = self.get_from_peer(peer)
        db_peer.errors += 1
        self.db.add(db_peer)

    def count_peers(self):
        return self.db.query(DHTPeer).count()

    def associate_peers(self, target_peer_id, db_peer_ids):
        connections = {
            DHTConnection(
                from_peer_id=target_peer_id,
                to_peer_id=peer_id)
            for peer_id in db_peer_ids
        }
        self.db.query(DHTPeer).filter(DHTPeer.peer_id.in_(set(db_peer_ids))).update(
            {DHTPeer.last_seen: datetime.datetime.utcnow()})
        self.db.query(DHTConnection).filter(DHTConnection.from_peer_id == target_peer_id).delete()
        self.db.add_all(connections)

    async def request_peers(self, host, port, key) -> typing.List['KademliaPeer']:
        async with self.semaphore:
            peer = make_kademlia_peer(None, await resolve_host(host, port, 'udp'), port)
            for attempt in range(3):
                try:
                    response = await self.node.protocol.get_rpc_peer(peer).find_node(key)
                    return [make_kademlia_peer(*peer_tuple) for peer_tuple in response]
                except asyncio.TimeoutError:
                    log.info('Previously responding peer timed out: %s:%d attempt #%d', host, port, (attempt + 1))
                    continue
                except lbry.dht.error.RemoteException as e:
                    log.info('Previously responding peer errored: %s:%d attempt #%d - %s',
                             host, port, (attempt + 1), str(e))
                    self.inc_errors(peer)
                    continue
        return []

    async def crawl_routing_table(self, host, port):
        start = time.time()
        log.info("querying %s:%d", host, port)
        address = await resolve_host(host, port, 'udp')
        this_peer_id, = self.add_peers(make_kademlia_peer(None, address, port))
        key = self.node.protocol.peer_manager.get_node_id_for_endpoint(address, port)
        latency = None
        for _ in range(3):
            try:
                ping_start = time.perf_counter_ns()
                async with self.semaphore:
                    await self.node.protocol.get_rpc_peer(make_kademlia_peer(None, address, port)).ping()
                    key = key or self.node.protocol.peer_manager.get_node_id_for_endpoint(address, port)
                latency = time.perf_counter_ns() - ping_start
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
        db_peer_ids = self.add_peers(*peers)
        self.associate_peers(this_peer_id, db_peer_ids)
        self.db.commit()
        return peers

    async def process(self):
        to_process = {}

        def submit(_peer):
            f = asyncio.ensure_future(self.crawl_routing_table(_peer.address, peer.udp_port))
            to_process[_peer] = f
            f.add_done_callback(lambda _: to_process.pop(_peer))

        to_check = self.get_peers_needing_check()
        while True:
            for peer in to_check:
                if peer not in to_process:
                    submit(peer)
                if len(to_process) > 20:
                    break
            await asyncio.sleep(0)
            log.info("%d known, %d contacted recently, %d unreachable, %d error, %d processing, %d on queue",
                     self.active_peers_query.count(), self.checked_peers_count, self.unreachable_peers_count,
                     self.peers_with_errors_count, len(to_process), len(to_check))
            if to_process:
                await asyncio.wait(to_process.values(), return_when=asyncio.FIRST_COMPLETED)
            to_check = self.get_peers_needing_check()
            while not to_check and not to_process:
                log.info("Idle, sleeping a minute.")
                await asyncio.sleep(60.0)
                to_check = self.get_peers_needing_check()


async def test():
    crawler = Crawler("/tmp/a.db")
    await crawler.node.start_listening()
    conf = Config()
    if crawler.active_peers_query.count() < 100:
        for (host, port) in conf.known_dht_nodes:
            await crawler.crawl_routing_table(host, port)
    await crawler.process()

if __name__ == '__main__':
    asyncio.run(test())
