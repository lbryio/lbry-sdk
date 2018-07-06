import logging
from twisted.internet import defer
from lbrynet.dht import constants
from dht_test_environment import TestKademliaBase

log = logging.getLogger()


class TestReJoin(TestKademliaBase):
    network_size = 40

    @defer.inlineCallbacks
    def setUp(self):
        yield super(TestReJoin, self).setUp()
        self.removed_node = self.nodes[20]
        self.nodes.remove(self.removed_node)
        yield self.run_reactor(1, [self.removed_node.stop()])
        self.pump_clock(constants.checkRefreshInterval * 2)
        self.verify_all_nodes_are_routable()
        self.verify_all_nodes_are_pingable()

    @defer.inlineCallbacks
    def test_re_join(self):
        self.nodes.append(self.removed_node)
        yield self.run_reactor(
            31, [self.removed_node.start([(seed_name, 4444) for seed_name in sorted(self.seed_dns.keys())])]
        )
        self.pump_clock(constants.checkRefreshInterval*2)
        self.verify_all_nodes_are_routable()
        self.verify_all_nodes_are_pingable()

    def test_re_join_with_new_ip(self):
        self.removed_node.externalIP = "10.43.43.43"
        return self.test_re_join()

    def test_re_join_with_new_node_id(self):
        self.removed_node.node_id = self.removed_node._generateID()
        return self.test_re_join()
