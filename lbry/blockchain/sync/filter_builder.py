from typing import Dict


def split_range_into_10k_batches(start, end):
    batch = [start, end]
    batches = [batch]
    for block in range(start, end+1):
        if 0 < block != batch[0] and block % 10_000 == 0:
            batch = [block, block]
            batches.append(batch)
        else:
            batch[1] = block
    return batches


class GroupFilter:
    """
    Collects addresses into buckets of specific sizes defined by 10 raised to power of factor.
    eg. a factor of 2 (10**2) would create block buckets 100-199, 200-299, etc
        a factor of 3 (10**3) would create block buckets 1000-1999, 2000-2999, etc
    """
    def __init__(self, start, end, factor):
        self.start = start
        self.end = end
        self.factor = factor
        self.resolution = resolution = 10**factor
        last_height_in_group, groups = resolution-1, {}
        for block in range(start, end+1):
            if block % resolution == last_height_in_group:
                groups[block-last_height_in_group] = set()
        self.last_height_in_group = last_height_in_group
        self.groups: Dict[int, set] = groups

    @property
    def coverage(self):
        return list(self.groups.keys())

    def add(self, height, addresses):
        group = self.groups.get(height - (height % self.resolution))
        if group is not None:
            group.update(addresses)


class FilterBuilder:
    """
    Creates filter groups, calculates the necessary block range to fulfill creation
    of filter groups and collects tx filters, block filters and group filters.
    """
    def __init__(self, start, end):
        self.start = start
        self.end = end
        self.group_filters = [
            GroupFilter(start, end, 4),
            GroupFilter(start, end, 3),
            GroupFilter(start, end, 2),
        ]
        self.start_tx_height, self.end_tx_height = self._calculate_tx_heights_for_query()
        self.tx_filters = []
        self.block_filters: Dict[int, set] = {}

    def _calculate_tx_heights_for_query(self):
        for group_filter in self.group_filters:
            if group_filter.groups:
                return group_filter.coverage[0], self.end
        return self.start, self.end

    @property
    def query_heights(self):
        return self.start_tx_height, self.end_tx_height

    def add(self, tx_hash, height, addresses):
        if self.start <= height <= self.end:
            self.tx_filters.append((tx_hash, height, addresses))
            block_filter = self.block_filters.get(height)
            if block_filter is None:
                block_filter = self.block_filters[height] = set()
            block_filter.update(addresses)
        for group_filter in self.group_filters:
            group_filter.add(height, addresses)
