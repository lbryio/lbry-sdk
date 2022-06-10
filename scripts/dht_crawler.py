import logging
import asyncio
import time
import typing

import lbry.dht.error
from lbry.dht.constants import generate_id
from lbry.dht.node import Node
from lbry.dht.peer import make_kademlia_peer, PeerManager
from lbry.dht.protocol.distance import Distance
from lbry.extras.daemon.storage import SQLiteStorage
from lbry.conf import Config
from lbry.utils import resolve_host


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-4s %(name)s:%(lineno)d: %(message)s")
log = logging.getLogger(__name__)


def new_node(address="0.0.0.0", udp_port=4444, node_id=None):
    node_id = node_id or generate_id()
    loop = asyncio.get_event_loop()
    return Node(loop, PeerManager(loop), node_id, udp_port, udp_port, 3333, address)


class Crawler:
    def __init__(self):
        self.node = new_node()
        self.crawled = set()
        self.known_peers = set()
        self.unreachable = set()
        self.error = set()
        self.semaphore = asyncio.Semaphore(10)

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
                    self.error.add((host, port))
                    continue
        return []

    async def crawl_routing_table(self, host, port):
        start = time.time()
        log.info("querying %s:%d", host, port)
        self.known_peers.add((host, port))
        self.crawled.add((host, port))
        address = await resolve_host(host, port, 'udp')
        key = self.node.protocol.peer_manager.get_node_id_for_endpoint(address, port)
        if not key:
            for _ in range(3):
                try:
                    async with self.semaphore:
                        await self.node.protocol.get_rpc_peer(make_kademlia_peer(None, address, port)).ping()
                    key = self.node.protocol.peer_manager.get_node_id_for_endpoint(address, port)
                except asyncio.TimeoutError:
                    pass
                except lbry.dht.error.RemoteException:
                    self.error.add((host, port))
            if not key:
                self.unreachable.add((host, port))
                return set()
        node_id = key
        distance = Distance(key)
        max_distance = int.from_bytes(bytes([0xff] * 48), 'big')
        peers = set()
        factor = 2048
        for i in range(200):
            #print(i, len(peers), key.hex(), host)
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
        self.crawled.update(peers)
        return peers

    async def process(self):
        to_process = {}

        def submit(_peer):
            f = asyncio.ensure_future(self.crawl_routing_table(_peer.address, peer.udp_port))
            to_process[_peer] = f
            f.add_done_callback(lambda _: to_process.pop(_peer))

        while to_process or len(self.known_peers) < len(self.crawled):
            log.info("%d known, %d unreachable, %d error.. %d processing",
                     len(self.known_peers), len(self.unreachable), len(self.error), len(to_process))
            for peer in self.crawled.difference(self.known_peers):
                self.known_peers.add(peer)
                submit(peer)
            await asyncio.wait(to_process.values(), return_when=asyncio.FIRST_COMPLETED)


async def test():
    crawler = Crawler()
    await crawler.node.start_listening()
    conf = Config()
    for (host, port) in conf.known_dht_nodes:
        await crawler.crawl_routing_table(host, port)
    await crawler.process()

if __name__ == '__main__':
    asyncio.run(test())
