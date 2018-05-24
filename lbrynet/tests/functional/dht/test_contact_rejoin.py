import logging
from twisted.internet import defer
from dht_test_environment import TestKademliaBase

log = logging.getLogger()


class TestReJoin(TestKademliaBase):
    network_size = 40

    @defer.inlineCallbacks
    def test_re_join(self):

        removed_node = self.nodes[0]
        self.nodes.remove(removed_node)
        yield self.run_reactor(1, [removed_node.stop()])

        # run the network for an hour, which should expire the removed node
        self.pump_clock(3600)
        self.verify_all_nodes_are_routable()
        self.verify_all_nodes_are_pingable()
        self.nodes.append(removed_node)
        yield self.run_reactor(
            31, [removed_node.start([(seed_name, 4444) for seed_name in sorted(self.seed_dns.keys())])]
        )
        self.pump_clock(901)
        self.verify_all_nodes_are_routable()
        self.verify_all_nodes_are_pingable()

    @defer.inlineCallbacks
    def test_re_join_with_new_ip(self):

        removed_node = self.nodes[0]
        self.nodes.remove(removed_node)
        yield self.run_reactor(1, [removed_node.stop()])

        # run the network for an hour, which should expire the removed node
        for _ in range(60):
            self.pump_clock(60)
        self.verify_all_nodes_are_routable()
        self.verify_all_nodes_are_pingable()
        removed_node.externalIP = "10.43.43.43"
        self.nodes.append(removed_node)
        yield self.run_reactor(
            31, [removed_node.start([(seed_name, 4444) for seed_name in sorted(self.seed_dns.keys())])]
        )
        self.pump_clock(901)
        self.verify_all_nodes_are_routable()
        self.verify_all_nodes_are_pingable()

    @defer.inlineCallbacks
    def test_re_join_with_new_node_id(self):

        removed_node = self.nodes[0]
        self.nodes.remove(removed_node)
        yield self.run_reactor(1, [removed_node.stop()])

        # run the network for an hour, which should expire the removed node
        for _ in range(60):
            self.pump_clock(60)
        self.verify_all_nodes_are_routable()
        self.verify_all_nodes_are_pingable()
        removed_node.node_id = removed_node._generateID()
        self.nodes.append(removed_node)
        yield self.run_reactor(
            31, [removed_node.start([(seed_name, 4444) for seed_name in sorted(self.seed_dns.keys())])]
        )
        self.pump_clock(901)
        self.verify_all_nodes_are_routable()
        self.verify_all_nodes_are_pingable()
