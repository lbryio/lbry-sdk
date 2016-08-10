from lbrynet.core import utils

from twisted.trial import unittest


class CompareVersionTest(unittest.TestCase):
    def test_compare_versions_isnot_lexographic(self):
        self.assertTrue(utils.version_is_greater_than('0.3.10', '0.3.6'))

    def test_same_versions_return_false(self):
        self.assertFalse(utils.version_is_greater_than('1.3.9', '1.3.9'))

    def test_same_release_is_greater_then_beta(self):
        self.assertTrue(utils.version_is_greater_than('1.3.9', '1.3.9b1'))

    def test_version_can_have_four_parts(self):
        self.assertTrue(utils.version_is_greater_than('1.3.9.1', '1.3.9'))
        
    
