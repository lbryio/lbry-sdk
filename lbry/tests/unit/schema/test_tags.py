import unittest

from lbry.schema.tags import normalize_tag, clean_tags


class TestTagNormalization(unittest.TestCase):

    def assertNormalizedTag(self, clean, dirty):
        self.assertEqual(clean, normalize_tag(dirty))

    def test_normalize_tag(self):
        tag = self.assertNormalizedTag
        tag('', ' \t #!~')
        tag("t'ag", 'T\'ag')
        tag('t ag', '\tT  \nAG   ')
        tag('tag hash', '#tag~#hash!')

    def test_clean_tags(self):
        self.assertEqual(['tag'], clean_tags([' \t #!~', '!taG', '\t']))
        cleaned = clean_tags(['fOo', '!taG', 'FoO'])
        self.assertIn('tag', cleaned)
        self.assertIn('foo', cleaned)
        self.assertEqual(len(cleaned), 2)
