from lbrynet.core.Error import NegotiationError


class Offer(object):
    """
    A rate offer to download blobs from a host
    """

    def __init__(self, offer):
        self._state = None
        self.rate = None
        if isinstance(offer, float):
            self.rate = round(offer, 5)
        elif offer == Negotiate.RATE_ACCEPTED:
            self.accept()
        elif offer == Negotiate.RATE_TOO_LOW:
            self.reject()

    @property
    def accepted(self):
        return self._state is Negotiate.RATE_ACCEPTED

    @property
    def too_low(self):
        return self._state is Negotiate.RATE_TOO_LOW

    @property
    def message(self):
        if self.accepted:
            return Negotiate.RATE_ACCEPTED
        elif self.too_low:
            return Negotiate.RATE_TOO_LOW
        elif self.rate is None:
            return Negotiate.RATE_UNSET

    def accept(self):
        if self._state is None:
            self._state = Negotiate.RATE_ACCEPTED

    def reject(self):
        if self._state is None:
            self._state = Negotiate.RATE_TOO_LOW


class Negotiate(object):
    """
    Helper class for converting to and from Offers
    """

    RATE_ACCEPTED = "RATE_ACCEPTED"
    RATE_TOO_LOW = "RATE_TOO_LOW"
    RATE_UNSET = "RATE_UNSET"

    PAYMENT_RATE = "blob_data_payment_rate"
    ERROR = "error"

    @staticmethod
    def get_offer_from_request(request_dict):
        error = request_dict.get(Negotiate.ERROR, False)
        if error:
            raise NegotiationError()
        return Offer(request_dict.get(Negotiate.PAYMENT_RATE))

    @staticmethod
    def make_dict_from_offer(offer):
        if offer.message:
            request_dict = {Negotiate.PAYMENT_RATE: offer.message}
        else:
            request_dict = {Negotiate.PAYMENT_RATE: offer.rate}
        return request_dict
