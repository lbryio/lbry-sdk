import asyncio
from torba.testcase import AsyncioTestCase
from tests import dht_mocks
from lbrynet.dht import constants
from lbrynet.dht.node import Node
from lbrynet.peer import PeerManager


class TestRouting(AsyncioTestCase):
    async def test_fill_one_bucket(self):
        loop = asyncio.get_event_loop()
        peer_addresses = [
            (constants.generate_id(1), '1.2.3.1'),
            (constants.generate_id(2), '1.2.3.2'),
            (constants.generate_id(3), '1.2.3.3'),
            (constants.generate_id(4), '1.2.3.4'),
            (constants.generate_id(5), '1.2.3.5'),
            (constants.generate_id(6), '1.2.3.6'),
            (constants.generate_id(7), '1.2.3.7'),
            (constants.generate_id(8), '1.2.3.8'),
            (constants.generate_id(9), '1.2.3.9'),
        ]
        with dht_mocks.mock_network_loop(loop):
            nodes = {
                i: Node(PeerManager(loop), loop, node_id, 4444, 4444, 3333, address)
                for i, (node_id, address) in enumerate(peer_addresses)
            }
            node_1 = nodes[0]
            contact_cnt = 0
            for i in range(1, len(peer_addresses)):
                self.assertEqual(len(node_1.protocol.routing_table.get_peers()), contact_cnt)
                node = nodes[i]
                peer = node_1.protocol.peer_manager.make_peer(
                    node.protocol.external_ip, node_id=node.protocol.node_id,
                    udp_port=node.protocol.udp_port
                )
                added = await node_1.protocol.routing_table.add_peer(peer)
                self.assertEqual(True, added)
                contact_cnt += 1

            self.assertEqual(len(node_1.protocol.routing_table.get_peers()), 8)
            self.assertEqual(node_1.protocol.routing_table.buckets_with_contacts(), 1)
            for node in nodes.values():
                node.protocol.stop()


# from binascii import hexlify, unhexlify
#
# from twisted.trial import unittest
# from twisted.internet import defer
# from lbrynet.dht import constants
# from lbrynet.dht.routingtable import TreeRoutingTable
# from lbrynet.dht.contact import ContactManager
# from lbrynet.dht.distance import Distance
# from lbrynet.utils import generate_id
#
#
# class FakeRPCProtocol:
#     """ Fake RPC protocol; allows lbrynet.dht.contact.Contact objects to "send" RPCs """
#     def sendRPC(self, *args, **kwargs):
#         return defer.succeed(None)
#
#
# class TreeRoutingTableTest(unittest.TestCase):
#     """ Test case for the RoutingTable class """
#     def setUp(self):
#         self.contact_manager = ContactManager()
#         self.nodeID = generate_id(b'node1')
#         self.protocol = FakeRPCProtocol()
#         self.routingTable = TreeRoutingTable(self.nodeID)
#
#     def test_distance(self):
#         """ Test to see if distance method returns correct result"""
#         d = Distance(bytes((170,) * 48))
#         result = d(bytes((85,) * 48))
#         expected = int(hexlify(bytes((255,) * 48)), 16)
#         self.assertEqual(result, expected)
#
#     @defer.inlineCallbacks
#     def test_add_contact(self):
#         """ Tests if a contact can be added and retrieved correctly """
#         # Create the contact
#         contact_id = generate_id(b'node2')
#         contact = self.contact_manager.make_contact(contact_id, '127.0.0.1', 9182, self.protocol)
#         # Now add it...
#         yield self.routingTable.addContact(contact)
#         # ...and request the closest nodes to it (will retrieve it)
#         closest_nodes = self.routingTable.findCloseNodes(contact_id)
#         self.assertEqual(len(closest_nodes), 1)
#         self.assertIn(contact, closest_nodes)
#
#     @defer.inlineCallbacks
#     def test_get_contact(self):
#         """ Tests if a specific existing contact can be retrieved correctly """
#         contact_id = generate_id(b'node2')
#         contact = self.contact_manager.make_contact(contact_id, '127.0.0.1', 9182, self.protocol)
#         # Now add it...
#         yield self.routingTable.addContact(contact)
#         # ...and get it again
#         same_contact = self.routingTable.getContact(contact_id)
#         self.assertEqual(contact, same_contact, 'getContact() should return the same contact')
#
#     @defer.inlineCallbacks
#     def test_add_parent_node_as_contact(self):
#         """
#         Tests the routing table's behaviour when attempting to add its parent node as a contact
#         """
#         # Create a contact with the same ID as the local node's ID
#         contact = self.contact_manager.make_contact(self.nodeID, '127.0.0.1', 9182, self.protocol)
#         # Now try to add it
#         yield self.routingTable.addContact(contact)
#         # ...and request the closest nodes to it using FIND_NODE
#         closest_nodes = self.routingTable.findCloseNodes(self.nodeID, constants.k)
#         self.assertNotIn(contact, closest_nodes, 'Node added itself as a contact')
#
#     @defer.inlineCallbacks
#     def test_remove_contact(self):
#         """ Tests contact removal """
#         # Create the contact
#         contact_id = generate_id(b'node2')
#         contact = self.contact_manager.make_contact(contact_id, '127.0.0.1', 9182, self.protocol)
#         # Now add it...
#         yield self.routingTable.addContact(contact)
#         # Verify addition
#         self.assertEqual(len(self.routingTable._buckets[0]), 1, 'Contact not added properly')
#         # Now remove it
#         self.routingTable.removeContact(contact)
#         self.assertEqual(len(self.routingTable._buckets[0]), 0, 'Contact not removed properly')
#
#     @defer.inlineCallbacks
#     def test_split_bucket(self):
#         """ Tests if the the routing table correctly dynamically splits k-buckets """
#         self.assertEqual(self.routingTable._buckets[0].rangeMax, 2**384,
#                              'Initial k-bucket range should be 0 <= range < 2**384')
#         # Add k contacts
#         for i in range(constants.k):
#             node_id = generate_id(b'remote node %d' % i)
#             contact = self.contact_manager.make_contact(node_id, '127.0.0.1', 9182, self.protocol)
#             yield self.routingTable.addContact(contact)
#
#         self.assertEqual(len(self.routingTable._buckets), 1,
#                              'Only k nodes have been added; the first k-bucket should now '
#                              'be full, but should not yet be split')
#         # Now add 1 more contact
#         node_id = generate_id(b'yet another remote node')
#         contact = self.contact_manager.make_contact(node_id, '127.0.0.1', 9182, self.protocol)
#         yield self.routingTable.addContact(contact)
#         self.assertEqual(len(self.routingTable._buckets), 2,
#                              'k+1 nodes have been added; the first k-bucket should have been '
#                              'split into two new buckets')
#         self.assertNotEqual(self.routingTable._buckets[0].rangeMax, 2**384,
#                          'K-bucket was split, but its range was not properly adjusted')
#         self.assertEqual(self.routingTable._buckets[1].rangeMax, 2**384,
#                              'K-bucket was split, but the second (new) bucket\'s '
#                              'max range was not set properly')
#         self.assertEqual(self.routingTable._buckets[0].rangeMax,
#                              self.routingTable._buckets[1].rangeMin,
#                              'K-bucket was split, but the min/max ranges were '
#                              'not divided properly')
#
#     @defer.inlineCallbacks
#     def test_full_split(self):
#         """
#         Test that a bucket is not split if it is full, but the new contact is not closer than the kth closest contact
#         """
#
#         self.routingTable._parentNodeID = bytes(48 * b'\xff')
#
#         node_ids = [
#             b"100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
#             b"200000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
#             b"300000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
#             b"400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
#             b"500000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
#             b"600000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
#             b"700000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
#             b"800000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
#             b"ff0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
#             b"010000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
#         ]
#
#         # Add k contacts
#         for nodeID in node_ids:
#             # self.assertEquals(nodeID, node_ids[i].decode('hex'))
#             contact = self.contact_manager.make_contact(unhexlify(nodeID), '127.0.0.1', 9182, self.protocol)
#             yield self.routingTable.addContact(contact)
#         self.assertEqual(len(self.routingTable._buckets), 2)
#         self.assertEqual(len(self.routingTable._buckets[0]._contacts), 8)
#         self.assertEqual(len(self.routingTable._buckets[1]._contacts), 2)
#
#         #  try adding a contact who is further from us than the k'th known contact
#         nodeID = b'020000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
#         nodeID = unhexlify(nodeID)
#         contact = self.contact_manager.make_contact(nodeID, '127.0.0.1', 9182, self.protocol)
#         self.assertFalse(self.routingTable._shouldSplit(self.routingTable._kbucketIndex(contact.id), contact.id))
#         yield self.routingTable.addContact(contact)
#         self.assertEqual(len(self.routingTable._buckets), 2)
#         self.assertEqual(len(self.routingTable._buckets[0]._contacts), 8)
#         self.assertEqual(len(self.routingTable._buckets[1]._contacts), 2)
#         self.assertNotIn(contact, self.routingTable._buckets[0]._contacts)
#         self.assertNotIn(contact, self.routingTable._buckets[1]._contacts)
#

# class KeyErrorFixedTest(unittest.TestCase):
#     """ Basic tests case for boolean operators on the Contact class """
#
#     def setUp(self):
#         own_id = (2 ** constants.key_bits) - 1
#         # carefully chosen own_id. here's the logic
#         # we want a bunch of buckets (k+1, to be exact), and we want to make sure own_id
#         # is not in bucket 0. so we put own_id at the end so we can keep splitting by adding to the
#         # end
#
#         self.table = lbrynet.dht.routingtable.OptimizedTreeRoutingTable(own_id)
#
#     def fill_bucket(self, bucket_min):
#         bucket_size = lbrynet.dht.constants.k
#         for i in range(bucket_min, bucket_min + bucket_size):
#             self.table.addContact(lbrynet.dht.contact.Contact(long(i), '127.0.0.1', 9999, None))
#
#     def overflow_bucket(self, bucket_min):
#         bucket_size = lbrynet.dht.constants.k
#         self.fill_bucket(bucket_min)
#         self.table.addContact(
#             lbrynet.dht.contact.Contact(long(bucket_min + bucket_size + 1),
#                                         '127.0.0.1', 9999, None))
#
#     def testKeyError(self):
#
#         # find middle, so we know where bucket will split
#         bucket_middle = self.table._buckets[0].rangeMax / 2
#
#         # fill last bucket
#         self.fill_bucket(self.table._buckets[0].rangeMax - lbrynet.dht.constants.k - 1)
#         # -1 in previous line because own_id is in last bucket
#
#         # fill/overflow 7 more buckets
#         bucket_start = 0
#         for i in range(0, lbrynet.dht.constants.k):
#             self.overflow_bucket(bucket_start)
#             bucket_start += bucket_middle / (2 ** i)
#
#         # replacement cache now has k-1 entries.
#         # adding one more contact to bucket 0 used to cause a KeyError, but it should work
#         self.table.addContact(
#             lbrynet.dht.contact.Contact(long(lbrynet.dht.constants.k + 2), '127.0.0.1', 9999, None))
#
#         # import math
#         # print ""
#         # for i, bucket in enumerate(self.table._buckets):
#         #     print "Bucket " + str(i) + " (2 ** " + str(
#         #         math.log(bucket.rangeMin, 2) if bucket.rangeMin > 0 else 0) + " <= x < 2 ** "+str(
#         #         math.log(bucket.rangeMax, 2)) + ")"
#         #     for c in bucket.getContacts():
#         #         print "  contact " + str(c.id)
#         # for key, bucket in self.table._replacementCache.items():
#         #     print "Replacement Cache for Bucket " + str(key)
#         #     for c in bucket:
#         #         print "  contact " + str(c.id)
