# pylint: skip-file
class BaseLiveStreamPaymentRateManager(object):
    def __init__(self, blob_info_rate, blob_data_rate=None):
        self.min_live_blob_info_payment_rate = blob_info_rate
        self.min_blob_data_payment_rate = blob_data_rate


class LiveStreamPaymentRateManager(object):
    def __init__(self, base_live_stream_payment_rate_manager, payment_rate_manager,
                 blob_info_rate=None, blob_data_rate=None):
        self._base_live_stream_payment_rate_manager = base_live_stream_payment_rate_manager
        self._payment_rate_manager = payment_rate_manager
        self.min_live_blob_info_payment_rate = blob_info_rate
        self.min_blob_data_payment_rate = blob_data_rate
        self.points_paid = 0.0

    def get_rate_live_blob_info(self, peer):
        return self.get_effective_min_live_blob_info_payment_rate()

    def accept_rate_live_blob_info(self, peer, payment_rate):
        return payment_rate >= self.get_effective_min_live_blob_info_payment_rate()

    def get_rate_blob_data(self, peer, blobs):
        response = self._payment_rate_manager.strategy.make_offer(peer, blobs)
        return response.rate

    def accept_rate_blob_data(self, peer, blobs, offer):
        response = self._payment_rate_manager.strategy.respond_to_offer(offer, peer, blobs)
        return response.accepted

    def reply_to_offer(self, peer, blobs, offer):
        reply = self._payment_rate_manager.strategy.respond_to_offer(offer, peer, blobs)
        self._payment_rate_manager.strategy.offer_accepted(peer, reply)
        return reply

    def get_effective_min_blob_data_payment_rate(self):
        rate = self.min_blob_data_payment_rate
        if rate is None:
            rate = self._payment_rate_manager.min_blob_data_payment_rate
        if rate is None:
            rate = self._base_live_stream_payment_rate_manager.min_blob_data_payment_rate
        if rate is None:
            rate = self._payment_rate_manager.get_effective_min_blob_data_payment_rate()
        return rate

    def get_effective_min_live_blob_info_payment_rate(self):
        rate = self.min_live_blob_info_payment_rate
        if rate is None:
            rate = self._base_live_stream_payment_rate_manager.min_live_blob_info_payment_rate
        return rate

    def record_points_paid(self, amount):
        self.points_paid += amount
