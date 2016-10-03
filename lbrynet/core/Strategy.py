import logging

from lbrynet.core.Offer import Offer
from lbrynet.core.PriceModel import get_default_price_model

log = logging.getLogger(__name__)


def get_default_strategy(blob_tracker, **kwargs):
    return BasicAvailabilityWeightedStrategy(blob_tracker, **kwargs)


class BasicAvailabilityWeightedStrategy(object):
    """
    Basic strategy to target blob prices based on supply relative to mean supply

    Discount price target with each incoming request, and raise it with each outgoing from the modeled price
    until the rate is accepted or a threshold is reached
    """

    def __init__(self, blob_tracker, acceleration=1.25, deceleration=0.9, max_rate=0.005, min_rate=0.0, **kwargs):
        self._acceleration = acceleration # rate of how quickly to ramp offer
        self._deceleration = deceleration
        self._min_rate = min_rate
        self._max_rate = max_rate
        self._count_up = {}
        self._count_down = {}
        self._requested = {}
        self._offers_to_peers = {}
        self.model = get_default_price_model(blob_tracker, **kwargs)

    def respond_to_offer(self, offer, peer, blobs):
        request_count = self._count_up.get(peer, 0)
        rates = [self._calculate_price(blob) for blob in blobs]
        rate = sum(rates) / max(len(rates), 1)
        discounted = self._discount(rate, request_count)
        price = self._bounded_price(discounted)
        log.info("Price target: %f, final: %f", discounted, price)

        self._inc_up_count(peer)
        if offer.rate == 0.0 and request_count == 0:
            # give blobs away for free by default on the first request
            offer.accept()
            return offer
        elif offer.rate >= price:
            log.info("Accept: %f", offer.rate)
            offer.accept()
            return offer
        else:
            log.info("Reject: %f", offer.rate)
            offer.reject()
            return offer

    def make_offer(self, peer, blobs):
        # use mean turn-discounted price for all the blobs requested
        # if there was a previous offer replied to, use the same rate if it was accepted
        last_offer = self._offers_to_peers.get(peer, False)
        if last_offer:
            if last_offer.rate is not None and last_offer.accepted:
                return last_offer

        request_count = self._count_down.get(peer, 0)
        self._inc_down_count(peer)
        if request_count == 0:
            # Try asking for it for free
            self._offers_to_peers.update({peer: Offer(0.0)})
        else:
            rates = [self._calculate_price(blob) for blob in blobs]
            mean_rate = sum(rates) / max(len(blobs), 1)
            with_premium = self._premium(mean_rate, request_count)
            price = self._bounded_price(with_premium)
            self._offers_to_peers.update({peer: Offer(price)})
        return self._offers_to_peers[peer]

    def _bounded_price(self, price):
        price_for_return = min(self._max_rate, max(price, self._min_rate))
        return price_for_return

    def _inc_up_count(self, peer):
        turn = self._count_up.get(peer, 0) + 1
        self._count_up.update({peer: turn})

    def _inc_down_count(self, peer):
        turn = self._count_down.get(peer, 0) + 1
        self._count_down.update({peer: turn})

    def _calculate_price(self, blob):
        return self.model.calculate_price(blob)

    def _premium(self, rate, turn):
        return rate * (self._acceleration ** turn)

    def _discount(self, rate, turn):
        return rate * (self._deceleration ** turn)