import struct
import asyncio
from lbry.utils import generate_id
from lbry.dht.protocol.routing_table import KBucket
from lbry.dht.peer import PeerManager, get_kademlia_peer
from lbry.dht import constants
from torba.testcase import AsyncioTestCase


def address_generator(address=(10, 42, 42, 1)):
    def increment(addr):
        value = struct.unpack("I", "".join([chr(x) for x in list(addr)[::-1]]).encode())[0] + 1
        new_addr = []
        for i in range(4):
            new_addr.append(value % 256)
            value >>= 8
        return tuple(new_addr[::-1])

    while True:
        yield "{}.{}.{}.{}".format(*address)
        address = increment(address)


class TestKBucket(AsyncioTestCase):
    def setUp(self):
        self.loop = asyncio.get_event_loop()
        self.address_generator = address_generator()
        self.peer_manager = PeerManager(self.loop)
        self.kbucket = KBucket(self.peer_manager, 0, 2**constants.hash_bits, generate_id())

    def test_add_peer(self):
        peer = get_kademlia_peer(constants.generate_id(2), "1.2.3.4", udp_port=4444)
        peer_update2 = get_kademlia_peer(constants.generate_id(2), "1.2.3.4", udp_port=4445)

        self.assertListEqual([], self.kbucket.peers)

        # add the peer
        self.kbucket.add_peer(peer)
        self.assertListEqual([peer], self.kbucket.peers)

        # re-add it
        self.kbucket.add_peer(peer)
        self.assertListEqual([peer], self.kbucket.peers)
        self.assertEqual(self.kbucket.peers[0].udp_port, 4444)

        # add a new peer object with the same id and address but a different port
        self.kbucket.add_peer(peer_update2)
        self.assertListEqual([peer_update2], self.kbucket.peers)
        self.assertEqual(self.kbucket.peers[0].udp_port, 4445)

        # modify the peer object to have a different port
        peer_update2.udp_port = 4444
        self.kbucket.add_peer(peer_update2)
        self.assertListEqual([peer_update2], self.kbucket.peers)
        self.assertEqual(self.kbucket.peers[0].udp_port, 4444)

        self.kbucket.peers.clear()

        # Test if contacts can be added to empty list
        # Add k contacts to bucket
        for i in range(constants.k):
            peer = get_kademlia_peer(generate_id(), next(self.address_generator), 4444)
            self.assertTrue(self.kbucket.add_peer(peer))
            self.assertEqual(peer, self.kbucket.peers[i])

        # Test if contact is not added to full list
        peer = get_kademlia_peer(generate_id(), next(self.address_generator), 4444)
        self.assertFalse(self.kbucket.add_peer(peer))

        # Test if an existing contact is updated correctly if added again
        existing_peer = self.kbucket.peers[0]
        self.assertTrue(self.kbucket.add_peer(existing_peer))
        self.assertEqual(existing_peer, self.kbucket.peers[-1])

    # def testGetContacts(self):
    #     # try and get 2 contacts from empty list
    #     result = self.kbucket.getContacts(2)
    #     self.assertFalse(len(result) != 0, "Returned list should be empty; returned list length: %d" %
    #                 (len(result)))
    #
    #     # Add k-2 contacts
    #     node_ids = []
    #     if constants.k >= 2:
    #         for i in range(constants.k-2):
    #             node_ids.append(generate_id())
    #             tmpContact = self.contact_manager.make_contact(node_ids[-1], next(self.address_generator), 4444, 0,
    #                                                            None)
    #             self.kbucket.addContact(tmpContact)
    #     else:
    #         # add k contacts
    #         for i in range(constants.k):
    #             node_ids.append(generate_id())
    #             tmpContact = self.contact_manager.make_contact(node_ids[-1], next(self.address_generator), 4444, 0,
    #                                                            None)
    #             self.kbucket.addContact(tmpContact)
    #
    #     # try to get too many contacts
    #     # requested count greater than bucket size; should return at most k contacts
    #     contacts = self.kbucket.getContacts(constants.k+3)
    #     self.assertTrue(len(contacts) <= constants.k,
    #                     'Returned list should not have more than k entries!')
    #
    #     # verify returned contacts in list
    #     for node_id, i in zip(node_ids, range(constants.k-2)):
    #         self.assertFalse(self.kbucket._contacts[i].id != node_id,
    #                     "Contact in position %s not same as added contact" % (str(i)))
    #
    #     # try to get too many contacts
    #     # requested count one greater than number of contacts
    #     if constants.k >= 2:
    #         result = self.kbucket.getContacts(constants.k-1)
    #         self.assertFalse(len(result) != constants.k-2,
    #                     "Too many contacts in returned list %s - should be %s" %
    #                     (len(result), constants.k-2))
    #     else:
    #         result = self.kbucket.getContacts(constants.k-1)
    #         # if the count is <= 0, it should return all of it's contats
    #         self.assertFalse(len(result) != constants.k,
    #                     "Too many contacts in returned list %s - should be %s" %
    #                     (len(result), constants.k-2))
    #         result = self.kbucket.getContacts(constants.k-3)
    #         self.assertFalse(len(result) != constants.k-3,
    #                     "Too many contacts in returned list %s - should be %s" %
    #                     (len(result), constants.k-3))

    def test_remove_peer(self):
        # try remove contact from empty list
        peer = get_kademlia_peer(generate_id(), next(self.address_generator), 4444)
        self.assertRaises(ValueError, self.kbucket.remove_peer, peer)

        added = []
        # Add couple contacts
        for i in range(constants.k-2):
            peer = get_kademlia_peer(generate_id(), next(self.address_generator), 4444)
            self.assertTrue(self.kbucket.add_peer(peer))
            added.append(peer)

        while added:
            peer = added.pop()
            self.assertIn(peer, self.kbucket.peers)
            self.kbucket.remove_peer(peer)
            self.assertNotIn(peer, self.kbucket.peers)
