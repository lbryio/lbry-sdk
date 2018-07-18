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
        self.cases = ((42, b'i42e'),
                      (b'spam', b'4:spam'),
                      ([b'spam', 42], b'l4:spami42ee'),
                      ({b'foo': 42, b'bar': b'spam'}, b'd3:bar4:spam3:fooi42ee'),
                      # ...and now the "real life" tests
                      ([[b'abc', b'127.0.0.1', 1919], [b'def', b'127.0.0.1', 1921]],
                       b'll3:abc9:127.0.0.1i1919eel3:def9:127.0.0.1i1921eee'))
        # The following test cases are "bad"; i.e. sending rubbish into the decoder to test
        # what exceptions get thrown
        self.badDecoderCases = (b'abcdefghijklmnopqrstuvwxyz',
                                b'')

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
