import itertools
from twisted.trial import unittest
import random
import mock
from lbrynet.core.PaymentRateManager import NegotiatedPaymentRateManager, BasePaymentRateManager
from lbrynet.core.Strategy import BasicAvailabilityWeightedStrategy
from lbrynet.core.Offer import Offer
from lbrynet.tests.mocks import BlobAvailabilityTracker as DummyBlobAvailabilityTracker, mock_conf_settings

MAX_NEGOTIATION_TURNS = 10
random.seed(12345)


def get_random_sample(list_to_sample):
    result = list_to_sample[random.randint(1, len(list_to_sample)):random.randint(1, len(list_to_sample))]
    if not result:
        return get_random_sample(list_to_sample)
    return result


def calculate_negotation_turns(client_base, host_base, host_is_generous=True, client_is_generous=True):
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

    host = mock.Mock()
    host.host = "1.2.3.4"
    client = mock.Mock()
    client.host = "1.2.3.5"

    client_base_prm = BasePaymentRateManager(client_base)
    client_prm = NegotiatedPaymentRateManager(client_base_prm,
                                              DummyBlobAvailabilityTracker(),
                                              generous=client_is_generous)
    host_base_prm = BasePaymentRateManager(host_base)
    host_prm = NegotiatedPaymentRateManager(host_base_prm,
                                            DummyBlobAvailabilityTracker(),
                                            generous=host_is_generous)
    blobs_to_query = get_random_sample(blobs)
    accepted = False
    turns = 0
    while not accepted:
        rate = client_prm.get_rate_blob_data(host, blobs_to_query)
        offer = Offer(rate)
        accepted = host_prm.accept_rate_blob_data(client, blobs_to_query, offer)
        turns += 1
    return turns


class AvailabilityWeightedStrategyTests(unittest.TestCase):
    def setUp(self):
        mock_conf_settings(self)

    def test_first_offer_is_zero_and_second_is_not_if_offer_not_accepted(self):
        strategy = BasicAvailabilityWeightedStrategy(DummyBlobAvailabilityTracker())
        peer = "1.1.1.1"

        blobs = strategy.price_model.blob_tracker.availability.keys()
        offer1 = strategy.make_offer(peer, blobs)

        offer2 = strategy.make_offer(peer, blobs)

        self.assertEquals(offer1.rate, 0.0)
        self.assertNotEqual(offer2.rate, 0.0)

    def test_accept_zero_and_persist_if_accepted(self):
        host_strategy = BasicAvailabilityWeightedStrategy(DummyBlobAvailabilityTracker())
        client_strategy = BasicAvailabilityWeightedStrategy(DummyBlobAvailabilityTracker())

        client = "1.1.1.1"
        host = "1.1.1.2"
        blobs = host_strategy.price_model.blob_tracker.availability.keys()

        offer = client_strategy.make_offer(host, blobs)
        response1 = host_strategy.respond_to_offer(offer, client, blobs)
        client_strategy.update_accepted_offers(host, response1)

        offer = client_strategy.make_offer(host, blobs)
        response2 = host_strategy.respond_to_offer(offer, client, blobs)
        client_strategy.update_accepted_offers(host, response2)

        self.assertEquals(response1.is_too_low, False)
        self.assertEquals(response1.is_accepted, True)
        self.assertEquals(response1.rate, 0.0)

        self.assertEquals(response2.is_too_low, False)
        self.assertEquals(response2.is_accepted, True)
        self.assertEquals(response2.rate, 0.0)

    def test_how_many_turns_before_accept_with_similar_rate_settings(self):
        base_rates = [0.0001 * n for n in range(1, 10)]
        for host_base, client_base in itertools.product(base_rates, base_rates):
            turns = calculate_negotation_turns(host_base,
                                               client_base,
                                               client_is_generous=False,
                                               host_is_generous=False)
            self.assertGreater(MAX_NEGOTIATION_TURNS, turns)

    def test_generous_connects_in_one_turn(self):
        base_rates = [0.0001 * n for n in range(1, 10)]
        for host_base, client_base in itertools.product(base_rates, base_rates):
            turns = calculate_negotation_turns(host_base, client_base)
            self.assertEqual(1, turns)

    def test_how_many_turns_with_generous_client(self):
        base_rates = [0.0001 * n for n in range(1, 10)]
        for host_base, client_base in itertools.product(base_rates, base_rates):
            turns = calculate_negotation_turns(host_base,
                                               client_base,
                                               host_is_generous=False)
            self.assertGreater(MAX_NEGOTIATION_TURNS, turns)

    def test_how_many_turns_with_generous_host(self):
        base_rates = [0.0001 * n for n in range(1, 10)]
        for host_base, client_base in itertools.product(base_rates, base_rates):
            turns = calculate_negotation_turns(host_base,
                                               client_base,
                                               client_is_generous=False)
            self.assertGreater(MAX_NEGOTIATION_TURNS, turns)
