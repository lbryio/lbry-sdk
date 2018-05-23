#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive

from twisted.trial import unittest
import struct
from lbrynet.core.utils import generate_id
from lbrynet.dht import kbucket
from lbrynet.dht.contact import ContactManager
from lbrynet.dht import constants


def address_generator(address=(10, 42, 42, 1)):
    def increment(addr):
        value = struct.unpack("I", "".join([chr(x) for x in list(addr)[::-1]]))[0] + 1
        new_addr = []
        for i in range(4):
            new_addr.append(value % 256)
            value >>= 8
        return tuple(new_addr[::-1])

    while True:
        yield "{}.{}.{}.{}".format(*address)
        address = increment(address)


class KBucketTest(unittest.TestCase):
    """ Test case for the KBucket class """
    def setUp(self):
        self.address_generator = address_generator()
        self.contact_manager = ContactManager()
        self.kbucket = kbucket.KBucket(0, 2**constants.key_bits, generate_id())

    def testAddContact(self):
        """ Tests if the bucket handles contact additions/updates correctly """
        # Test if contacts can be added to empty list
        # Add k contacts to bucket
        for i in range(constants.k):
            tmpContact = self.contact_manager.make_contact(generate_id(), next(self.address_generator), 4444, 0, None)
            self.kbucket.addContact(tmpContact)
            self.failUnlessEqual(
                self.kbucket._contacts[i],
                tmpContact,
                "Contact in position %d not the same as the newly-added contact" % i)

        # Test if contact is not added to full list
        tmpContact = self.contact_manager.make_contact(generate_id(), next(self.address_generator), 4444, 0, None)
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
        node_ids = []
        if constants.k >= 2:
            for i in range(constants.k-2):
                node_ids.append(generate_id())
                tmpContact = self.contact_manager.make_contact(node_ids[-1], next(self.address_generator), 4444, 0, None)
                self.kbucket.addContact(tmpContact)
        else:
            # add k contacts
            for i in range(constants.k):
                node_ids.append(generate_id())
                tmpContact = self.contact_manager.make_contact(node_ids[-1], next(self.address_generator), 4444, 0, None)
                self.kbucket.addContact(tmpContact)

        # try to get too many contacts
        # requested count greater than bucket size; should return at most k contacts
        contacts = self.kbucket.getContacts(constants.k+3)
        self.failUnless(len(contacts) <= constants.k,
                        'Returned list should not have more than k entries!')

        # verify returned contacts in list
        for node_id, i in zip(node_ids, range(constants.k-2)):
            self.failIf(self.kbucket._contacts[i].id != node_id,
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
        rmContact = self.contact_manager.make_contact(generate_id(), next(self.address_generator), 4444, 0, None)
        self.failUnlessRaises(ValueError, self.kbucket.removeContact, rmContact)

        # Add couple contacts
        for i in range(constants.k-2):
            tmpContact = self.contact_manager.make_contact(generate_id(), next(self.address_generator), 4444, 0, None)
            self.kbucket.addContact(tmpContact)

        # try remove contact from empty list
        self.kbucket.addContact(rmContact)
        result = self.kbucket.removeContact(rmContact)
        self.failIf(rmContact in self.kbucket._contacts, "Could not remove contact from bucket")
