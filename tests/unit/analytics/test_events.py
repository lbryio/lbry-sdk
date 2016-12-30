from lbrynet.analytics import events

from twisted.trial import unittest

from tests import util


class EventsTest(unittest.TestCase):
    def setUp(self):
        util.resetTime(self)
        self.event_generator = events.Events('any valid json datatype', 'lbry123', 'session456')

    def test_heartbeat(self):
        result = self.event_generator.heartbeat()
        desired_result = {
            'context': 'any valid json datatype',
            'event': 'Heartbeat',
            'properties': {'lbry_id': 'lbry123', 'session_id': 'session456'},
            'timestamp': '2016-01-01T00:00:00Z',
            'userId': 'lbry'
        }
        self.assertEqual(desired_result, result)

    def test_download_started(self):
        result = self.event_generator.download_started('1', 'great gatsby')
        desired_result = {
            'context': 'any valid json datatype',
            'event': 'Download Started',
            'properties': {
                'lbry_id': 'lbry123',
                'session_id': 'session456',
                'name': 'great gatsby',
                'stream_info': None,
                'download_id': '1'
            },
            'timestamp': '2016-01-01T00:00:00Z',
            'userId': 'lbry'
        }
        self.assertEqual(desired_result, result)
