from zope.interface import implementer
from decimal import Decimal

from lbrynet.interfaces import IBlobPriceModel
from lbrynet.conf import settings


def get_default_price_model(blob_tracker, base_price, **kwargs):
    return MeanAvailabilityWeightedPrice(blob_tracker, base_price, **kwargs)


class MeanAvailabilityWeightedPrice(object):
    """
    Calculate mean-blob-availability and stream-position weighted price for a blob

    Attributes:
        base_price (float): base price
        alpha (float): constant, > 0.0 and <= 1.0, used to more highly value blobs at the beginning of a stream.
                       alpha defaults to 1.0, which has a null effect
        blob_tracker (BlobAvailabilityTracker): blob availability tracker
    """
    implementer(IBlobPriceModel)

    def __init__(self, tracker, base_price=settings.data_rate, alpha=1.0):
        self.blob_tracker = tracker
        self.base_price = Decimal(base_price)
        self.alpha = Decimal(alpha)

    def calculate_price(self, blob):
        mean_availability = self.blob_tracker.last_mean_availability
        availability = self.blob_tracker.availability.get(blob, [])
        index = 0  # blob.index
        price = self.base_price *  self._get_availability_multiplier(mean_availability, availability) / self._frontload(index)
        return round(price, 5)

    def _get_availability_multiplier(self, mean_availability, availability):
        return Decimal(max(1, mean_availability) / Decimal(max(1, len(availability))))

    def _frontload(self, index):
        """
        Get front-load multiplier, used to weight prices of blobs in a stream towards the front of the stream.

        At index 0, returns 1.0
        As index increases, return value approaches 2.0

        @param index: blob position in stream
        @return: front-load multiplier
        """

        return Decimal(2.0) - (self.alpha ** index)
