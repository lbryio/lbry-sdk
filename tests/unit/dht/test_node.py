import hashlib
import struct

from twisted.trial import unittest
from twisted.internet import defer
from lbrynet.dht.node import Node
from lbrynet.dht import constants
from lbrynet.core.utils import generate_id


class NodeIDTest(unittest.TestCase):

    def setUp(self):
        self.node = Node()

    def test_new_node_has_auto_created_id(self):
        self.assertEqual(type(self.node.node_id), bytes)
        self.assertEqual(len(self.node.node_id), 48)

    def test_uniqueness_and_length_of_generated_ids(self):
        previous_ids = []
        for i in range(100):
            new_id = self.node._generateID()
            self.assertNotIn(new_id, previous_ids, 'id at index {} not unique'.format(i))
            self.assertEqual(len(new_id), 48, 'id at index {} wrong length: {}'.format(i, len(new_id)))
            previous_ids.append(new_id)


class NodeDataTest(unittest.TestCase):
    """ Test case for the Node class's data-related functions """

    def setUp(self):
        h = hashlib.sha384()
        h.update(b'test')
        self.node = Node()
        self.contact = self.node.contact_manager.make_contact(
            h.digest(), '127.0.0.1', 12345, self.node._protocol)
        self.token = self.node.make_token(self.contact.compact_ip())
        self.cases = []
        for i in range(5):
            h.update(str(i).encode())
            self.cases.append((h.digest(), 5000+2*i))
            self.cases.append((h.digest(), 5001+2*i))

    @defer.inlineCallbacks
    def test_store(self):
        """ Tests if the node can store (and privately retrieve) some data """
        for key, port in self.cases:
            yield self.node.store(
                self.contact, key, self.token, port, self.contact.id, 0
            )
        for key, value in self.cases:
            expected_result = self.contact.compact_ip() + struct.pack('>H', value) + self.contact.id
            self.assertTrue(self.node._dataStore.hasPeersForBlob(key),
                            "Stored key not found in node's DataStore: '%s'" % key)
            self.assertTrue(expected_result in self.node._dataStore.getPeersForBlob(key),
                            "Stored val not found in node's DataStore: key:'%s' port:'%s' %s"
                            % (key, value, self.node._dataStore.getPeersForBlob(key)))


class NodeContactTest(unittest.TestCase):
    """ Test case for the Node class's contact management-related functions """
    def setUp(self):
        self.node = Node()

    @defer.inlineCallbacks
    def test_add_contact(self):
        """ Tests if a contact can be added and retrieved correctly """
        # Create the contact
        contact_id = generate_id(b'node1')
        contact = self.node.contact_manager.make_contact(contact_id, '127.0.0.1', 9182, self.node._protocol)
        # Now add it...
        yield self.node.addContact(contact)
        # ...and request the closest nodes to it using FIND_NODE
        closest_nodes = self.node._routingTable.findCloseNodes(contact_id, constants.k)
        self.assertEqual(len(closest_nodes), 1)
        self.assertIn(contact, closest_nodes)

    @defer.inlineCallbacks
    def test_add_self_as_contact(self):
        """ Tests the node's behaviour when attempting to add itself as a contact """
        # Create a contact with the same ID as the local node's ID
        contact = self.node.contact_manager.make_contact(self.node.node_id, '127.0.0.1', 9182, None)
        # Now try to add it
        yield self.node.addContact(contact)
        # ...and request the closest nodes to it using FIND_NODE
        closest_nodes = self.node._routingTable.findCloseNodes(self.node.node_id, constants.k)
        self.assertNotIn(contact, closest_nodes, 'Node added itself as a contact.')
