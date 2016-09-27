import logging

from lbrynet.core.Offer import Offer
from lbrynet.core.PriceModel import MeanAvailabilityWeightedPrice

log = logging.getLogger(__name__)


def get_default_strategy(blob_tracker, **kwargs):
    return BasicAvailabilityWeightedStrategy(blob_tracker, **kwargs)


class BasicAvailabilityWeightedStrategy(object):
    """
    Basic strategy to target blob prices based on supply relative to mean supply

    Discount price target with each incoming request, and raise it with each outgoing from the modeled price
    until the rate is accepted or a threshold is reached
    """

    def __init__(self, blob_tracker, acceleration=1.25, deceleration=0.9, max_rate=0.005):
        self._acceleration = acceleration # rate of how quickly to ramp offer
        self._deceleration = deceleration
        self._max_rate = max_rate
        self._count_up = {}
        self._count_down = {}
        self._requested = {}
        self._offers_to_peers = {}
        self.model = MeanAvailabilityWeightedPrice(blob_tracker)

    def respond_to_offer(self, offer, peer, blobs):
        request_count = self._count_up.get(peer, 0)
        rates = [self._calculate_price(blob) for blob in blobs]
        rate = self._discount(sum(rates) / max(len(blobs), 1), request_count)
        log.info("Target rate: %s", rate)

        self._inc_up_count(peer)
        if offer.accepted:
            return offer
        elif offer.rate >= rate:
            log.info("Accept: %f", offer.rate)
            offer.accept()
            return offer
        else:
            log.info("Reject: %f", offer.rate)
            offer.reject()
            return offer

    def make_offer(self, peer, blobs):
        # use mean turn-discounted price for all the blobs requested
        request_count = self._count_down.get(peer, 0)
        self._inc_down_count(peer)
        if request_count == 0:
            # Try asking for it for free
            offer = Offer(0.0)
        else:
            rates = [self._calculate_price(blob) for blob in blobs]
            mean_rate = sum(rates) / max(len(blobs), 1)
            with_premium = self._premium(mean_rate, request_count)
            offer = Offer(with_premium)
        return offer

    def _inc_up_count(self, peer):
        turn = self._count_up.get(peer, 0) + 1
        self._count_up.update({peer: turn})

    def _inc_down_count(self, peer):
        turn = self._count_down.get(peer, 0) + 1
        self._count_down.update({peer: turn})

    def _calculate_price(self, blob):
        return self.model.calculate_price(blob)

    def _premium(self, rate, turn):
        return min(rate * (self._acceleration ** turn), self._max_rate)

    def _discount(self, rate, turn):
        return min(rate * (self._deceleration ** turn), self._max_rate)