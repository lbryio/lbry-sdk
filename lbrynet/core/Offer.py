from lbrynet.core.Error import NegotiationError


class Offer(object):
    """
    A rate offer to download blobs from a host
    """

    RATE_ACCEPTED = "RATE_ACCEPTED"
    RATE_TOO_LOW = "RATE_TOO_LOW"
    RATE_UNSET = "RATE_UNSET"

    def __init__(self, offer):
        self._state = None
        self.rate = None
        if isinstance(offer, float):
            self.rate = round(offer, 5)
        elif offer == Offer.RATE_ACCEPTED:
            self.accept()
        elif offer == Offer.RATE_TOO_LOW:
            self.reject()

    @property
    def accepted(self):
        return self._state is Offer.RATE_ACCEPTED

    @property
    def too_low(self):
        return self._state is Offer.RATE_TOO_LOW

    @property
    def message(self):
        if self.accepted:
            return Offer.RATE_ACCEPTED
        elif self.too_low:
            return Offer.RATE_TOO_LOW
        elif self.rate is None:
            return Offer.RATE_UNSET

    def accept(self):
        if self._state is None:
            self._state = Offer.RATE_ACCEPTED

    def reject(self):
        if self._state is None:
            self._state = Offer.RATE_TOO_LOW
