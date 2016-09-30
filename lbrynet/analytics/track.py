import collections


class Track(object):
    """Track and summarize observations of metrics."""
    def __init__(self):
        self.data = collections.defaultdict(list)

    def add_observation(self, metric, value):
        self.data[metric].append(value)

    def summarize(self, metric, op=sum):
        """Apply `op` on the current values for `metric`.

        This operation also resets the metric.
        """
        return op(self.data.pop(metric, []))
