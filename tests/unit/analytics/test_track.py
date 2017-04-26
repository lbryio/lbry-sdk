from lbrynet import analytics

from twisted.trial import unittest


class TrackTest(unittest.TestCase):
    def test_empty_summarize_is_none(self):
        track = analytics.Manager(None, 'x', 'y', 'z')
        _, result = track.summarize_and_reset('a')
        self.assertEqual(None, result)

    def test_can_get_sum_of_metric(self):
        track = analytics.Manager(None, 'x', 'y', 'z')
        track.add_observation('b', 1)
        track.add_observation('b', 2)

        _, result = track.summarize_and_reset('b')
        self.assertEqual(3, result)

    def test_summarize_resets_metric(self):
        track = analytics.Manager(None, 'x', 'y', 'z')
        track.add_observation('metric', 1)
        track.add_observation('metric', 2)

        track.summarize_and_reset('metric')
        _, result = track.summarize_and_reset('metric')
        self.assertEqual(None, result)
