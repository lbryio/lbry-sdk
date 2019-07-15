from unittest import TestCase
from decimal import Decimal

from lbry.schema.claim import Claim, Stream


class TestClaimContainerAwareness(TestCase):

    def test_stream_claim(self):
        stream = Stream()
        claim = stream.claim
        self.assertEqual(claim.claim_type, Claim.STREAM)
        claim = Claim.from_bytes(claim.to_bytes())
        self.assertEqual(claim.claim_type, Claim.STREAM)
        self.assertIsNotNone(claim.stream)
        with self.assertRaisesRegex(ValueError, 'Claim is not a channel.'):
            print(claim.channel)


class TestFee(TestCase):

    def test_amount_setters(self):
        stream = Stream()

        stream.fee.lbc = Decimal('1.01')
        self.assertEqual(stream.fee.lbc, Decimal('1.01'))
        self.assertEqual(stream.fee.dewies, 101000000)
        self.assertEqual(stream.fee.currency, 'LBC')
        stream.fee.dewies = 203000000
        self.assertEqual(stream.fee.lbc, Decimal('2.03'))
        self.assertEqual(stream.fee.dewies, 203000000)
        self.assertEqual(stream.fee.currency, 'LBC')
        with self.assertRaisesRegex(ValueError, 'USD can only be returned for USD fees.'):
            print(stream.fee.usd)
        with self.assertRaisesRegex(ValueError, 'Pennies can only be returned for USD fees.'):
            print(stream.fee.pennies)

        stream.fee.usd = Decimal('1.01')
        self.assertEqual(stream.fee.usd, Decimal('1.01'))
        self.assertEqual(stream.fee.pennies, 101)
        self.assertEqual(stream.fee.currency, 'USD')
        stream.fee.pennies = 203
        self.assertEqual(stream.fee.usd, Decimal('2.03'))
        self.assertEqual(stream.fee.pennies, 203)
        self.assertEqual(stream.fee.currency, 'USD')
        with self.assertRaisesRegex(ValueError, 'LBC can only be returned for LBC fees.'):
            print(stream.fee.lbc)
        with self.assertRaisesRegex(ValueError, 'Dewies can only be returned for LBC fees.'):
            print(stream.fee.dewies)


class TestLanguages(TestCase):

    def test_language_successful_parsing(self):
        stream = Stream()

        stream.languages.append('en')
        self.assertEqual(stream.languages[0].langtag, 'en')
        self.assertEqual(stream.languages[0].language, 'en')
        self.assertEqual(stream.langtags, ['en'])

        stream.languages.append('en-US')
        self.assertEqual(stream.languages[1].langtag, 'en-US')
        self.assertEqual(stream.languages[1].language, 'en')
        self.assertEqual(stream.languages[1].region, 'US')
        self.assertEqual(stream.langtags, ['en', 'en-US'])

        stream.languages.append('en-Latn-US')
        self.assertEqual(stream.languages[2].langtag, 'en-Latn-US')
        self.assertEqual(stream.languages[2].language, 'en')
        self.assertEqual(stream.languages[2].script, 'Latn')
        self.assertEqual(stream.languages[2].region, 'US')
        self.assertEqual(stream.langtags, ['en', 'en-US', 'en-Latn-US'])

        stream.languages.append('es-419')
        self.assertEqual(stream.languages[3].langtag, 'es-419')
        self.assertEqual(stream.languages[3].language, 'es')
        self.assertEqual(stream.languages[3].script, None)
        self.assertEqual(stream.languages[3].region, '419')
        self.assertEqual(stream.langtags, ['en', 'en-US', 'en-Latn-US', 'es-419'])

        stream = Stream()
        stream.languages.extend(['en-Latn-US', 'es-ES', 'de-DE'])
        self.assertEqual(stream.languages[0].language, 'en')
        self.assertEqual(stream.languages[1].language, 'es')
        self.assertEqual(stream.languages[2].language, 'de')

    def test_language_error_parsing(self):
        stream = Stream()
        with self.assertRaisesRegex(ValueError, 'Language has no value defined for name zz'):
            stream.languages.append('zz')
        with self.assertRaisesRegex(ValueError, 'Script has no value defined for name Zabc'):
            stream.languages.append('en-Zabc')
        with self.assertRaisesRegex(ValueError, 'Country has no value defined for name ZZ'):
            stream.languages.append('en-Zzzz-ZZ')
        with self.assertRaisesRegex(AssertionError, 'Failed to parse language tag: en-Zzz-US'):
            stream.languages.append('en-Zzz-US')


class TestLocations(TestCase):

    def test_location_successful_parsing(self):
        # from simple string
        stream = Stream()
        stream.locations.append('US')
        self.assertEqual(stream.locations[0].country, 'US')

        # from full string
        stream = Stream()
        stream.locations.append('US:NH:Manchester:03101:42.990605:-71.460989')
        self.assertEqual(stream.locations[0].country, 'US')
        self.assertEqual(stream.locations[0].state, 'NH')
        self.assertEqual(stream.locations[0].city, 'Manchester')
        self.assertEqual(stream.locations[0].code, '03101')
        self.assertEqual(stream.locations[0].latitude, '42.990605')
        self.assertEqual(stream.locations[0].longitude, '-71.460989')

        # from partial string
        stream = Stream()
        stream.locations.append('::Manchester:03101:')
        self.assertEqual(stream.locations[0].country, None)
        self.assertEqual(stream.locations[0].state, '')
        self.assertEqual(stream.locations[0].city, 'Manchester')
        self.assertEqual(stream.locations[0].code, '03101')
        self.assertEqual(stream.locations[0].latitude, None)
        self.assertEqual(stream.locations[0].longitude, None)

        # from partial string lat/long
        stream = Stream()
        stream.locations.append('::::42.990605:-71.460989')
        self.assertEqual(stream.locations[0].country, None)
        self.assertEqual(stream.locations[0].state, '')
        self.assertEqual(stream.locations[0].city, '')
        self.assertEqual(stream.locations[0].code, '')
        self.assertEqual(stream.locations[0].latitude, '42.990605')
        self.assertEqual(stream.locations[0].longitude, '-71.460989')

        # from short circuit lat/long
        stream = Stream()
        stream.locations.append('42.990605:-71.460989')
        self.assertEqual(stream.locations[0].country, None)
        self.assertEqual(stream.locations[0].state, '')
        self.assertEqual(stream.locations[0].city, '')
        self.assertEqual(stream.locations[0].code, '')
        self.assertEqual(stream.locations[0].latitude, '42.990605')
        self.assertEqual(stream.locations[0].longitude, '-71.460989')

        # from json string
        stream = Stream()
        stream.locations.append('{"country": "ES"}')
        self.assertEqual(stream.locations[0].country, 'ES')

        # from dict
        stream = Stream()
        stream.locations.append({"country": "UA"})
        self.assertEqual(stream.locations[0].country, 'UA')
