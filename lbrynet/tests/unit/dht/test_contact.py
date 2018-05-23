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
