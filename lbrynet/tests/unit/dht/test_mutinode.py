#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive


from twisted.trial import unittest
from twisted.internet import defer
import lbrynet.dht.node
import lbrynet.dht.constants
import lbrynet.dht.datastore
from lbrynet.tests.util import random_lbry_hash

class MultiNodeTest(unittest.TestCase):
    """ Setup some nodes on localhost and have them talk to each other """

    def _setup_node(self):
        node = lbrynet.dht.node.Node(udpPort=self.cur_udp_port,
            externalIP='127.0.0.1', peerPort=self.peer_port)
        self.cur_udp_port += 1
        return node

    def setUp(self):
        self.nodes = []
        self.num_nodes = 2
        self.peer_port = 4444
        self.cur_udp_port = 12333
        self.known_nodes = set()
        for i in range(0, self.num_nodes):
            self.known_nodes.add(('127.0.0.1', self.cur_udp_port))
            node = self._setup_node()
            self.nodes.append(node)

    def tearDown(self):
        for n in self.nodes:
            n.stop()
            del n

    @defer.inlineCallbacks
    def testAnnounceBlob(self):
        for n in self.nodes:
            # remove itself from known nodes
            known_nodes = self.known_nodes.difference(set([('127.0.0.1', n.port)]))
            out = yield n.joinNetwork(known_nodes)

        bh = random_lbry_hash()
        out = yield self.nodes[0].announceHaveBlob(bh)

