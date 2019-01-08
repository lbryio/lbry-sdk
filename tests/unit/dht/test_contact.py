import asyncio
from binascii import hexlify
from lbrynet.utils import generate_id
from lbrynet.peer import PeerManager
from torba.testcase import AsyncioTestCase


class PeerTest(AsyncioTestCase):
    def setUp(self):
        self.loop = asyncio.get_event_loop()
        self.peer_manager = PeerManager(self.loop)
        self.node_ids = [generate_id(), generate_id(), generate_id()]
        self.first_contact = self.peer_manager.make_peer('127.0.0.1', self.node_ids[1], udp_port=1000)
        self.second_contact = self.peer_manager.make_peer('192.168.0.1', self.node_ids[0], udp_port=1000)

    def test_make_contact_error_cases(self):
        self.assertRaises(ValueError, self.peer_manager.make_peer, '192.168.1.20', self.node_ids[1], 100000)
        self.assertRaises(ValueError, self.peer_manager.make_peer, '192.168.1.20.1', self.node_ids[1], 1000)
        self.assertRaises(ValueError, self.peer_manager.make_peer, 'this is not an ip', self.node_ids[1], 1000)
        self.assertRaises(ValueError, self.peer_manager.make_peer, '192.168.1.20', self.node_ids[1], -1000)
        self.assertRaises(ValueError, self.peer_manager.make_peer, '192.168.1.20', b'not valid node id', 1000)

    def test_no_duplicate_contact_objects(self):
        self.assertIs(self.second_contact, self.peer_manager.make_peer('192.168.0.1', self.node_ids[0], udp_port=1000))
        self.assertIsNot(self.first_contact, self.peer_manager.make_peer('192.168.1.20', self.node_ids[1], 1000))

    def test_boolean(self):
        self.assertNotEqual(self.first_contact, self.second_contact)
        self.assertEquals(
            self.second_contact, self.peer_manager.make_peer('192.168.0.1', self.node_ids[0], udp_port=1000)
        )

    def test_compact_ip(self):
        self.assertEqual(self.first_contact.compact_ip(), b'\x7f\x00\x00\x01')
        self.assertEqual(self.second_contact.compact_ip(), b'\xc0\xa8\x00\x01')

    def test_id_log(self):
        self.assertEqual(self.first_contact.log_id(False), hexlify(self.node_ids[1]))
        self.assertEqual(self.first_contact.log_id(True),  hexlify(self.node_ids[1])[:8])


# class TestContactLastReplied(unittest.TestCase):
#     def setUp(self):
#         self.clock = task.Clock()
#         self.contact_manager = ContactManager(self.clock.seconds)
#         self.contact = self.contact_manager.make_contact(generate_id(), "127.0.0.1", 4444, None)
#         self.clock.advance(3600)
#         self.assertIsNone(self.contact.contact_is_good)
#
#     def test_stale_replied_to_us(self):
#         self.contact.update_last_replied()
#         self.assertIs(self.contact.contact_is_good, True)
#
#     def test_stale_requested_from_us(self):
#         self.contact.update_last_requested()
#         self.assertIsNone(self.contact.contact_is_good)
#
#     def test_stale_then_fail(self):
#         self.contact.update_last_failed()
#         self.assertIsNone(self.contact.contact_is_good)
#         self.clock.advance(1)
#         self.contact.update_last_failed()
#         self.assertIs(self.contact.contact_is_good, False)
#
#     def test_good_turned_stale(self):
#         self.contact.update_last_replied()
#         self.assertIs(self.contact.contact_is_good, True)
#         self.clock.advance(constants.checkRefreshInterval - 1)
#         self.assertIs(self.contact.contact_is_good, True)
#         self.clock.advance(1)
#         self.assertIsNone(self.contact.contact_is_good)
#
#     def test_good_then_fail(self):
#         self.contact.update_last_replied()
#         self.assertIs(self.contact.contact_is_good, True)
#         self.clock.advance(1)
#         self.contact.update_last_failed()
#         self.assertIs(self.contact.contact_is_good, True)
#         self.clock.advance(59)
#         self.assertIs(self.contact.contact_is_good, True)
#         self.contact.update_last_failed()
#         self.assertIs(self.contact.contact_is_good, False)
#         for _ in range(7200):
#             self.clock.advance(60)
#             self.assertIs(self.contact.contact_is_good, False)
#
#     def test_good_then_fail_then_good(self):
#         # it replies
#         self.contact.update_last_replied()
#         self.assertIs(self.contact.contact_is_good, True)
#         self.clock.advance(1)
#
#         # it fails twice in a row
#         self.contact.update_last_failed()
#         self.clock.advance(1)
#         self.contact.update_last_failed()
#         self.assertIs(self.contact.contact_is_good, False)
#         self.clock.advance(1)
#
#         # it replies
#         self.contact.update_last_replied()
#         self.clock.advance(1)
#         self.assertIs(self.contact.contact_is_good, True)
#
#         # it goes stale
#         self.clock.advance(constants.checkRefreshInterval - 2)
#         self.assertIs(self.contact.contact_is_good, True)
#         self.clock.advance(1)
#         self.assertIsNone(self.contact.contact_is_good)
#
#
# class TestContactLastRequested(unittest.TestCase):
#     def setUp(self):
#         self.clock = task.Clock()
#         self.contact_manager = ContactManager(self.clock.seconds)
#         self.contact = self.contact_manager.make_contact(generate_id(), "127.0.0.1", 4444, None)
#         self.clock.advance(1)
#         self.contact.update_last_replied()
#         self.clock.advance(3600)
#         self.assertIsNone(self.contact.contact_is_good)
#
#     def test_previous_replied_then_requested(self):
#         # it requests
#         self.contact.update_last_requested()
#         self.assertIs(self.contact.contact_is_good, True)
#
#         # it goes stale
#         self.clock.advance(constants.checkRefreshInterval - 1)
#         self.assertIs(self.contact.contact_is_good, True)
#         self.clock.advance(1)
#         self.assertIsNone(self.contact.contact_is_good)
#
#     def test_previous_replied_then_requested_then_failed(self):
#         # it requests
#         self.contact.update_last_requested()
#         self.assertIs(self.contact.contact_is_good, True)
#         self.clock.advance(1)
#
#         # it fails twice in a row
#         self.contact.update_last_failed()
#         self.clock.advance(1)
#         self.contact.update_last_failed()
#         self.assertIs(self.contact.contact_is_good, False)
#         self.clock.advance(1)
#
#         # it requests
#         self.contact.update_last_requested()
#         self.clock.advance(1)
#         self.assertIs(self.contact.contact_is_good, False)
#
#         # it goes stale
#         self.clock.advance((constants.refreshTimeout / 4) - 2)
#         self.assertIs(self.contact.contact_is_good, False)
#         self.clock.advance(1)
#         self.assertIs(self.contact.contact_is_good, False)
