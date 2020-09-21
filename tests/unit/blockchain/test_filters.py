from unittest import TestCase
from lbry.blockchain.sync.filter_builder import (
    FilterBuilder as FB, GroupFilter as GF, split_range_into_10k_batches as split
)


class TestFilterGenerationComponents(TestCase):

    def test_split_range_into_10k_batches(self):
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
        fb = FB(818_813, 819_999)
        self.assertEqual(fb.query_heights, (810_000, 819_999))
        self.assertEqual(fb.group_filters[0].coverage, [810_000])
        self.assertEqual(fb.group_filters[1].coverage, [818_000, 819_000])
        self.assertEqual(fb.group_filters[2].coverage, [
            818_800, 818_900, 819_000, 819_100, 819_200, 819_300,
            819_400, 819_500, 819_600, 819_700, 819_800, 819_900
        ])
        fb.add(b'beef0', 810_000, ['a'])
        fb.add(b'beef1', 815_001, ['b'])
        fb.add(b'beef2', 818_412, ['c'])
        fb.add(b'beef3', 818_812, ['d'])
        fb.add(b'beef4', 818_813, ['e'])
        fb.add(b'beef5', 819_000, ['f'])
        fb.add(b'beef6', 819_999, ['g'])
        fb.add(b'beef7', 819_999, ['h'])
        fb.add(b'beef8', 820_000, ['i'])
        self.assertEqual(fb.group_filters[0].groups, {
            810_000: {'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'}
        })
        self.assertEqual(fb.group_filters[1].groups, {
            818_000: {'c', 'd', 'e'},
            819_000: {'f', 'g', 'h'}
        })
        self.assertEqual(fb.group_filters[2].groups[818_800], {'d', 'e'})
        self.assertEqual(fb.group_filters[2].groups[819_000], {'f'})
        self.assertEqual(fb.group_filters[2].groups[819_900], {'g', 'h'})
        self.assertEqual(fb.block_filters, {818813: {'e'}, 819000: {'f'}, 819999: {'g', 'h'}})
        self.assertEqual(fb.tx_filters, [
            (b'beef4', 818813, ['e']),
            (b'beef5', 819000, ['f']),
            (b'beef6', 819999, ['g']),
            (b'beef7', 819999, ['h'])
        ])
