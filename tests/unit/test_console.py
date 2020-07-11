import unittest
from lbry.console import Bar2


class TestBar2(unittest.TestCase):

    def bar(self, top, bottom, expected):
        self.assertEqual(expected, f"{Bar2((top, bottom))}")

    def test_rendering(self):
        self.bar(0.00, 0.00, '          ')
        self.bar(0.00, 0.05, '▖         ')
        self.bar(0.05, 0.00, '▘         ')
        self.bar(0.05, 0.05, '▌         ')
        self.bar(0.00, 0.10, '▄         ')
        self.bar(0.10, 0.00, '▀         ')
        self.bar(0.05, 0.10, '▙         ')
        self.bar(0.10, 0.05, '▛         ')
        self.bar(0.30, 0.50, '███▄▄     ')
        self.bar(0.35, 0.55, '███▙▄▖    ')
        self.bar(0.40, 0.60, '████▄▄    ')
        self.bar(0.50, 0.30, '███▀▀     ')
        self.bar(0.55, 0.35, '███▛▀▘    ')
        self.bar(0.60, 0.40, '████▀▀    ')
        self.bar(0.95, 0.90, '█████████▘')
        self.bar(0.99, 0.98, '█████████▌')
        self.bar(0.99, 1.00, '█████████▙')
        self.bar(1.00, 1.00, '██████████')
