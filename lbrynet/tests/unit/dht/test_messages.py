#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive

import unittest

from lbrynet.dht.msgtypes import RequestMessage, ResponseMessage, ErrorMessage
from lbrynet.dht.msgformat import MessageTranslator, DefaultFormat


class DefaultFormatTranslatorTest(unittest.TestCase):
    """ Test case for the default message translator """
    def setUp(self):
        self.cases = ((RequestMessage('1' * 48, 'rpcMethod',
                                      {'arg1': 'a string', 'arg2': 123}, '1' * 20),
                       {DefaultFormat.headerType: DefaultFormat.typeRequest,
                        DefaultFormat.headerNodeID: '1' * 48,
                        DefaultFormat.headerMsgID: '1' * 20,
                        DefaultFormat.headerPayload: 'rpcMethod',
                        DefaultFormat.headerArgs: {'arg1': 'a string', 'arg2': 123}}),

                      (ResponseMessage('2' * 20, '2' * 48, 'response'),
                       {DefaultFormat.headerType: DefaultFormat.typeResponse,
                        DefaultFormat.headerNodeID: '2' * 48,
                        DefaultFormat.headerMsgID: '2' * 20,
                        DefaultFormat.headerPayload: 'response'}),

                      (ErrorMessage('3' * 20, '3' * 48,
                                    "<type 'exceptions.ValueError'>", 'this is a test exception'),
                       {DefaultFormat.headerType: DefaultFormat.typeError,
                        DefaultFormat.headerNodeID: '3' * 48,
                        DefaultFormat.headerMsgID: '3' * 20,
                        DefaultFormat.headerPayload: "<type 'exceptions.ValueError'>",
                        DefaultFormat.headerArgs: 'this is a test exception'}),

                      (ResponseMessage(
                          '4' * 20, '4' * 48,
                          [('H\x89\xb0\xf4\xc9\xe6\xc5`H>\xd5\xc2\xc5\xe8Od\xf1\xca\xfa\x82',
                            '127.0.0.1', 1919),
                           ('\xae\x9ey\x93\xdd\xeb\xf1^\xff\xc5\x0f\xf8\xac!\x0e\x03\x9fY@{',
                            '127.0.0.1', 1921)]),
                       {DefaultFormat.headerType: DefaultFormat.typeResponse,
                        DefaultFormat.headerNodeID: '4' * 48,
                        DefaultFormat.headerMsgID: '4' * 20,
                        DefaultFormat.headerPayload:
                            [('H\x89\xb0\xf4\xc9\xe6\xc5`H>\xd5\xc2\xc5\xe8Od\xf1\xca\xfa\x82',
                              '127.0.0.1', 1919),
                             ('\xae\x9ey\x93\xdd\xeb\xf1^\xff\xc5\x0f\xf8\xac!\x0e\x03\x9fY@{',
                              '127.0.0.1', 1921)]})
                      )
        self.translator = DefaultFormat()
        self.failUnless(
            isinstance(self.translator, MessageTranslator),
            'Translator class must inherit from entangled.kademlia.msgformat.MessageTranslator!')

    def testToPrimitive(self):
        """ Tests translation from a Message object to a primitive """
        for msg, msgPrimitive in self.cases:
            translatedObj = self.translator.toPrimitive(msg)
            self.failUnlessEqual(len(translatedObj), len(msgPrimitive),
                                 "Translated object does not match example object's size")
            for key in msgPrimitive:
                self.failUnlessEqual(
                    translatedObj[key], msgPrimitive[key],
                    'Message object type %s not translated correctly into primitive on '
                    'key "%s"; expected "%s", got "%s"' %
                    (msg.__class__.__name__, key, msgPrimitive[key], translatedObj[key]))

    def testFromPrimitive(self):
        """ Tests translation from a primitive to a Message object """
        for msg, msgPrimitive in self.cases:
            translatedObj = self.translator.fromPrimitive(msgPrimitive)
            self.failUnlessEqual(
                type(translatedObj), type(msg),
                'Message type incorrectly translated; expected "%s", got "%s"' %
                (type(msg), type(translatedObj)))
            for key in msg.__dict__:
                self.failUnlessEqual(
                    msg.__dict__[key], translatedObj.__dict__[key],
                    'Message instance variable "%s" not translated correctly; '
                    'expected "%s", got "%s"' %
                    (key, msg.__dict__[key], translatedObj.__dict__[key]))
