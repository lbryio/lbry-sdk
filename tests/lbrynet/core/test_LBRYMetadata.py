import mock
from lbrynet.core import LBRYMetadata

from twisted.trial import unittest


class LBRYFeeFormatTest(unittest.TestCase):
    def test_fee_created_with_correct_inputs(self):
        fee_dict = {
            'USD': {
                'amount': 10,
                'address': None
            }
        }
        fee = LBRYMetadata.LBRYFeeValidator(fee_dict)
        self.assertEqual(10, fee['USD']['amount'])


class LBRYFeeTest(unittest.TestCase):
    def setUp(self):
        self.patcher = mock.patch('time.time')
        self.time = self.patcher.start()
        self.time.return_value = 0

    def tearDown(self):
        self.time.stop()

    def test_fee_converts_to_lbc(self):
        fee_dict = {
            'USD': {
                'amount': 10,
                'address': None
            }
        }
        rates = {'BTCLBC': {'spot': 3, 'ts': 2}, 'USDBTC': {'spot': 2, 'ts': 3}}
        fee = LBRYMetadata.LBRYFee(fee_dict, rates, 0)
        self.assertEqual(60, fee.to_lbc())


class MetadataTest(unittest.TestCase):
    def test_assertion_if_source_is_missing(self):
        metadata = {}
        with self.assertRaises(AssertionError):
            LBRYMetadata.Metadata(metadata)

    def test_assertion_if_invalid_source(self):
        metadata = {
            'sources': {'garbage': None}
        }
        with self.assertRaises(AssertionError):
            LBRYMetadata.Metadata(metadata)

    def test_assertion_if_missing_v001_field(self):
        metadata = {
            'sources': [],
        }
        with self.assertRaises(AssertionError):
            LBRYMetadata.Metadata(metadata)

    def test_version_is_001_if_all_fields_are_present(self):
        metadata = {
            'sources': [],
            'title': None,
            'description': None,
            'author': None,
            'language': None,
            'license': None,
            'content-type': None,
        }
        m = LBRYMetadata.Metadata(metadata)
        self.assertEquals('0.0.1', m.meta_version)

    def test_assertion_if_there_is_an_extra_field(self):
        metadata = {
            'sources': [],
            'title': None,
            'description': None,
            'author': None,
            'language': None,
            'license': None,
            'content-type': None,
            'extra': None
        }
        with self.assertRaises(AssertionError):
            LBRYMetadata.Metadata(metadata)

    def test_version_is_002_if_all_fields_are_present(self):
        metadata = {
            'sources': [],
            'title': None,
            'description': None,
            'author': None,
            'language': None,
            'license': None,
            'content-type': None,
            'nsfw': None,
            'ver': None
        }
        m = LBRYMetadata.Metadata(metadata)
        self.assertEquals('0.0.2', m.meta_version)


