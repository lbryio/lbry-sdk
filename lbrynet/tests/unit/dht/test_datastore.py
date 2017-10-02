#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive

import unittest
import time

import lbrynet.dht.datastore
import lbrynet.dht.constants

import hashlib

class DictDataStoreTest(unittest.TestCase):
    """ Basic tests case for the reference DataStore API and implementation """
    def setUp(self):
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
                self.fail('Failed writing the following data: key: "%s" '
                          'data: "%s"\n  The error was: %s:' %
                          (key, value, traceback.format_exc(5)))

        # Verify writing (test query ability)
        for key, value in self.cases:
            try:
                self.failUnless(self.ds.hasPeersForBlob(key),
                                'Key "%s" not found in DataStore! DataStore key dump: %s' %
                                (key, self.ds.keys()))
            except Exception:
                import traceback
                self.fail(
                    'Failed verifying that the following key exists: "%s"\n  The error was: %s:' %
                    (key, traceback.format_exc(5)))

        # Read back the data
        for key, value in self.cases:
            self.failUnless(value in self.ds.getPeersForBlob(key),
                            'DataStore returned invalid data! Expected "%s", got "%s"' %
                            (value, self.ds.getPeersForBlob(key)))

    def testNonExistentKeys(self):
        for key, value in self.cases:
            self.failIf(key in self.ds.keys(), 'DataStore reports it has non-existent key: "%s"' %
                        key)

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
        self.failUnless(
            'val1' in self.ds.getPeersForBlob(h1),
            'DataStore deleted an unexpired value! Value %s, publish time %s, current time %s' %
            ('val1', str(now - td), str(now)))
        self.failIf(
            'val2' in self.ds.getPeersForBlob(h1),
            'DataStore failed to delete an expired value! '
            'Value %s, publish time %s, current time %s' %
            ('val2', str(now - td2), str(now)))
        self.failIf(
            'val3' in self.ds.getPeersForBlob(h2),
            'DataStore failed to delete an expired value! '
            'Value %s, publish time %s, current time %s' %
            ('val3', str(now - td2), str(now)))
        self.failUnless(
            'val4' in self.ds.getPeersForBlob(h2),
            'DataStore deleted an unexpired value! Value %s, publish time %s, current time %s' %
            ('val4', str(now), str(now)))

#        # First write with fake values
#        for key, value in self.cases:
#            except Exception:
#
#        # write this stuff a second time, with the real values
#        for key, value in self.cases:
#            except Exception:
#
#        # Read back the data
#        for key, value in self.cases:

#        # First some values
#        for key, value in self.cases:
#            except Exception:
#
#
#        # Delete an item from the data

#        # First some values with metadata
#        for key, value in self.cases:
#            except Exception:
#
#        # Read back the meta-data
#        for key, value in self.cases:




def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(DictDataStoreTest))
    return suite


if __name__ == '__main__':
    # If this module is executed from the commandline, run all its tests
    unittest.TextTestRunner().run(suite())
