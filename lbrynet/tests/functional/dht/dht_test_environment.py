import logging
from twisted.trial import unittest
from twisted.internet import defer, task
from lbrynet.dht import constants
from lbrynet.dht.node import Node
from mock_transport import resolve, listenUDP, MOCK_DHT_SEED_DNS, mock_node_generator


log = logging.getLogger(__name__)


class TestKademliaBase(unittest.TestCase):
    timeout = 300.0   # timeout for each test
    network_size = 16  # including seed nodes
    node_ids = None
    seed_dns = MOCK_DHT_SEED_DNS

    def _add_next_node(self):
        node_id, node_ip = self.mock_node_generator.next()
        node = Node(node_id=node_id.decode('hex'), udpPort=4444, peerPort=3333, externalIP=node_ip,
                    resolve=resolve, listenUDP=listenUDP, callLater=self.clock.callLater, clock=self.clock)
        self.nodes.append(node)
        return node

    @defer.inlineCallbacks
    def add_node(self):
        node = self._add_next_node()
        yield node.start([(seed_name, 4444) for seed_name in sorted(self.seed_dns.keys())])
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

    def pump_clock(self, n, step=0.1, tick_callback=None):
        """
        :param n: seconds to run the reactor for
        :param step: reactor tick rate (in seconds)
        """
        for _ in range(int(n * (1.0 / float(step)))):
            self.clock.advance(step)
            if tick_callback and callable(tick_callback):
                tick_callback(self.clock.seconds())

    def run_reactor(self, seconds, deferreds, tick_callback=None):
        d = defer.DeferredList(deferreds)
        self.pump_clock(seconds, tick_callback=tick_callback)
        return d

    def get_contacts(self):
        contacts = {}
        for seed in self._seeds:
            contacts[seed] = seed.contacts
        for node in self._seeds:
            contacts[node] = node.contacts
        return contacts

    def get_routable_addresses(self):
        known = set()
        for n in self._seeds:
            known.update([(c.id, c.address, c.port) for c in n.contacts])
        for n in self.nodes:
            known.update([(c.id, c.address, c.port) for c in n.contacts])
        addresses = {triple[1] for triple in known}
        return addresses

    def get_online_addresses(self):
        online = set()
        for n in self._seeds:
            online.add(n.externalIP)
        for n in self.nodes:
            online.add(n.externalIP)
        return online

    def show_info(self):
        known = set()
        for n in self._seeds:
            known.update([(c.id, c.address, c.port) for c in n.contacts])
        for n in self.nodes:
            known.update([(c.id, c.address, c.port) for c in n.contacts])

        log.info("Routable: %i/%i", len(known), len(self.nodes) + len(self._seeds))
        for n in self._seeds:
            log.info("seed %s has %i contacts in %i buckets", n.externalIP, len(n.contacts),
                     len([b for b in n._routingTable._buckets if b.getContacts()]))
        for n in self.nodes:
            log.info("node %s has %i contacts in %i buckets", n.externalIP, len(n.contacts),
                     len([b for b in n._routingTable._buckets if b.getContacts()]))

    @defer.inlineCallbacks
    def setUp(self):
        self.nodes = []
        self._seeds = []
        self.clock = task.Clock()
        self.mock_node_generator = mock_node_generator(mock_node_ids=self.node_ids)

        seed_dl = []
        seeds = sorted(list(self.seed_dns.keys()))
        known_addresses = [(seed_name, 4444) for seed_name in seeds]
        for seed_dns in seeds:
            self._add_next_node()
            seed = self.nodes.pop()
            self._seeds.append(seed)
            seed_dl.append(
                seed.start(known_addresses)
            )
        yield self.run_reactor(constants.checkRefreshInterval+1, seed_dl)
        while len(self.nodes + self._seeds) < self.network_size:
            network_dl = []
            for i in range(min(10, self.network_size - len(self._seeds) - len(self.nodes))):
                network_dl.append(self.add_node())
            yield self.run_reactor(constants.checkRefreshInterval*2+1, network_dl)
        self.assertEqual(len(self.nodes + self._seeds), self.network_size)
        self.pump_clock(3600)
        self.verify_all_nodes_are_routable()
        self.verify_all_nodes_are_pingable()

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
        yield self.run_reactor(2, ping_dl)
        node_addresses = {node.externalIP for node in self.nodes}.union({seed.externalIP for seed in self._seeds})
        self.assertSetEqual(node_addresses, contacted)
        expected = {node: "pong" for node in contacted}
        self.assertDictEqual(ping_replies, expected)
