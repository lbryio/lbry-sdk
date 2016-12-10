import StringIO
import logging

import mock
from twisted.internet import defer
from twisted.trial import unittest

from lbrynet.core import log_support


class TestLogger(unittest.TestCase):
    def raiseError(self):
        raise Exception('terrible things happened')

    def triggerErrback(self, callback=None):
        d = defer.Deferred()
        d.addCallback(lambda _: self.raiseError())
        d.addErrback(self.log.fail(callback), 'My message')
        d.callback(None)
        return d

    def setUp(self):
        self.log = log_support.Logger('test')
        self.stream = StringIO.StringIO()
        handler = logging.StreamHandler(self.stream)
        handler.setFormatter(logging.Formatter("%(filename)s:%(lineno)d - %(message)s"))
        self.log.addHandler(handler)

    def test_can_log_failure(self):
        def output_lines():
            return self.stream.getvalue().split('\n')

        # the line number could change if this file gets refactored
        expected_first_line = 'test_log_support.py:18 - My message: terrible things happened'

        # testing the entirety of the message is futile as the
        # traceback will depend on the system the test is being run on
        # but hopefully these two tests are good enough
        d = self.triggerErrback()
        d.addCallback(lambda _: self.assertEquals(expected_first_line, output_lines()[0]))
        d.addCallback(lambda _: self.assertEqual(10, len(output_lines())))
        return d

    def test_can_log_failure_with_callback(self):
        callback = mock.Mock()
        d = self.triggerErrback(callback)
        d.addCallback(lambda _: callback.assert_called_once_with(mock.ANY))
        return d
