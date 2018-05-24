import logging
from twisted.internet import defer
from dht_test_environment import TestKademliaBase

log = logging.getLogger()


class TestPeerExpiration(TestKademliaBase):
    network_size = 40

    @defer.inlineCallbacks
    def test_expire_stale_peers(self):
        removed_addresses = set()
        removed_nodes = []
        self.show_info()

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
                                                       for contact in node.contacts), self.nodes + self._seeds)

        self.assertRaises(AssertionError, self.verify_all_nodes_are_routable)
        self.assertTrue(len(get_nodes_with_stale_contacts()) > 1)

        # run the network for an hour, which should expire the removed nodes
        for _ in range(60):
            log.info("Time is %f, nodes with stale contacts: %i/%i", self.clock.seconds(),
                     len(get_nodes_with_stale_contacts()), len(self.nodes + self._seeds))
            self.pump_clock(60)
        self.assertTrue(len(get_nodes_with_stale_contacts()) == 0)
        self.verify_all_nodes_are_routable()
        self.verify_all_nodes_are_pingable()
