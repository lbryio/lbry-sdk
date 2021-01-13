from unittest import TestCase
from lbry.blockchain.sync.filter_builder import (
    FilterBuilder as FB, GroupFilter as GF, split_range_into_batches
)


class TestFilterGenerationComponents(TestCase):

    def test_split_range_into_10k_batches(self):
        def split(a, b): return split_range_into_batches(a, b, 10_000)
        # single block (same start-end)
        self.assertEqual(split(901_123, 901_123), [[901_123, 901_123]])
        # spans a 10k split
        self.assertEqual(split(901_123, 911_123), [[901_123, 909_999], [910_000, 911_123]])
        # starts on last element before split
        self.assertEqual(split(909_999, 911_123), [[909_999, 909_999], [910_000, 911_123]])
        # starts on first element after split
        self.assertEqual(split(910_000, 911_123), [[910_000, 911_123]])
        # ends on last element before split
        self.assertEqual(split(901_123, 909_999), [[901_123, 909_999]])
        # ends on first element after split
        self.assertEqual(split(901_123, 910_000), [[901_123, 909_999], [910_000, 910_000]])
        # initial sync from 0 onwards
        self.assertEqual(split(0, 37645), [
            [0, 9_999],
            [10_000, 19_999],
            [20_000, 29_999],
            [30_000, 37645]
        ])

    def test_group_filter_coverage(self):
        # single block (same start-end)
        self.assertEqual(GF(1893, 1898, 2).coverage, [])
        # spans a group split
        self.assertEqual(GF(1893, 1905, 2).coverage, [1800])
        # starts on last element before split and
        self.assertEqual(GF(1799, 1915, 2).coverage, [1700, 1800])
        # starts on first element after split
        self.assertEqual(GF(1800, 1915, 2).coverage, [1800])
        # ends on last element before split
        self.assertEqual(GF(1893, 1899, 2).coverage, [1800])
        # ends on first element after split
        self.assertEqual(GF(1899, 1900, 2).coverage, [1800])
        self.assertEqual(GF(1599, 1899, 2).coverage, [1500, 1600, 1700, 1800])
        self.assertEqual(GF(1600, 1899, 2).coverage, [1600, 1700, 1800])

    def test_group_filter_add_tx(self):
        gf = GF(1898, 2002, 2)
        gf.add(1798, ['a'])  # outside range
        gf.add(1800, ['b'])  # first element in group 1800
        gf.add(1801, ['c'])
        gf.add(1898, ['d'])
        gf.add(1899, ['e'])  # last element in group 1800
        gf.add(1900, ['f'])  # first element in group 1900
        gf.add(1901, ['g'])
        gf.add(2001, ['h'])  # outside range
        self.assertEqual(gf.groups, {
            1800: {'b', 'c', 'd', 'e'},
            1900: {'f', 'g'}
        })

    def test_filter_builder_query_heights(self):
        self.assertEqual(FB(893, 898).query_heights, (893, 898))
        self.assertEqual(FB(893, 899).query_heights, (800, 899))
        self.assertEqual(FB(913, 998).query_heights, (913, 998))
        self.assertEqual(FB(913, 999).query_heights, (0, 999))
        self.assertEqual(FB(1_913, 1_999).query_heights, (1_000, 1_999))
        self.assertEqual(FB(9_913, 9_998).query_heights, (9_913, 9_998))
        self.assertEqual(FB(9_913, 9_999).query_heights, (0, 9_999))
        self.assertEqual(FB(19_913, 19_999).query_heights, (10_000, 19_999))
        self.assertEqual(FB(819_913, 819_999).query_heights, (810_000, 819_999))

    def test_filter_builder_add(self):
        fb = FB(798_813, 809_999)
        self.assertEqual(fb.query_heights, (700_000, 809_999))
        self.assertEqual(fb.group_filters[0].coverage, [700_000])
        self.assertEqual(fb.group_filters[1].coverage, [790_000, 800_000])
        self.assertEqual(fb.group_filters[2].coverage, list(range(798_000, 809_000+1, 1_000)))
        self.assertEqual(fb.group_filters[3].coverage, list(range(798_800, 809_900+1, 100)))
        fb.add(b'beef0', 787_111, ['a'])
        fb.add(b'beef1', 798_222, ['b'])
        fb.add(b'beef2', 798_812, ['c'])
        fb.add(b'beef3', 798_813, ['d'])
        fb.add(b'beef4', 798_814, ['e'])
        fb.add(b'beef5', 809_000, ['f'])
        fb.add(b'beef6', 809_999, ['g'])
        fb.add(b'beef7', 809_999, ['h'])
        fb.add(b'beef8', 820_000, ['i'])
        self.assertEqual(fb.group_filters[0].groups, {
            700_000: {'a', 'b', 'c', 'd', 'e'}
        })
        self.assertEqual(fb.group_filters[1].groups, {
            790_000: {'b', 'c', 'd', 'e'},
            800_000: {'f', 'g', 'h'}
        })
        self.assertEqual(fb.group_filters[2].groups, {
            798_000: {'b', 'c', 'd', 'e'}, 799_000: set(),
            800_000: set(), 801_000: set(), 802_000: set(), 803_000: set(), 804_000: set(),
            805_000: set(), 806_000: set(), 807_000: set(), 808_000: set(),
            809_000: {'f', 'g', 'h'}
        })
        self.assertEqual(fb.group_filters[3].groups[798_800], {'c', 'd', 'e'})
        self.assertEqual(fb.group_filters[3].groups[809_000], {'f'})
        self.assertEqual(fb.group_filters[3].groups[809_900], {'g', 'h'})
        self.assertEqual(fb.block_filters, {798813: {'d'}, 798814: {'e'}, 809000: {'f'}, 809999: {'h', 'g'}})
        self.assertEqual(fb.tx_filters, [
            (b'beef3', 798813, ['d']),
            (b'beef4', 798814, ['e']),
            (b'beef5', 809000, ['f']),
            (b'beef6', 809999, ['g']),
            (b'beef7', 809999, ['h'])
        ])
