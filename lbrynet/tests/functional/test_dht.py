import time
import logging
from twisted.trial import unittest
from twisted.internet import defer, threads, task
from lbrynet.dht.node import Node
from lbrynet.tests import mocks
from lbrynet.core.utils import generate_id

log = logging.getLogger("lbrynet.tests.util")
# log.addHandler(logging.StreamHandler())
# log.setLevel(logging.DEBUG)


class TestKademliaBase(unittest.TestCase):
    timeout = 300.0   # timeout for each test
    network_size = 0  # plus lbrynet1, lbrynet2, and lbrynet3 seed nodes
    node_ids = None
    seed_dns = mocks.MOCK_DHT_SEED_DNS

    def _add_next_node(self):
        node_id, node_ip = self.mock_node_generator.next()
        node = Node(node_id=node_id.decode('hex'), udpPort=4444, peerPort=3333, externalIP=node_ip,
                    resolve=mocks.resolve, listenUDP=mocks.listenUDP, callLater=self.clock.callLater, clock=self.clock)
        self.nodes.append(node)
        return node

    @defer.inlineCallbacks
    def add_node(self):
        node = self._add_next_node()
        yield node.joinNetwork(
            [
                ("lbrynet1.lbry.io", self._seeds[0].port),
                ("lbrynet2.lbry.io", self._seeds[1].port),
                ("lbrynet3.lbry.io", self._seeds[2].port),
            ]
        )
        defer.returnValue(node)

    def get_node(self, node_id):
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise KeyError(node_id)

    @defer.inlineCallbacks
    def pop_node(self):
        node = self.nodes.pop()
        yield node.stop()

    def pump_clock(self, n, step=0.01):
        """
        :param n: seconds to run the reactor for
        :param step: reactor tick rate (in seconds)
        """
        for _ in range(n * 100):
            self.clock.advance(step)

    def run_reactor(self, seconds, *deferreds):
        dl = [threads.deferToThread(self.pump_clock, seconds)]
        for d in deferreds:
            dl.append(d)
        return defer.DeferredList(dl)

    @defer.inlineCallbacks
    def setUp(self):
        self.nodes = []
        self._seeds = []
        self.clock = task.Clock()
        self.mock_node_generator = mocks.mock_node_generator(mock_node_ids=self.node_ids)

        join_dl = []
        for seed_dns in self.seed_dns:
            other_seeds = list(self.seed_dns.keys())
            other_seeds.remove(seed_dns)

            self._add_next_node()
            seed = self.nodes.pop()
            self._seeds.append(seed)
            join_dl.append(
                seed.joinNetwork([(other_seed_dns, 4444) for other_seed_dns in other_seeds])
            )

        if self.network_size:
            for _ in range(self.network_size):
                join_dl.append(self.add_node())
        yield self.run_reactor(1, *tuple(join_dl))
        self.verify_all_nodes_are_routable()

    @defer.inlineCallbacks
    def tearDown(self):
        dl = []
        while self.nodes:
            dl.append(self.pop_node())  # stop all of the nodes
        while self._seeds:
            dl.append(self._seeds.pop().stop())  # and the seeds
        yield defer.DeferredList(dl)

    def verify_all_nodes_are_routable(self):
        routable = set()
        node_addresses = {node.externalIP for node in self.nodes}
        node_addresses = node_addresses.union({node.externalIP for node in self._seeds})
        for node in self._seeds:
            contact_addresses = {contact.address for contact in node.contacts}
            routable.update(contact_addresses)
        for node in self.nodes:
            contact_addresses = {contact.address for contact in node.contacts}
            routable.update(contact_addresses)
        self.assertSetEqual(routable, node_addresses)

    @defer.inlineCallbacks
    def verify_all_nodes_are_pingable(self):
        ping_replies = {}
        ping_dl = []
        contacted = set()

        def _ping_cb(result, node, replies):
            replies[node] = result

        for node in self._seeds:
            contact_addresses = set()
            for contact in node.contacts:
                contact_addresses.add(contact.address)
                d = contact.ping()
                d.addCallback(_ping_cb, contact.address, ping_replies)
                contacted.add(contact.address)
                ping_dl.append(d)
        for node in self.nodes:
            contact_addresses = set()
            for contact in node.contacts:
                contact_addresses.add(contact.address)
                d = contact.ping()
                d.addCallback(_ping_cb, contact.address, ping_replies)
                contacted.add(contact.address)
                ping_dl.append(d)
        self.run_reactor(2, *ping_dl)
        yield threads.deferToThread(time.sleep, 0.1)
        node_addresses = {node.externalIP for node in self.nodes}.union({seed.externalIP for seed in self._seeds})
        self.assertSetEqual(node_addresses, contacted)
        self.assertDictEqual(ping_replies, {node: "pong" for node in contacted})


class TestKademliaBootstrap(TestKademliaBase):
    """
    Test initializing the network / connecting the seed nodes
    """

    def test_bootstrap_network(self):  # simulates the real network, which has three seeds
        self.assertEqual(len(self._seeds[0].contacts), 2)
        self.assertEqual(len(self._seeds[1].contacts), 2)
        self.assertEqual(len(self._seeds[2].contacts), 2)

        self.assertSetEqual(
            {self._seeds[0].contacts[0].address, self._seeds[0].contacts[1].address},
            {self._seeds[1].externalIP, self._seeds[2].externalIP}
        )

        self.assertSetEqual(
            {self._seeds[1].contacts[0].address, self._seeds[1].contacts[1].address},
            {self._seeds[0].externalIP, self._seeds[2].externalIP}
        )

        self.assertSetEqual(
            {self._seeds[2].contacts[0].address, self._seeds[2].contacts[1].address},
            {self._seeds[0].externalIP, self._seeds[1].externalIP}
        )

    def test_all_nodes_are_pingable(self):
        return self.verify_all_nodes_are_pingable()


class TestKademliaBootstrapSixteenSeeds(TestKademliaBase):
    node_ids = [
        '000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000',
        '111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111',
        '222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222222',
        '333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333333',
        '444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444444',
        '555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555',
        '666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666666',
        '777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777777',
        '888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888888',
        '999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999',
        'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
        'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
        'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
        'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
        'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
    ]

    @defer.inlineCallbacks
    def setUp(self):
        self.seed_dns.update(
            {
                "lbrynet4.lbry.io": "10.42.42.4",
                "lbrynet5.lbry.io": "10.42.42.5",
                "lbrynet6.lbry.io": "10.42.42.6",
                "lbrynet7.lbry.io": "10.42.42.7",
                "lbrynet8.lbry.io": "10.42.42.8",
                "lbrynet9.lbry.io": "10.42.42.9",
                "lbrynet10.lbry.io": "10.42.42.10",
                "lbrynet11.lbry.io": "10.42.42.11",
                "lbrynet12.lbry.io": "10.42.42.12",
                "lbrynet13.lbry.io": "10.42.42.13",
                "lbrynet14.lbry.io": "10.42.42.14",
                "lbrynet15.lbry.io": "10.42.42.15",
                "lbrynet16.lbry.io": "10.42.42.16",
            }
        )
        yield TestKademliaBase.setUp(self)

    @defer.inlineCallbacks
    def tearDown(self):
        yield TestKademliaBase.tearDown(self)

    def test_bootstrap_network(self):
        pass

    def _test_all_nodes_are_pingable(self):
        return self.verify_all_nodes_are_pingable()


class Test250NodeNetwork(TestKademliaBase):
    network_size = 250

    def test_setup_network_and_verify_connectivity(self):
        pass

    def update_network(self):
        import random
        dl = []
        announced_blobs = []

        for node in self.nodes: # random events
            if random.randint(0, 10000) < 75 and announced_blobs: # get peers for a blob
                log.info('find blob')
                blob_hash = random.choice(announced_blobs)
                dl.append(node.getPeersForBlob(blob_hash))
            if random.randint(0, 10000) < 25: # announce a blob
                log.info('announce blob')
                blob_hash = generate_id()
                announced_blobs.append((blob_hash, node.node_id))
                dl.append(node.announceHaveBlob(blob_hash))

        random.shuffle(self.nodes)

        # kill nodes
        while random.randint(0, 100) > 95:
            dl.append(self.pop_node())
            log.info('pop node')

        # add nodes
        while random.randint(0, 100) > 95:
            dl.append(self.add_node())
            log.info('add node')
        return tuple(dl), announced_blobs

    @defer.inlineCallbacks
    def _test_simulate_network(self):
        total_blobs = []
        for i in range(100):
            d, blobs = self.update_network()
            total_blobs.extend(blobs)
            self.run_reactor(1, *d)
            yield threads.deferToThread(time.sleep, 0.1)
            routable = set()
            node_addresses = {node.externalIP for node in self.nodes}
            for node in self.nodes:
                contact_addresses = {contact.address for contact in node.contacts}
                routable.update(contact_addresses)
            log.warning("difference: %i", len(node_addresses.difference(routable)))
            log.info("blobs %i", len(total_blobs))
            log.info("step %i, %i nodes", i, len(self.nodes))
        self.pump_clock(100)
