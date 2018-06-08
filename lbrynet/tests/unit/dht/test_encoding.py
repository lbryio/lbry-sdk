#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive

from twisted.trial import unittest
import lbrynet.dht.encoding


class BencodeTest(unittest.TestCase):
    """ Basic tests case for the Bencode implementation """
    def setUp(self):
        self.encoding = lbrynet.dht.encoding.Bencode()
        # Thanks goes to wikipedia for the initial test cases ;-)
        self.cases = ((42, 'i42e'),
                      ('spam', '4:spam'),
                      (['spam', 42], 'l4:spami42ee'),
                      ({'foo': 42, 'bar': 'spam'}, 'd3:bar4:spam3:fooi42ee'),
                      # ...and now the "real life" tests
                      ([['abc', '127.0.0.1', 1919], ['def', '127.0.0.1', 1921]],
                       'll3:abc9:127.0.0.1i1919eel3:def9:127.0.0.1i1921eee'))
        # The following test cases are "bad"; i.e. sending rubbish into the decoder to test
        # what exceptions get thrown
        self.badDecoderCases = ('abcdefghijklmnopqrstuvwxyz',
                                '')

    def testEncoder(self):
        """ Tests the bencode encoder """
        for value, encodedValue in self.cases:
            result = self.encoding.encode(value)
            self.failUnlessEqual(
                result, encodedValue,
                'Value "%s" not correctly encoded! Expected "%s", got "%s"' %
                (value, encodedValue, result))

    def testDecoder(self):
        """ Tests the bencode decoder """
        for value, encodedValue in self.cases:
            result = self.encoding.decode(encodedValue)
            self.failUnlessEqual(
                result, value,
                'Value "%s" not correctly decoded! Expected "%s", got "%s"' %
                (encodedValue, value, result))
        for encodedValue in self.badDecoderCases:
            self.failUnlessRaises(
                lbrynet.dht.encoding.DecodeError, self.encoding.decode, encodedValue)
