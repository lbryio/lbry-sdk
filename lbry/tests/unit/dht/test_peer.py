import asyncio
import unittest
from lbry.utils import generate_id
from lbry.dht.peer import PeerManager, make_kademlia_peer
from torba.testcase import AsyncioTestCase


class PeerTest(AsyncioTestCase):
    def setUp(self):
        self.loop = asyncio.get_event_loop()
        self.peer_manager = PeerManager(self.loop)
        self.node_ids = [generate_id(), generate_id(), generate_id()]
        self.first_contact = make_kademlia_peer(self.node_ids[1], '127.0.0.1', udp_port=1000)
        self.second_contact = make_kademlia_peer(self.node_ids[0], '192.168.0.1', udp_port=1000)

    def test_peer_is_good_unknown_peer(self):
        # Scenario: peer replied, but caller doesn't know the node_id.
        # Outcome: We can't say it's good or bad.
        # (yes, we COULD tell the node id, but not here. It would be
        # a side effect and the caller is responsible to discover it)
        peer = make_kademlia_peer(None, '1.2.3.4', 4444)
        self.peer_manager.report_last_requested('1.2.3.4', 4444)
        self.peer_manager.report_last_replied('1.2.3.4', 4444)
        self.assertIsNone(self.peer_manager.peer_is_good(peer))

    def test_make_contact_error_cases(self):
        self.assertRaises(ValueError, make_kademlia_peer, self.node_ids[1], '192.168.1.20', 100000)
        self.assertRaises(ValueError, make_kademlia_peer, self.node_ids[1], '192.168.1.20.1', 1000)
        self.assertRaises(ValueError, make_kademlia_peer, self.node_ids[1], 'this is not an ip', 1000)
        self.assertRaises(ValueError, make_kademlia_peer, self.node_ids[1], '192.168.1.20', -1000)
        self.assertRaises(ValueError, make_kademlia_peer, b'not valid node id', '192.168.1.20', 1000)

    def test_boolean(self):
        self.assertNotEqual(self.first_contact, self.second_contact)
        self.assertEqual(
            self.second_contact, make_kademlia_peer(self.node_ids[0], '192.168.0.1', udp_port=1000)
        )

    def test_compact_ip(self):
        self.assertEqual(self.first_contact.compact_ip(), b'\x7f\x00\x00\x01')
        self.assertEqual(self.second_contact.compact_ip(), b'\xc0\xa8\x00\x01')


@unittest.SkipTest
class TestContactLastReplied(unittest.TestCase):
    def setUp(self):
        self.clock = task.Clock()
        self.contact_manager = ContactManager(self.clock.seconds)
        self.contact = self.contact_manager.make_contact(generate_id(), "127.0.0.1", 4444, None)
        self.clock.advance(3600)
        self.assertIsNone(self.contact.contact_is_good)

    def test_stale_replied_to_us(self):
        self.contact.update_last_replied()
        self.assertIs(self.contact.contact_is_good, True)

    def test_stale_requested_from_us(self):
        self.contact.update_last_requested()
        self.assertIsNone(self.contact.contact_is_good)

    def test_stale_then_fail(self):
        self.contact.update_last_failed()
        self.assertIsNone(self.contact.contact_is_good)
        self.clock.advance(1)
        self.contact.update_last_failed()
        self.assertIs(self.contact.contact_is_good, False)

    def test_good_turned_stale(self):
        self.contact.update_last_replied()
        self.assertIs(self.contact.contact_is_good, True)
        self.clock.advance(constants.checkRefreshInterval - 1)
        self.assertIs(self.contact.contact_is_good, True)
        self.clock.advance(1)
        self.assertIsNone(self.contact.contact_is_good)

    def test_good_then_fail(self):
        self.contact.update_last_replied()
        self.assertIs(self.contact.contact_is_good, True)
        self.clock.advance(1)
        self.contact.update_last_failed()
        self.assertIs(self.contact.contact_is_good, True)
        self.clock.advance(59)
        self.assertIs(self.contact.contact_is_good, True)
        self.contact.update_last_failed()
        self.assertIs(self.contact.contact_is_good, False)
        for _ in range(7200):
            self.clock.advance(60)
            self.assertIs(self.contact.contact_is_good, False)

    def test_good_then_fail_then_good(self):
        # it replies
        self.contact.update_last_replied()
        self.assertIs(self.contact.contact_is_good, True)
        self.clock.advance(1)

        # it fails twice in a row
        self.contact.update_last_failed()
        self.clock.advance(1)
        self.contact.update_last_failed()
        self.assertIs(self.contact.contact_is_good, False)
        self.clock.advance(1)

        # it replies
        self.contact.update_last_replied()
        self.clock.advance(1)
        self.assertIs(self.contact.contact_is_good, True)

        # it goes stale
        self.clock.advance(constants.checkRefreshInterval - 2)
        self.assertIs(self.contact.contact_is_good, True)
        self.clock.advance(1)
        self.assertIsNone(self.contact.contact_is_good)


@unittest.SkipTest
class TestContactLastRequested(unittest.TestCase):
    def setUp(self):
        self.clock = task.Clock()
        self.contact_manager = ContactManager(self.clock.seconds)
        self.contact = self.contact_manager.make_contact(generate_id(), "127.0.0.1", 4444, None)
        self.clock.advance(1)
        self.contact.update_last_replied()
        self.clock.advance(3600)
        self.assertIsNone(self.contact.contact_is_good)

    def test_previous_replied_then_requested(self):
        # it requests
        self.contact.update_last_requested()
        self.assertIs(self.contact.contact_is_good, True)

        # it goes stale
        self.clock.advance(constants.checkRefreshInterval - 1)
        self.assertIs(self.contact.contact_is_good, True)
        self.clock.advance(1)
        self.assertIsNone(self.contact.contact_is_good)

    def test_previous_replied_then_requested_then_failed(self):
        # it requests
        self.contact.update_last_requested()
        self.assertIs(self.contact.contact_is_good, True)
        self.clock.advance(1)

        # it fails twice in a row
        self.contact.update_last_failed()
        self.clock.advance(1)
        self.contact.update_last_failed()
        self.assertIs(self.contact.contact_is_good, False)
        self.clock.advance(1)

        # it requests
        self.contact.update_last_requested()
        self.clock.advance(1)
        self.assertIs(self.contact.contact_is_good, False)

        # it goes stale
        self.clock.advance((constants.refreshTimeout / 4) - 2)
        self.assertIs(self.contact.contact_is_good, False)
        self.clock.advance(1)
        self.assertIs(self.contact.contact_is_good, False)
