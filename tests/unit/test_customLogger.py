import StringIO
import logging

import mock
import unittest
from twisted.internet import defer
from twisted import trial

from lbrynet import custom_logger
from lbrynet.tests.util import is_android


class TestLogger(trial.unittest.TestCase):
    def raiseError(self):
        raise Exception('terrible things happened')

    def triggerErrback(self, callback=None):
        d = defer.Deferred()
        d.addCallback(lambda _: self.raiseError())
        d.addErrback(self.log.fail(callback), 'My message')
        d.callback(None)
        return d

    def setUp(self):
        self.log = custom_logger.Logger('test')
        self.stream = StringIO.StringIO()
        handler = logging.StreamHandler(self.stream)
        handler.setFormatter(logging.Formatter("%(filename)s:%(lineno)d - %(message)s"))
        self.log.addHandler(handler)

    @unittest.skipIf(is_android(),
                     'Test cannot pass on Android because the tests package is compiled '
                     'which results in a different method call stack')
    def test_can_log_failure(self):
        def output_lines():
            return self.stream.getvalue().split('\n')

        # the line number could change if this file gets refactored
        expected_first_line = 'test_customLogger.py:20 - My message: terrible things happened'

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
