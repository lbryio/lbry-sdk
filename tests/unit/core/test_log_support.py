import StringIO
import logging

from twisted.internet import defer
from twisted.trial import unittest

from lbrynet.core import log_support


class TestLogger(unittest.TestCase):
    def raiseError(self):
        raise Exception('terrible things happened')

    def triggerErrback(self, log):
        d = defer.Deferred()
        d.addCallback(lambda _: self.raiseError())
        d.addErrback(log.fail(), 'My message')
        d.callback(None)
        return d

    def test_can_log_failure(self):
        def output_lines():
            return stream.getvalue().split('\n')

        log = log_support.Logger('test')
        stream = StringIO.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(filename)s:%(lineno)d - %(message)s"))
        log.addHandler(handler)

        # the line number could change if this file gets refactored
        expected_first_line = 'test_log_support.py:17 - My message: terrible things happened'

        # testing the entirety of the message is futile as the
        # traceback will depend on the system the test is being run on
        # but hopefully these two tests are good enough
        d = self.triggerErrback(log)
        d.addCallback(lambda _: self.assertEquals(expected_first_line, output_lines()[0]))
        d.addCallback(lambda _: self.assertEqual(10, len(output_lines())))
        return d
