import logging
from twisted.internet import defer
from lbrynet.dht import constants
from dht_test_environment import TestKademliaBase

log = logging.getLogger()


class TestPeerExpiration(TestKademliaBase):
    network_size = 40

    @defer.inlineCallbacks
    def test_expire_stale_peers(self):
        removed_addresses = set()
        removed_nodes = []

        # stop 5 nodes
        for _ in range(5):
            n = self.nodes[0]
            removed_nodes.append(n)
            removed_addresses.add(n.externalIP)
            self.nodes.remove(n)
            yield self.run_reactor(1, [n.stop()])

        offline_addresses = self.get_routable_addresses().difference(self.get_online_addresses())
        self.assertSetEqual(offline_addresses, removed_addresses)

        get_nodes_with_stale_contacts = lambda: filter(lambda node: any(contact.address in offline_addresses
                                                                        for contact in node.contacts),
                                                       self.nodes + self._seeds)

        self.assertRaises(AssertionError, self.verify_all_nodes_are_routable)
        self.assertTrue(len(get_nodes_with_stale_contacts()) > 1)

        # run the network long enough for two failures to happen
        self.pump_clock(constants.checkRefreshInterval * 3)

        self.assertEquals(len(get_nodes_with_stale_contacts()), 0)
        self.verify_all_nodes_are_routable()
        self.verify_all_nodes_are_pingable()
