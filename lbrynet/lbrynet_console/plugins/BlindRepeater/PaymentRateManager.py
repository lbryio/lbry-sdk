from lbrynet.core.PaymentRateManager import PaymentRateManager


class BlindRepeaterPaymentRateManager(PaymentRateManager):
    def __init__(self, base, valuable_info_rate, valuable_hash_rate, blob_data_rate=None):
        PaymentRateManager.__init__(self, base, blob_data_rate)
        self.min_valuable_blob_info_payment_rate = valuable_info_rate
        self.min_valuable_blob_hash_payment_rate = valuable_hash_rate

    def get_rate_valuable_blob_info(self, peer):
        return self.min_valuable_blob_info_payment_rate

    def accept_rate_valuable_blob_info(self, peer, payment_rate):
        return payment_rate >= self.min_valuable_blob_info_payment_rate

    def get_rate_valuable_blob_hash(self, peer):
        return self.min_valuable_blob_hash_payment_rate

    def accept_rate_valuable_blob_hash(self, peer, payment_rate):
        return payment_rate >= self.min_valuable_blob_hash_payment_rate