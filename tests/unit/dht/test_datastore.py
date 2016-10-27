#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive

import unittest
import time
import datetime
import random

import lbrynet.dht.datastore
import lbrynet.dht.constants

import hashlib

class DictDataStoreTest(unittest.TestCase):
    """ Basic tests case for the reference DataStore API and implementation """
    def setUp(self):
        #if not hasattr(self, 'ds'):
        self.ds = lbrynet.dht.datastore.DictDataStore()
        h = hashlib.sha1()
        h.update('g')
        hashKey = h.digest()
        h2 = hashlib.sha1()
        h2.update('dried')
        hashKey2 = h2.digest()
        h3 = hashlib.sha1()
        h3.update('Boozoo Bajou - 09 - S.I.P.mp3')
        hashKey3 = h3.digest()
        #self.cases = (('a', 'hello there\nthis is a test'),
        #              ('b', unicode('jasdklfjklsdj;f2352352ljklzsdlkjkasf\ndsjklafsd')),
        #              ('e', 123),
        #              ('f', [('this', 'is', 1), {'complex': 'data entry'}]),
        #              ('aMuchLongerKeyThanAnyOfThePreviousOnes', 'some data'),
        #              (hashKey, 'some data'),
        #              (hashKey2, 'abcdefghijklmnopqrstuvwxz'),
        #              (hashKey3, '1 2 3 4 5 6 7 8 9 0'))
        self.cases = ((hashKey, 'test1test1test1test1test1t'),
                      (hashKey, 'test2'),
                      (hashKey, 'test3test3test3test3test3test3test3test3'),
                      (hashKey2, 'test4'),
                      (hashKey3, 'test5'),
                      (hashKey3, 'test6'))
    
    def testReadWrite(self):
        # Test write ability
        for key, value in self.cases:
            try:
                now = int(time.time())
                self.ds.addPeerToBlob(key, value, now, now, 'node1')
            except Exception:
                import traceback
                self.fail('Failed writing the following data: key: "%s", data: "%s"\n  The error was: %s:' % (key, value, traceback.format_exc(5)))
        
        # Verify writing (test query ability)
        for key, value in self.cases:
            try:
                self.failUnless(self.ds.hasPeersForBlob(key), 'Key "%s" not found in DataStore! DataStore key dump: %s' % (key, self.ds.keys()))
            except Exception:
                import traceback
                self.fail('Failed verifying that the following key exists: "%s"\n  The error was: %s:' % (key, traceback.format_exc(5)))
        
        # Read back the data
        for key, value in self.cases:
            self.failUnless(value in self.ds.getPeersForBlob(key), 'DataStore returned invalid data! Expected "%s", got "%s"' % (value, self.ds.getPeersForBlob(key)))
    
    def testNonExistentKeys(self):
        for key, value in self.cases:
            self.failIf(key in self.ds.keys(), 'DataStore reports it has non-existent key: "%s"' % key)

    def testExpires(self):
        now = int(time.time())

        h1 = hashlib.sha1()
        h1.update('test1')
        key1 = h1.digest()
        h2 = hashlib.sha1()
        h2.update('test2')
        key2 = h2.digest()
        td = lbrynet.dht.constants.dataExpireTimeout - 100
        td2 = td + td
        self.ds.addPeerToBlob(h1, 'val1', now - td, now - td, '1')
        self.ds.addPeerToBlob(h1, 'val2', now - td2, now - td2, '2')
        self.ds.addPeerToBlob(h2, 'val3', now - td2, now - td2, '3')
        self.ds.addPeerToBlob(h2, 'val4', now, now, '4')
        self.ds.removeExpiredPeers()
        self.failUnless('val1' in self.ds.getPeersForBlob(h1), 'DataStore deleted an unexpired value! Value %s, publish time %s, current time %s'  % ('val1', str(now - td), str(now)))
        self.failIf('val2' in self.ds.getPeersForBlob(h1),  'DataStore failed to delete an expired value! Value %s, publish time %s, current time %s'  % ('val2', str(now - td2), str(now)))
        self.failIf('val3' in self.ds.getPeersForBlob(h2), 'DataStore failed to delete an expired value! Value %s, publish time %s, current time %s'  % ('val3', str(now - td2), str(now)))
        self.failUnless('val4' in self.ds.getPeersForBlob(h2), 'DataStore deleted an unexpired value! Value %s, publish time %s, current time %s'  % ('val4', str(now), str(now)))
            
#    def testReplace(self):
#        # First write with fake values
#        now = int(time.time())
#        for key, value in self.cases:
#            try:
#                self.ds.setItem(key, 'abc', now, now, 'node1')
#            except Exception:
#                import traceback
#                self.fail('Failed writing the following data: key: "%s", data: "%s"\n  The error was: %s:' % (key, value, traceback.format_exc(5)))
#
#        # write this stuff a second time, with the real values
#        for key, value in self.cases:
#            try:
#                self.ds.setItem(key, value, now, now, 'node1')
#            except Exception:
#                import traceback
#                self.fail('Failed writing the following data: key: "%s", data: "%s"\n  The error was: %s:' % (key, value, traceback.format_exc(5)))
#
#        self.failUnlessEqual(len(self.ds.keys()), len(self.cases), 'Values did not get overwritten properly; expected %d keys, got %d' % (len(self.cases), len(self.ds.keys())))
#        # Read back the data
#        for key, value in self.cases:
#            self.failUnlessEqual(self.ds[key], value, 'DataStore returned invalid data! Expected "%s", got "%s"' % (value, self.ds[key]))

#    def testDelete(self):
#        # First some values
#        now = int(time.time())
#        for key, value in self.cases:
#            try:
#                self.ds.setItem(key, 'abc', now, now, 'node1')
#            except Exception:
#                import traceback
#                self.fail('Failed writing the following data: key: "%s", data: "%s"\n  The error was: %s:' % (key, value, traceback.format_exc(5)))
#
#        self.failUnlessEqual(len(self.ds.keys()), len(self.cases), 'Values did not get stored properly; expected %d keys, got %d' % (len(self.cases), len(self.ds.keys())))
#
#        # Delete an item from the data
#        key, value == self.cases[0]
#        del self.ds[key]
#        self.failUnlessEqual(len(self.ds.keys()), len(self.cases)-1, 'Value was not deleted; expected %d keys, got %d' % (len(self.cases)-1, len(self.ds.keys())))
#        self.failIf(key in self.ds.keys(), 'Key was not deleted: %s' % key)

#    def testMetaData(self):
#        now = int(time.time())
#        age = random.randint(10,3600)
#        originallyPublished = []
#        for i in range(len(self.cases)):
#            originallyPublished.append(now - age)
#        # First some values with metadata
#        i = 0
#        for key, value in self.cases:
#            try:
#                self.ds.setItem(key, 'abc', now, originallyPublished[i], 'node%d' % i)
#                i += 1
#            except Exception:
#                import traceback
#                self.fail('Failed writing the following data: key: "%s", data: "%s"\n  The error was: %s:' % (key, value, traceback.format_exc(5)))
#
#        # Read back the meta-data
#        i = 0
#        for key, value in self.cases:
#            dsLastPublished = self.ds.lastPublished(key)
#            dsOriginallyPublished = self.ds.originalPublishTime(key)
#            dsOriginalPublisherID = self.ds.originalPublisherID(key)
#            self.failUnless(type(dsLastPublished) == int, 'DataStore returned invalid type for "last published" time! Expected "int", got %s' % type(dsLastPublished))
#            self.failUnless(type(dsOriginallyPublished) == int, 'DataStore returned invalid type for "originally published" time! Expected "int", got %s' % type(dsOriginallyPublished))
#            self.failUnless(type(dsOriginalPublisherID) == str, 'DataStore returned invalid type for "original publisher ID"; Expected "str", got %s' % type(dsOriginalPublisherID))
#            self.failUnlessEqual(dsLastPublished, now, 'DataStore returned invalid "last published" time! Expected "%d", got "%d"' % (now, dsLastPublished))
#            self.failUnlessEqual(dsOriginallyPublished, originallyPublished[i], 'DataStore returned invalid "originally published" time! Expected "%d", got "%d"' % (originallyPublished[i], dsOriginallyPublished))
#            self.failUnlessEqual(dsOriginalPublisherID, 'node%d' % i, 'DataStore returned invalid "original publisher ID"; Expected "%s", got "%s"' % ('node%d' % i, dsOriginalPublisherID))
#            i += 1


#class SQLiteDataStoreTest(DictDataStoreTest):
#    def setUp(self):
#        self.ds = entangled.kademlia.datastore.SQLiteDataStore()
#        DictDataStoreTest.setUp(self)


def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(DictDataStoreTest))
    #suite.addTest(unittest.makeSuite(SQLiteDataStoreTest))
    return suite


if __name__ == '__main__':
    # If this module is executed from the commandline, run all its tests
    unittest.TextTestRunner().run(suite())
