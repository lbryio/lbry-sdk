from twisted.internet import task
from twisted.trial import unittest
from lbrynet.core.utils import generate_id
from lbrynet.dht.contact import ContactManager
from lbrynet.dht import constants


class ContactOperatorsTest(unittest.TestCase):
    """ Basic tests case for boolean operators on the Contact class """
    def setUp(self):
        self.contact_manager = ContactManager()
        self.node_ids = [generate_id(), generate_id(), generate_id()]
        self.firstContact = self.contact_manager.make_contact(self.node_ids[1], '127.0.0.1', 1000, None, 1)
        self.secondContact = self.contact_manager.make_contact(self.node_ids[0], '192.168.0.1', 1000, None, 32)
        self.secondContactCopy = self.contact_manager.make_contact(self.node_ids[0], '192.168.0.1', 1000, None, 32)
        self.firstContactDifferentValues = self.contact_manager.make_contact(self.node_ids[1], '192.168.1.20',
                                                                             1000, None, 50)
        self.assertRaises(ValueError, self.contact_manager.make_contact, self.node_ids[1], '192.168.1.20',
                                                                             100000, None)
        self.assertRaises(ValueError, self.contact_manager.make_contact, self.node_ids[1], '192.168.1.20.1',
                          1000, None)
        self.assertRaises(ValueError, self.contact_manager.make_contact, self.node_ids[1], 'this is not an ip',
                          1000, None)
        self.assertRaises(ValueError, self.contact_manager.make_contact, "this is not a node id", '192.168.1.20.1',
                          1000, None)

    def testNoDuplicateContactObjects(self):
        self.assertTrue(self.secondContact is self.secondContactCopy)
        self.assertTrue(self.firstContact is not self.firstContactDifferentValues)

    def testBoolean(self):
        """ Test "equals" and "not equals" comparisons """
        self.failIfEqual(
            self.firstContact, self.secondContact,
            'Contacts with different IDs should not be equal.')
        self.failUnlessEqual(
            self.firstContact, self.firstContactDifferentValues,
            'Contacts with same IDs should be equal, even if their other values differ.')
        self.failUnlessEqual(
            self.secondContact, self.secondContactCopy,
            'Different copies of the same Contact instance should be equal')

    def testIllogicalComparisons(self):
        """ Test comparisons with non-Contact and non-str types """
        msg = '"{}" operator: Contact object should not be equal to {} type'
        for item in (123, [1, 2, 3], {'key': 'value'}):
            self.failIfEqual(
                self.firstContact, item,
                msg.format('eq', type(item).__name__))
            self.failUnless(
                self.firstContact != item,
                msg.format('ne', type(item).__name__))

    def testCompactIP(self):
        self.assertEqual(self.firstContact.compact_ip(), '\x7f\x00\x00\x01')
        self.assertEqual(self.secondContact.compact_ip(), '\xc0\xa8\x00\x01')


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
