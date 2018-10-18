from lbrynet.dht import constants
from lbrynet.dht.distance import Distance
import logging

from tests.functional.dht.dht_test_environment import TestKademliaBase

log = logging.getLogger()


class TestFindNode(TestKademliaBase):
    """
    This tests the local routing table lookup for a node, every node should return the sorted k contacts closest
    to the querying node (even if the key being looked up is known)
    """
    network_size = 35

    def test_find_node(self):
        last_node_id = self.nodes[-1].node_id
        to_last_node = Distance(last_node_id)
        for n in self.nodes:
            find_close_nodes_result = n._routingTable.findCloseNodes(last_node_id, constants.k)
            self.assertEqual(len(find_close_nodes_result), constants.k)
            found_ids = [c.id for c in find_close_nodes_result]
            self.assertListEqual(found_ids, sorted(found_ids, key=lambda x: to_last_node(x)))
            if last_node_id in [c.id for c in n.contacts]:
                self.assertEqual(found_ids[0], last_node_id)
            else:
                self.assertNotIn(last_node_id, found_ids)
