from lbrynet.core.Strategy import get_default_strategy


class BasePaymentRateManager(object):
    def __init__(self, rate):
        self.min_blob_data_payment_rate = rate


class PaymentRateManager(object):
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


class NegotiatedPaymentRateManager(object):
    def __init__(self, base, availability_tracker, generous=True):
        """
        @param base: a BasePaymentRateManager
        @param availability_tracker: a BlobAvailabilityTracker
        @param rate: the min blob data payment rate
        """

        self.base = base
        self.min_blob_data_payment_rate = self.base.min_blob_data_payment_rate
        self.points_paid = 0.0
        self.blob_tracker = availability_tracker
        self.generous = generous
        self.strategy = get_default_strategy(self.blob_tracker, base_price=self.min_blob_data_payment_rate, is_generous=generous)

    def get_rate_blob_data(self, peer, blobs):
        response = self.strategy.make_offer(peer, blobs)
        return response.rate

    def accept_rate_blob_data(self, peer, blobs, offer):
        offer = self.strategy.respond_to_offer(offer, peer, blobs)
        self.strategy.offer_accepted(peer, offer)
        return offer.accepted

    def reply_to_offer(self, peer, blobs, offer):
        reply = self.strategy.respond_to_offer(offer, peer, blobs)
        self.strategy.offer_accepted(peer, reply)
        return reply

    def get_rate_for_peer(self, peer):
        return self.strategy.accepted_offers.get(peer, False)

    def record_points_paid(self, amount):
        self.points_paid += amount

    def record_offer_reply(self, peer, offer):
        self.strategy.offer_accepted(peer, offer)