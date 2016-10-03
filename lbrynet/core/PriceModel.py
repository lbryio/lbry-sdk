from lbrynet.conf import MIN_BLOB_DATA_PAYMENT_RATE


def get_default_price_model(blob_tracker, **kwargs):
    return MeanAvailabilityWeightedPrice(blob_tracker, **kwargs)


class MeanAvailabilityWeightedPrice(object):
    """
    Calculate mean-blob-availability and stream-position weighted price for a blob

    Attributes:
        min_price (float): minimum accepted price
        base_price (float): base price to shift from
        alpha (float): constant used to more highly value blobs at the beginning of a stream
                        alpha defaults to 1.0, which has a null effect
        blob_tracker (BlobAvailabilityTracker): blob availability tracker
    """

    def __init__(self, tracker, base_price=MIN_BLOB_DATA_PAYMENT_RATE, alpha=1.0):
        self.blob_tracker = tracker
        self.base_price = base_price
        self.alpha = alpha

    def calculate_price(self, blob):
        mean_availability = self.blob_tracker.last_mean_availability
        availability = self.blob_tracker.availability.get(blob, [])
        index = 0  # blob.index
        price = self.base_price * (mean_availability / max(1, len(availability))) / self._frontload(index)
        return round(price, 5)

    def _frontload(self, index):
        """
        Get frontload multipler

        @param index: blob position in stream
        @return: frontload multipler
        """

        return 2.0 - (self.alpha ** index)
