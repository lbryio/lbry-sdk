from zope.interface import implementer
from decimal import Decimal
from lbrynet.conf import settings
from lbrynet.interfaces import INegotiationStrategy
from lbrynet.core.Offer import Offer
from lbrynet.core.PriceModel import MeanAvailabilityWeightedPrice


def get_default_strategy(blob_tracker, **kwargs):
    return BasicAvailabilityWeightedStrategy(blob_tracker, **kwargs)


class Strategy(object):
    """
    Base for negotiation strategies
    """
    implementer(INegotiationStrategy)

    def __init__(self, price_model, max_rate, min_rate, is_generous=settings.is_generous_host):
        self.price_model = price_model
        self.is_generous = is_generous
        self.accepted_offers = {}
        self.pending_sent_offers = {}
        self.offers_sent = {}
        self.offers_received = {}
        self.max_rate = max_rate or Decimal(self.price_model.base_price * 50)
        self.min_rate = Decimal(min_rate)

    def _make_rate_offer(self, rates, offer_count):
        return NotImplementedError()

    def _get_response_rate(self, rates, offer_count):
        return NotImplementedError()

    def make_offer(self, peer, blobs):
        offer_count = self.offers_sent.get(peer, 0)
        self._add_offer_sent(peer)
        if peer in self.accepted_offers:
            # if there was a previous accepted offer, use that
            offer = self.accepted_offers[peer]
            if peer in self.pending_sent_offers:
                del self.pending_sent_offers[peer]
        elif offer_count == 0 and self.is_generous:
            # Try asking for it for free
            offer = Offer(Decimal(0.0))
            self.pending_sent_offers.update({peer: offer})
        else:
            rates = [self.price_model.calculate_price(blob) for blob in blobs]
            price = self._make_rate_offer(rates, offer_count)
            offer = Offer(price)
            self.pending_sent_offers.update({peer: offer})
        return offer

    def respond_to_offer(self, offer, peer, blobs):
        offer_count = self.offers_received.get(peer, 0)
        self._add_offer_received(peer)
        rates = [self.price_model.calculate_price(blob) for blob in blobs]
        price = self._get_response_rate(rates, offer_count)
        if peer in self.accepted_offers:
            offer = self.accepted_offers[peer]
        elif offer.rate == 0.0 and offer_count == 0 and self.is_generous:
            # give blobs away for free by default on the first request
            offer.accept()
            self.accepted_offers.update({peer: offer})
        elif offer.rate >= price:
            offer.accept()
            self.accepted_offers.update({peer: offer})
        else:
            offer.reject()
            if peer in self.accepted_offers:
                del self.accepted_offers[peer]
        return offer

    def update_accepted_offers(self, peer, offer):
        if not offer.is_accepted and peer in self.accepted_offers:
            del self.accepted_offers[peer]
        if offer.is_accepted:
            self.accepted_offers.update({peer: offer})
        self.pending_sent_offers.update({peer: offer})

    def _add_offer_sent(self, peer):
        turn = self.offers_sent.get(peer, 0) + 1
        self.offers_sent.update({peer: turn})

    def _add_offer_received(self, peer):
        turn = self.offers_received.get(peer, 0) + 1
        self.offers_received.update({peer: turn})

    def _bounded_price(self, price):
        price_for_return = Decimal(min(self.max_rate, max(price, self.min_rate)))
        return price_for_return


class BasicAvailabilityWeightedStrategy(Strategy):
    """Basic strategy to target blob prices based on supply relative to mean supply

    Discount price target with each incoming request, and raise it
    with each outgoing from the modeled price until the rate is
    accepted or a threshold is reached

    """
    implementer(INegotiationStrategy)

    def __init__(self, blob_tracker, acceleration=1.25,
                 deceleration=0.9, max_rate=None,
                 min_rate=0.0,
                 is_generous=settings.is_generous_host,
                 base_price=0.0001, alpha=1.0):
        price_model = MeanAvailabilityWeightedPrice(
            blob_tracker, base_price=base_price, alpha=alpha)
        Strategy.__init__(self, price_model, max_rate, min_rate, is_generous)
        self._acceleration = Decimal(acceleration)  # rate of how quickly to ramp offer
        self._deceleration = Decimal(deceleration)

    def _get_mean_rate(self, rates):
        mean_rate = Decimal(sum(rates)) / Decimal(max(len(rates), 1))
        return mean_rate

    def _premium(self, rate, turn):
        return rate * (self._acceleration ** Decimal(turn))

    def _discount(self, rate, turn):
        return rate * (self._deceleration ** Decimal(turn))

    def _get_response_rate(self, rates, offer_count):
        rate = self._get_mean_rate(rates)
        discounted = self._discount(rate, offer_count)
        rounded_price = round(discounted, 5)
        return self._bounded_price(rounded_price)

    def _make_rate_offer(self, rates, offer_count):
        rate = self._get_mean_rate(rates)
        with_premium = self._premium(rate, offer_count)
        rounded_price = round(with_premium, 5)
        return self._bounded_price(rounded_price)
