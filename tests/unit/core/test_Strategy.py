from twisted.trial import unittest
from lbrynet.core.Strategy import BasicAvailabilityWeightedStrategy
from lbrynet.core.BlobAvailability import DummyBlobAvailabilityTracker


class StrategyTests(unittest.TestCase):
    def test_first_offer_is_zero_and_second_isnt(self):
        strategy = BasicAvailabilityWeightedStrategy(DummyBlobAvailabilityTracker())
        peer = "1.1.1.1"
        blobs = strategy.model.blob_tracker.availability.keys()
        offer1 = strategy.make_offer(peer, blobs)
        offer2 = strategy.make_offer(peer, blobs)
        self.assertEquals(offer1.rate, 0.0)
        self.assertNotEqual(offer2.rate, 0.0)

    def test_accept_zero_for_first_offer_and_reject_after(self):
        host_strategy = BasicAvailabilityWeightedStrategy(DummyBlobAvailabilityTracker())
        client = "1.1.1.1"
        host = "1.1.1.2"
        blobs = host_strategy.model.blob_tracker.availability.keys()
        client_strategy = BasicAvailabilityWeightedStrategy(DummyBlobAvailabilityTracker())
        client_offer1 = client_strategy.make_offer(host, blobs)
        client_strategy = BasicAvailabilityWeightedStrategy(DummyBlobAvailabilityTracker())
        client_offer2 = client_strategy.make_offer(host, blobs)

        host_response1 = host_strategy.respond_to_offer(client_offer1, client, blobs)
        host_response2 = host_strategy.respond_to_offer(client_offer2, client, blobs)

        self.assertEquals(host_response2.too_low, False)
        self.assertEquals(host_response1.accepted, True)
        self.assertEquals(host_response1.rate, 0.0)

        self.assertEquals(host_response2.too_low, True)
        self.assertEquals(host_response2.accepted, False)
        self.assertEquals(host_response2.rate, 0.0)