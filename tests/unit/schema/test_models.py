from unittest import TestCase
from decimal import Decimal

from lbrynet.schema.claim import Claim, Channel, Stream


class TestClaimContainerAwareness(TestCase):

    def test_stream_claim(self):
        stream = Stream()
        claim = stream.claim
        self.assertTrue(claim.is_stream)
        self.assertFalse(claim.is_channel)
        claim = Claim.from_bytes(claim.to_bytes())
        self.assertTrue(claim.is_stream)
        self.assertFalse(claim.is_channel)
        self.assertIsNotNone(claim.stream)
        with self.assertRaisesRegex(ValueError, 'Claim is not a channel.'):
            print(claim.channel)

    def test_channel_claim(self):
        channel = Channel()
        claim = channel.claim
        self.assertFalse(claim.is_stream)
        self.assertTrue(claim.is_channel)
        claim = Claim.from_bytes(claim.to_bytes())
        self.assertFalse(claim.is_stream)
        self.assertTrue(claim.is_channel)
        self.assertIsNotNone(claim.channel)
        with self.assertRaisesRegex(ValueError, 'Claim is not a stream.'):
            print(claim.stream)


class TestFee(TestCase):

    def test_amount_setters(self):
        stream = Stream()

        stream.fee.lbc = Decimal('1.01')
        self.assertEqual(stream.fee.lbc, Decimal('1.01'))
        self.assertEqual(stream.fee.dewies, 101000000)
        self.assertEqual(stream.fee.currency, 'LBC')
        with self.assertRaisesRegex(ValueError, 'USD can only be returned for USD fees.'):
            print(stream.fee.usd)

        stream.fee.usd = Decimal('1.01')
        self.assertEqual(stream.fee.usd, Decimal('1.01'))
        self.assertEqual(stream.fee.currency, 'USD')
        with self.assertRaisesRegex(ValueError, 'LBC can only be returned for LBC fees.'):
            print(stream.fee.lbc)
        with self.assertRaisesRegex(ValueError, 'Dewies can only be returned for LBC fees.'):
            print(stream.fee.dewies)
