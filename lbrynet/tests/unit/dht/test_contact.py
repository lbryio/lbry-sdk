import unittest

from lbrynet.dht import contact


class ContactOperatorsTest(unittest.TestCase):
    """ Basic tests case for boolean operators on the Contact class """
    def setUp(self):
        self.firstContact = contact.Contact('firstContactID', '127.0.0.1', 1000, None, 1)
        self.secondContact = contact.Contact('2ndContactID', '192.168.0.1', 1000, None, 32)
        self.secondContactCopy = contact.Contact('2ndContactID', '192.168.0.1', 1000, None, 32)
        self.firstContactDifferentValues = contact.Contact(
            'firstContactID', '192.168.1.20', 1000, None, 50)

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

    def testStringComparisons(self):
        """ Test comparisons of Contact objects with str types """
        self.failUnlessEqual(
            'firstContactID', self.firstContact,
            'The node ID string must be equal to the contact object')
        self.failIfEqual(
            'some random string', self.firstContact,
            "The tested string should not be equal to the contact object (not equal to it's ID)")

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
