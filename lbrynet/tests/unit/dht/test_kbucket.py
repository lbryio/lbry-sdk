#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive

import unittest

from lbrynet.dht import kbucket
import lbrynet.dht.contact as contact
from lbrynet.dht import constants

class KBucketTest(unittest.TestCase):
    """ Test case for the KBucket class """
    def setUp(self):
        self.kbucket = kbucket.KBucket(0, 2**160)

    def testAddContact(self):
        """ Tests if the bucket handles contact additions/updates correctly """
        # Test if contacts can be added to empty list
        # Add k contacts to bucket
        for i in range(constants.k):
            tmpContact = contact.Contact('tempContactID%d' % i, str(i), i, i)
            self.kbucket.addContact(tmpContact)
            self.failUnlessEqual(
                self.kbucket._contacts[i],
                tmpContact,
                "Contact in position %d not the same as the newly-added contact" % i)

        # Test if contact is not added to full list
        i += 1
        tmpContact = contact.Contact('tempContactID%d' % i, str(i), i, i)
        self.failUnlessRaises(kbucket.BucketFull, self.kbucket.addContact, tmpContact)

        # Test if an existing contact is updated correctly if added again
        existingContact = self.kbucket._contacts[0]
        self.kbucket.addContact(existingContact)
        self.failUnlessEqual(
            self.kbucket._contacts.index(existingContact),
            len(self.kbucket._contacts)-1,
            'Contact not correctly updated; it should be at the end of the list of contacts')

    def testGetContacts(self):
        # try and get 2 contacts from empty list
        result = self.kbucket.getContacts(2)
        self.failIf(len(result) != 0, "Returned list should be empty; returned list length: %d" %
                    (len(result)))


        # Add k-2 contacts
        if constants.k >= 2:
            for i in range(constants.k-2):
                tmpContact = contact.Contact(i, i, i, i)
                self.kbucket.addContact(tmpContact)
        else:
            # add k contacts
            for i in range(constants.k):
                tmpContact = contact.Contact(i, i, i, i)
                self.kbucket.addContact(tmpContact)

        # try to get too many contacts
        # requested count greater than bucket size; should return at most k contacts
        contacts = self.kbucket.getContacts(constants.k+3)
        self.failUnless(len(contacts) <= constants.k,
                        'Returned list should not have more than k entries!')

        # verify returned contacts in list
        for i in range(constants.k-2):
            self.failIf(self.kbucket._contacts[i].id != i,
                        "Contact in position %s not same as added contact" % (str(i)))

        # try to get too many contacts
        # requested count one greater than number of contacts
        if constants.k >= 2:
            result = self.kbucket.getContacts(constants.k-1)
            self.failIf(len(result) != constants.k-2,
                        "Too many contacts in returned list %s - should be %s" %
                        (len(result), constants.k-2))
        else:
            result = self.kbucket.getContacts(constants.k-1)
            # if the count is <= 0, it should return all of it's contats
            self.failIf(len(result) != constants.k,
                        "Too many contacts in returned list %s - should be %s" %
                        (len(result), constants.k-2))
            result = self.kbucket.getContacts(constants.k-3)
            self.failIf(len(result) != constants.k-3,
                        "Too many contacts in returned list %s - should be %s" %
                        (len(result), constants.k-3))

    def testRemoveContact(self):
        # try remove contact from empty list
        rmContact = contact.Contact('TestContactID1', '127.0.0.1', 1, 1)
        self.failUnlessRaises(ValueError, self.kbucket.removeContact, rmContact)

        # Add couple contacts
        for i in range(constants.k-2):
            tmpContact = contact.Contact('tmpTestContactID%d' % i, str(i), i, i)
            self.kbucket.addContact(tmpContact)

        # try remove contact from empty list
        self.kbucket.addContact(rmContact)
        result = self.kbucket.removeContact(rmContact)
        self.failIf(rmContact in self.kbucket._contacts, "Could not remove contact from bucket")


def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(KBucketTest))
    return suite

if __name__ == '__main__':
    # If this module is executed from the commandline, run all its tests
    unittest.TextTestRunner().run(suite())
