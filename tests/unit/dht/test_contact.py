from binascii import hexlify
from twisted.internet import task
from twisted.trial import unittest
from lbrynet.core.utils import generate_id
from lbrynet.dht.contact import ContactManager
from lbrynet.dht import constants


class ContactTest(unittest.TestCase):
    """ Basic tests case for boolean operators on the Contact class """
    def setUp(self):
        self.contact_manager = ContactManager()
        self.node_ids = [generate_id(), generate_id(), generate_id()]
        make_contact = self.contact_manager.make_contact
        self.first_contact = make_contact(self.node_ids[1], '127.0.0.1', 1000, None, 1)
        self.second_contact = make_contact(self.node_ids[0], '192.168.0.1', 1000, None, 32)
        self.second_contact_second_reference = make_contact(self.node_ids[0], '192.168.0.1', 1000, None, 32)
        self.first_contact_different_values = make_contact(self.node_ids[1], '192.168.1.20', 1000, None, 50)

    def test_make_contact_error_cases(self):
        self.assertRaises(
            ValueError, self.contact_manager.make_contact, self.node_ids[1], '192.168.1.20', 100000, None)
        self.assertRaises(
            ValueError, self.contact_manager.make_contact, self.node_ids[1], '192.168.1.20.1', 1000, None)
        self.assertRaises(
            ValueError, self.contact_manager.make_contact, self.node_ids[1], 'this is not an ip', 1000, None)
        self.assertRaises(
            ValueError, self.contact_manager.make_contact, b'not valid node id', '192.168.1.20.1', 1000, None)

    def test_no_duplicate_contact_objects(self):
        self.assertTrue(self.second_contact is self.second_contact_second_reference)
        self.assertTrue(self.first_contact is not self.first_contact_different_values)

    def test_boolean(self):
        """ Test "equals" and "not equals" comparisons """
        self.assertNotEqual(
            self.first_contact, self.contact_manager.make_contact(
                self.first_contact.id, self.first_contact.address, self.first_contact.port + 1, None, 32
            )
        )
        self.assertNotEqual(
            self.first_contact, self.contact_manager.make_contact(
                self.first_contact.id, '193.168.1.1', self.first_contact.port, None, 32
            )
        )
        self.assertNotEqual(
            self.first_contact, self.contact_manager.make_contact(
                generate_id(), self.first_contact.address, self.first_contact.port, None, 32
            )
        )
        self.assertEqual(self.second_contact, self.second_contact_second_reference)

    def test_compact_ip(self):
        self.assertEqual(self.first_contact.compact_ip(), b'\x7f\x00\x00\x01')
        self.assertEqual(self.second_contact.compact_ip(), b'\xc0\xa8\x00\x01')

    def test_id_log(self):
        self.assertEqual(self.first_contact.log_id(False), hexlify(self.node_ids[1]))
        self.assertEqual(self.first_contact.log_id(True),  hexlify(self.node_ids[1])[:8])


class TestContactLastReplied(unittest.TestCase):
    def setUp(self):
        self.clock = task.Clock()
        self.contact_manager = ContactManager(self.clock.seconds)
        self.contact = self.contact_manager.make_contact(generate_id(), "127.0.0.1", 4444, None)
        self.clock.advance(3600)
        self.assertTrue(self.contact.contact_is_good is None)

    def test_stale_replied_to_us(self):
        self.contact.update_last_replied()
        self.assertTrue(self.contact.contact_is_good is True)

    def test_stale_requested_from_us(self):
        self.contact.update_last_requested()
        self.assertTrue(self.contact.contact_is_good is None)

    def test_stale_then_fail(self):
        self.contact.update_last_failed()
        self.assertTrue(self.contact.contact_is_good is None)
        self.clock.advance(1)
        self.contact.update_last_failed()
        self.assertTrue(self.contact.contact_is_good is False)

    def test_good_turned_stale(self):
        self.contact.update_last_replied()
        self.assertTrue(self.contact.contact_is_good is True)
        self.clock.advance(constants.checkRefreshInterval - 1)
        self.assertTrue(self.contact.contact_is_good is True)
        self.clock.advance(1)
        self.assertTrue(self.contact.contact_is_good is None)

    def test_good_then_fail(self):
        self.contact.update_last_replied()
        self.assertTrue(self.contact.contact_is_good is True)
        self.clock.advance(1)
        self.contact.update_last_failed()
        self.assertTrue(self.contact.contact_is_good is True)
        self.clock.advance(59)
        self.assertTrue(self.contact.contact_is_good is True)
        self.contact.update_last_failed()
        self.assertTrue(self.contact.contact_is_good is False)
        for _ in range(7200):
            self.clock.advance(60)
            self.assertTrue(self.contact.contact_is_good is False)

    def test_good_then_fail_then_good(self):
        # it replies
        self.contact.update_last_replied()
        self.assertTrue(self.contact.contact_is_good is True)
        self.clock.advance(1)

        # it fails twice in a row
        self.contact.update_last_failed()
        self.clock.advance(1)
        self.contact.update_last_failed()
        self.assertTrue(self.contact.contact_is_good is False)
        self.clock.advance(1)

        # it replies
        self.contact.update_last_replied()
        self.clock.advance(1)
        self.assertTrue(self.contact.contact_is_good is True)

        # it goes stale
        self.clock.advance(constants.checkRefreshInterval - 2)
        self.assertTrue(self.contact.contact_is_good is True)
        self.clock.advance(1)
        self.assertTrue(self.contact.contact_is_good is None)


class TestContactLastRequested(unittest.TestCase):
    def setUp(self):
        self.clock = task.Clock()
        self.contact_manager = ContactManager(self.clock.seconds)
        self.contact = self.contact_manager.make_contact(generate_id(), "127.0.0.1", 4444, None)
        self.clock.advance(1)
        self.contact.update_last_replied()
        self.clock.advance(3600)
        self.assertTrue(self.contact.contact_is_good is None)

    def test_previous_replied_then_requested(self):
        # it requests
        self.contact.update_last_requested()
        self.assertTrue(self.contact.contact_is_good is True)

        # it goes stale
        self.clock.advance(constants.checkRefreshInterval - 1)
        self.assertTrue(self.contact.contact_is_good is True)
        self.clock.advance(1)
        self.assertTrue(self.contact.contact_is_good is None)

    def test_previous_replied_then_requested_then_failed(self):
        # it requests
        self.contact.update_last_requested()
        self.assertTrue(self.contact.contact_is_good is True)
        self.clock.advance(1)

        # it fails twice in a row
        self.contact.update_last_failed()
        self.clock.advance(1)
        self.contact.update_last_failed()
        self.assertTrue(self.contact.contact_is_good is False)
        self.clock.advance(1)

        # it requests
        self.contact.update_last_requested()
        self.clock.advance(1)
        self.assertTrue(self.contact.contact_is_good is False)

        # it goes stale
        self.clock.advance((constants.refreshTimeout / 4) - 2)
        self.assertTrue(self.contact.contact_is_good is False)
        self.clock.advance(1)
        self.assertTrue(self.contact.contact_is_good is False)
