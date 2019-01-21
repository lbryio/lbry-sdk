from decimal import Decimal
from lbrynet.p2p.Strategy import get_default_strategy, OnlyFreeStrategy


class BasePaymentRateManager:
    def __init__(self, rate, info_rate):
        self.min_blob_data_payment_rate = rate
        self.min_blob_info_payment_rate = info_rate


class PaymentRateManager:
    def __init__(self, base, rate=None):
        """
        @param base: a BasePaymentRateManager

        @param rate: the min blob data payment rate
        """
        self.base = base
        self.min_blob_data_payment_rate = rate
        self.points_paid = 0.0

    def get_rate_blob_data(self, peer):
        return self.get_effective_min_blob_data_payment_rate()

    def accept_rate_blob_data(self, peer, payment_rate):
        return payment_rate >= self.get_effective_min_blob_data_payment_rate()

    def get_effective_min_blob_data_payment_rate(self):
        if self.min_blob_data_payment_rate is None:
            return self.base.min_blob_data_payment_rate
        return self.min_blob_data_payment_rate

    def record_points_paid(self, amount):
        self.points_paid += amount


class NegotiatedPaymentRateManager:
    def __init__(self, base, availability_tracker, generous):
        """
        @param base: a BasePaymentRateManager
        @param availability_tracker: a BlobAvailabilityTracker
        @param rate: the min blob data payment rate
        """

        self.base = base
        self.min_blob_data_payment_rate = base.min_blob_data_payment_rate
        self.points_paid = 0.0
        self.blob_tracker = availability_tracker
        self.generous = generous
        self.strategy = get_default_strategy(
            self.blob_tracker, self.base.min_blob_data_payment_rate, generous
        )

    def get_rate_blob_data(self, peer, blobs):
        response = self.strategy.make_offer(peer, blobs)
        return response.rate

    def accept_rate_blob_data(self, peer, blobs, offer):
        offer = self.strategy.respond_to_offer(offer, peer, blobs)
        self.strategy.update_accepted_offers(peer, offer)
        return offer.is_accepted

    def reply_to_offer(self, peer, blobs, offer):
        reply = self.strategy.respond_to_offer(offer, peer, blobs)
        self.strategy.update_accepted_offers(peer, reply)
        return reply

    def get_rate_for_peer(self, peer):
        return self.strategy.accepted_offers.get(peer, False)

    def record_points_paid(self, amount):
        self.points_paid += amount

    def record_offer_reply(self, peer, offer):
        self.strategy.update_accepted_offers(peer, offer)

    def price_limit_reached(self, peer):
        if peer in self.strategy.pending_sent_offers:
            offer = self.strategy.pending_sent_offers[peer]
            return (offer.is_too_low and
                    round(Decimal.from_float(offer.rate), 5) >= round(self.strategy.max_rate, 5))
        return False


class OnlyFreePaymentsManager:
    def __init__(self, **kwargs):
        """
        A payment rate manager that will only ever accept and offer a rate of 0.0,
        Used for testing
        """

        self.base = BasePaymentRateManager(0.0, 0.0)
        self.points_paid = 0.0
        self.min_blob_data_payment_rate = 0.0
        self.generous = True
        self.strategy = OnlyFreeStrategy()

    def get_rate_blob_data(self, peer, blobs):
        response = self.strategy.make_offer(peer, blobs)
        return response.rate

    def accept_rate_blob_data(self, peer, blobs, offer):
        offer = self.strategy.respond_to_offer(offer, peer, blobs)
        self.strategy.update_accepted_offers(peer, offer)
        return offer.is_accepted

    def reply_to_offer(self, peer, blobs, offer):
        reply = self.strategy.respond_to_offer(offer, peer, blobs)
        self.strategy.update_accepted_offers(peer, reply)
        return reply

    def get_rate_for_peer(self, peer):
        return self.strategy.accepted_offers.get(peer, False)

    def record_points_paid(self, amount):
        self.points_paid += amount

    def record_offer_reply(self, peer, offer):
        self.strategy.update_accepted_offers(peer, offer)

    def price_limit_reached(self, peer):
        if peer in self.strategy.pending_sent_offers:
            offer = self.strategy.pending_sent_offers[peer]
            if offer.rate > 0.0:
                return True
        return False
