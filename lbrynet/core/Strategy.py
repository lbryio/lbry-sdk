import logging
from decimal import Decimal
from lbrynet.conf import MIN_BLOB_DATA_PAYMENT_RATE
from lbrynet.core.Offer import Offer
from lbrynet.core.PriceModel import MeanAvailabilityWeightedPrice

log = logging.getLogger(__name__)


def get_default_strategy(blob_tracker, **kwargs):
    return BasicAvailabilityWeightedStrategy(blob_tracker, **kwargs)


class BaseStrategy(object):
    def __init__(self, price_model, max_rate, min_rate, is_generous=True):
        self.price_model = price_model
        self.is_generous = is_generous
        self.accepted_offers = {}
        self.offers_sent = {}
        self.offers_received = {}
        self.max_rate = max_rate or Decimal(self.price_model.base_price * 100)
        self.min_rate = Decimal(min_rate)

    def add_offer_sent(self, peer):
        turn = self.offers_sent.get(peer, 0) + 1
        self.offers_sent.update({peer: turn})

    def add_offer_received(self, peer):
        turn = self.offers_received.get(peer, 0) + 1
        self.offers_received.update({peer: turn})

    def calculate_price_target(self, *args):
        return self.price_model.calculate_price(*args)

    def bounded_price(self, price):
        price_for_return = Decimal(min(self.max_rate, max(price, self.min_rate)))
        return price_for_return

    def make_offer(self, peer, blobs):
        offer_count = self.offers_sent.get(peer, 0)
        self.add_offer_sent(peer)
        if peer in self.accepted_offers:
            # if there was a previous accepted offer, use that
            offer = self.accepted_offers[peer]
        elif offer_count == 0 and self.is_generous:
            # Try asking for it for free
            offer = Offer(Decimal(0.0))
        else:
            rates = [self.calculate_price_target(blob) for blob in blobs]
            price = self._make_offer(rates, offer_count)
            bounded_price = self.bounded_price(price)
            offer = Offer(bounded_price)
        log.debug("Offering: %s", offer.rate)
        return offer

    def offer_accepted(self, peer, offer):
        if not offer.accepted and peer in self.accepted_offers:
            del self.accepted_offers[peer]
            log.debug("Throwing out old accepted offer")
        if offer.accepted:
            self.accepted_offers.update({peer: offer})
            log.debug("Updated accepted offer %f", offer.rate)

    def respond_to_offer(self, offer, peer, blobs):
        offer_count = self.offers_received.get(peer, 0)
        self.add_offer_received(peer)
        rates = [self.calculate_price_target(blob) for blob in blobs]
        price = self._respond_to_offer(rates, offer_count)
        bounded_price = self.bounded_price(price)
        log.debug("Price target: %f", price)

        if peer in self.accepted_offers:
            offer = self.accepted_offers[peer]
            log.debug("Already accepted %f", offer.rate)
        elif offer.rate == 0.0 and offer_count == 0 and self.is_generous:
            # give blobs away for free by default on the first request
            offer.accept()
            self.accepted_offers.update({peer: offer})
        elif offer.rate >= bounded_price:
            log.debug("Accept: %f", offer.rate)
            offer.accept()
            self.accepted_offers.update({peer: offer})
        else:
            log.debug("Reject: %f", offer.rate)
            offer.reject()
            if peer in self.accepted_offers:
                del self.accepted_offers[peer]
        return offer

    def _make_offer(self, rates, offer_count):
        return NotImplementedError()

    def _respond_to_offer(self, rates, offer_count):
        return NotImplementedError()


class BasicAvailabilityWeightedStrategy(BaseStrategy):
    """
    Basic strategy to target blob prices based on supply relative to mean supply

    Discount price target with each incoming request, and raise it with each outgoing from the modeled price
    until the rate is accepted or a threshold is reached
    """

    def __init__(self, blob_tracker, acceleration=1.25, deceleration=0.9, max_rate=None, min_rate=0.0,
                                    is_generous=True, base_price=MIN_BLOB_DATA_PAYMENT_RATE, alpha=1.0):
        price_model = MeanAvailabilityWeightedPrice(blob_tracker, base_price=base_price, alpha=alpha)
        BaseStrategy.__init__(self, price_model, max_rate, min_rate, is_generous)
        self._acceleration = Decimal(acceleration) # rate of how quickly to ramp offer
        self._deceleration = Decimal(deceleration)

    def _get_mean_rate(self, rates):
        mean_rate = Decimal(sum(rates)) / Decimal(max(len(rates), 1))
        return mean_rate

    def _premium(self, rate, turn):
        return rate * (self._acceleration ** Decimal(turn))

    def _discount(self, rate, turn):
        return rate * (self._deceleration ** Decimal(turn))

    def _respond_to_offer(self, rates, offer_count):
        rate = self._get_mean_rate(rates)
        discounted = self._discount(rate, offer_count)
        return round(discounted, 5)

    def _make_offer(self, rates, offer_count):
        rate = self._get_mean_rate(rates)
        with_premium = self._premium(rate, offer_count)
        return round(with_premium, 5)
