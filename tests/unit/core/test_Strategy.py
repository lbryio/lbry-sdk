from twisted.trial import unittest
import random
from lbrynet.core.Strategy import BasicAvailabilityWeightedStrategy
from lbrynet.core.BlobAvailability import DummyBlobAvailabilityTracker

def get_random_sample(list_to_sample):
    result = list_to_sample[random.randint(1, len(list_to_sample)):random.randint(1, len(list_to_sample))]
    if not result:
        return get_random_sample(list_to_sample)
    return result


class AvailabilityWeightedStrategyTests(unittest.TestCase):
    def test_first_offer_is_zero_and_second_isnt(self):
        strategy = BasicAvailabilityWeightedStrategy(DummyBlobAvailabilityTracker())
        peer = "1.1.1.1"
        blobs = strategy.model.blob_tracker.availability.keys()
        offer1 = strategy.make_offer(peer, blobs)
        offer2 = strategy.make_offer(peer, blobs)
        self.assertEquals(offer1.rate, 0.0)
        self.assertNotEqual(offer2.rate, 0.0)

    def test_accept_zero_and_persist(self):
        host_strategy = BasicAvailabilityWeightedStrategy(DummyBlobAvailabilityTracker())
        client = "1.1.1.1"
        host = "1.1.1.2"
        blobs = host_strategy.model.blob_tracker.availability.keys()
        client_strategy = BasicAvailabilityWeightedStrategy(DummyBlobAvailabilityTracker())
        offer = client_strategy.make_offer(host, blobs)
        response1 = host_strategy.respond_to_offer(offer, client, blobs)
        offer = client_strategy.make_offer(host, blobs)
        response2 = host_strategy.respond_to_offer(offer, client, blobs)

        self.assertEquals(response1.too_low, False)
        self.assertEquals(response1.accepted, True)
        self.assertEquals(response1.rate, 0.0)

        self.assertEquals(response2.too_low, False)
        self.assertEquals(response2.accepted, True)
        self.assertEquals(response2.rate, 0.0)

    def test_turns_before_accept_with_similar_rate_settings(self):
        blobs = [
            'b2e48bb4c88cf46b76adf0d47a72389fae0cd1f19ed27dc509138c99509a25423a4cef788d571dca7988e1dca69e6fa0',
            'd7c82e6cac093b3f16107d2ae2b2c75424f1fcad2c7fbdbe66e4a13c0b6bd27b67b3a29c403b82279ab0f7c1c48d6787',
            '5a450b416275da4bdff604ee7b58eaedc7913c5005b7184fc3bc5ef0b1add00613587f54217c91097fc039ed9eace9dd',
            'f99d24cd50d4bfd77c2598bfbeeb8415bf0feef21200bdf0b8fbbde7751a77b7a2c68e09c25465a2f40fba8eecb0b4e0',
            '9dbda74a472a2e5861a5d18197aeba0f5de67c67e401124c243d2f0f41edf01d7a26aeb0b5fc9bf47f6361e0f0968e2c',
            '91dc64cf1ff42e20d627b033ad5e4c3a4a96856ed8a6e3fb4cd5fa1cfba4bf72eefd325f579db92f45f4355550ace8e7',
            '6d8017aba362e5c5d0046625a039513419810a0397d728318c328a5cc5d96efb589fbca0728e54fe5adbf87e9545ee07',
            '6af95cd062b4a179576997ef1054c9d2120f8592eea045e9667bea411d520262cd5a47b137eabb7a7871f5f8a79c92dd',
            '8c70d5e2f5c3a6085006198e5192d157a125d92e7378794472007a61947992768926513fc10924785bdb1761df3c37e6',
            'c84aa1fd8f5009f7c4e71e444e40d95610abc1480834f835eefb267287aeb10025880a3ce22580db8c6d92efb5bc0c9c'
        ]
        for x in range(10):
            client_base = 0.001 * x
            for y in range(10):
                host_base = 0.001 * y
                client_strat = BasicAvailabilityWeightedStrategy(DummyBlobAvailabilityTracker(), base_price=client_base)
                host_strat = BasicAvailabilityWeightedStrategy(DummyBlobAvailabilityTracker(), base_price=host_base)
                for z in range(100):
                    blobs_to_query = get_random_sample(blobs)
                    accepted = False
                    turns = 0
                    while not accepted:
                        offer = client_strat.make_offer("2.3.4.5", blobs_to_query)
                        response = host_strat.respond_to_offer(offer, "3.4.5.6", blobs_to_query)
                        accepted = response.accepted
                        turns += 1
                    self.assertGreater(5, turns)
