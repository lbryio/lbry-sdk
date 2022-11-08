from unittest import TestCase
from decimal import Decimal
import json

from lbry.schema.claim import Claim, Stream, Collection
from lbry.schema.attrs import StreamExtension, StringMapMessage
from lbry.error import InputValueIsNoneError
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.any_pb2 import Any as AnyMessage
from google.protobuf.proto_builder import MakeSimpleProtoClass
from google.protobuf.descriptor_pb2 import FieldDescriptorProto

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
        self.assertIsNone(stream.languages[3].script)
        self.assertEqual(stream.languages[3].region, '419')
        self.assertEqual(stream.langtags, ['en', 'en-US', 'en-Latn-US', 'es-419'])

        stream = Stream()
        stream.languages.extend(['en-Latn-US', 'es-ES', 'de-DE'])
        self.assertEqual(stream.languages[0].language, 'en')
        self.assertEqual(stream.languages[1].language, 'es')
        self.assertEqual(stream.languages[2].language, 'de')

    def test_language_error_parsing(self):
        stream = Stream()
        with self.assertRaisesRegex(ValueError, "Enum Language has no value defined for name 'zz'"):
            stream.languages.append('zz')
        with self.assertRaisesRegex(ValueError, "Enum Script has no value defined for name 'Zabc'"):
            stream.languages.append('en-Zabc')
        with self.assertRaisesRegex(ValueError, "Enum Country has no value defined for name 'ZZ'"):
            stream.languages.append('en-Zzzz-ZZ')
        with self.assertRaisesRegex(AssertionError, "Failed to parse language tag: en-Zzz-US"):
            stream.languages.append('en-Zzz-US')


class TestTags(TestCase):

    def test_normalize_tags(self):
        claim = Claim()

        claim.channel.update(tags=['Anime', 'anime', ' aNiMe', 'maNGA '])
        self.assertCountEqual(claim.channel.tags, ['anime', 'manga'])

        claim.channel.update(tags=['Juri', 'juRi'])
        self.assertCountEqual(claim.channel.tags, ['anime', 'manga', 'juri'])

        claim.channel.update(tags='Anime')
        self.assertCountEqual(claim.channel.tags, ['anime', 'manga', 'juri'])

        claim.channel.update(clear_tags=True)
        self.assertEqual(len(claim.channel.tags), 0)

        claim.channel.update(tags='Anime')
        self.assertEqual(claim.channel.tags, ['anime'])


class TestCollection(TestCase):

    def test_collection(self):
        collection = Collection()

        collection.update(claims=['abc123', 'def123'])
        self.assertListEqual(collection.claims.ids, ['abc123', 'def123'])

        collection.update(claims=['abc123', 'bbb123'])
        self.assertListEqual(collection.claims.ids, ['abc123', 'def123', 'abc123', 'bbb123'])

        collection.update(clear_claims=True, claims=['bbb987', 'bb'])
        self.assertListEqual(collection.claims.ids, ['bbb987', 'bb'])

        self.assertEqual(collection.to_dict(), {'claims': ['bbb987', 'bb']})

        collection.update(clear_claims=True)
        self.assertListEqual(collection.claims.ids, [])


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
        self.assertIsNone(stream.locations[0].country)
        self.assertEqual(stream.locations[0].state, '')
        self.assertEqual(stream.locations[0].city, 'Manchester')
        self.assertEqual(stream.locations[0].code, '03101')
        self.assertIsNone(stream.locations[0].latitude)
        self.assertIsNone(stream.locations[0].longitude)

        # from partial string lat/long
        stream = Stream()
        stream.locations.append('::::42.990605:-71.460989')
        self.assertIsNone(stream.locations[0].country)
        self.assertEqual(stream.locations[0].state, '')
        self.assertEqual(stream.locations[0].city, '')
        self.assertEqual(stream.locations[0].code, '')
        self.assertEqual(stream.locations[0].latitude, '42.990605')
        self.assertEqual(stream.locations[0].longitude, '-71.460989')

        # from short circuit lat/long
        stream = Stream()
        stream.locations.append('42.990605:-71.460989')
        self.assertIsNone(stream.locations[0].country)
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


class TestStreamUpdating(TestCase):

    def test_stream_update(self):
        stream = Stream()
        # each of these values is set differently inside of .update()
        stream.update(
            title="foo",
            thumbnail_url="somescheme:some/path",
            file_name="file-name"
        )
        self.assertEqual(stream.title, "foo")
        self.assertEqual(stream.thumbnail.url, "somescheme:some/path")
        self.assertEqual(stream.source.name, "file-name")
        with self.assertRaises(InputValueIsNoneError):
            stream.update(title=None)
        with self.assertRaises(InputValueIsNoneError):
            stream.update(file_name=None)
        with self.assertRaises(InputValueIsNoneError):
            stream.update(thumbnail_url=None)

class TestExtensionUpdating(TestCase):

    def setUp(self):
        self.cad1 = StringMapMessage()
        self.schema1 = 'cad'
        self.cad1.s['material'].vs.append('PLA1')
        self.cad1.s['material'].vs.append('PLA2')
        self.cad1.s['cubic_cm'].vs.append('5')
        self.schema1 = 'cad'
        self.ext1 = AnyMessage()
        self.ext1.Pack(self.cad1, type_url_prefix='')
        self.ext1 = StreamExtension('cad', self.ext1)
        self.ext1_dict = {'cad': {'material': ['PLA1', 'PLA2'], 'cubic_cm': '5'}}
        self.ext1_json = json.dumps(self.ext1_dict)

        self.mus1 = StringMapMessage()
        self.schema2 = 'music'
        self.mus1.s['venue'].vs.append('studio')
        self.mus1.s['genre'].vs.append('metal')
        self.mus1.s['instrument'].vs.append('drum')
        self.mus1.s['instrument'].vs.append('cymbal')
        self.mus1.s['instrument'].vs.append('guitar')
        self.ext2 = AnyMessage()
        self.ext2.Pack(self.mus1, type_url_prefix='')
        self.ext2 = StreamExtension('music', self.ext2)
        self.ext2_dict = {'music': {'genre': 'metal', 'venue': 'studio', 'instrument': ['drum', 'cymbal', 'guitar']}}
        self.ext2_json = json.dumps(self.ext2_dict)

        self.lit1 = StringMapMessage()
        self.schema3 = 'lit'
        self.lit1.s['pages'].vs.append('185')
        self.lit1.s['genre'].vs.append('fiction')
        self.lit1.s['genre'].vs.append('mystery')
        self.lit1.s['format'].vs.append('epub')
        self.ext3 = AnyMessage()
        self.ext3.Pack(self.lit1, type_url_prefix='')
        self.ext3 = StreamExtension('lit', self.ext3)
        self.ext3_dict = {'lit': {'genre': ['fiction', 'mystery'], 'format': 'epub', 'pages': '185'}}
        self.ext3_json = json.dumps(self.ext3_dict)

    def test_extension_unresolved_type(self):
        self.maxDiff = None

        # Empty instance produces an error.
        bad0 = StreamExtension(None, AnyMessage())
        self.assertEqual(bad0.to_dict(), {'None': {'error': "Stream extension type '/' could not be resolved."}}, bad0.to_dict())
        # Empty instance can be initialized.
        bad0.from_value({'new': {'foo': '101'}})
        self.assertEqual(bad0.to_dict(), {'new': {'foo': '101'}}, bad0.to_dict())

        # Construct a new protobuf message according to a NEW schema
        # not in our descriptor pool.
        cls = MakeSimpleProtoClass(
            {'a': FieldDescriptorProto.TYPE_INT64, 'b': FieldDescriptorProto.TYPE_STRING},
            full_name='pb.NewMessage'
        )
        new = cls()
        new.a = 101
        new.b = 'property b value'
        bad1 = AnyMessage()
        bad1.Pack(new, type_url_prefix='')

        # String representation with type_url and encoded value can be printed.
        self.assertEqual(str(bad1), 'type_url: "/pb.NewMessage"\nvalue: "\\010e\\022\\020property b value"\n', str(bad1))
        self.assertEqual(bad1.SerializeToString(), b'\n\x0e/pb.NewMessage\x12\x14\x08e\x12\x10property b value')

        # Create a stream with a bad extension whose type is unknown to us.
        stream = Stream()
        stream.update(extensions=self.ext1.to_dict())
        stream.update(extensions={'new': {}})
        stream.message.extensions['new'].Pack(new, type_url_prefix='')
        stream.update(extensions=self.ext3.to_dict())

        # Although the bad extension can't be decoded the way we would like,
        # it is still possible to see the other two extensions.
        self.assertEqual(
            stream.to_dict(),
            {'extensions': {
                'cad': {
                    'material': ['PLA1', 'PLA2'],
                    'cubic_cm': '5',
                },
                'lit': {
                    'genre': ['fiction', 'mystery'],
                    'format': 'epub',
                    'pages': '185'
                },
                'new': {
                    'error': "Stream extension type '/pb.NewMessage' could not be resolved."
                }
            }},
            stream.to_dict()
        )

        # Updates to bad extension are ignored.
        stream.update(extensions={'new': {'foo': '101'}})
        self.assertEqual(
            stream.to_dict(),
            {'extensions': {
                'cad': {
                    'material': ['PLA1', 'PLA2'],
                    'cubic_cm': '5',
                },
                'lit': {
                    'genre': ['fiction', 'mystery'],
                    'format': 'epub',
                    'pages': '185'
                },
                'new': {
                    'error': "Stream extension type '/pb.NewMessage' could not be resolved."
                }
            }},
            stream.to_dict()
        )

        # Bad extension can be cleared.
        stream.update(clear_extensions={'new': {}})
        self.assertEqual(
            stream.to_dict(),
            {'extensions': {
                'cad': {
                    'material': ['PLA1', 'PLA2'],
                    'cubic_cm': '5',
                },
                'lit': {
                    'genre': ['fiction', 'mystery'],
                    'format': 'epub',
                    'pages': '185'
                },
            }},
            stream.to_dict()
        )


    def test_extension_properties(self):
        self.maxDiff = None
        # Verify schema.
        self.assertEqual(self.ext1.schema, 'cad')
        self.assertEqual(self.ext2.schema, 'music')
        self.assertEqual(self.ext3.schema, 'lit')
        # Verify to_dict().
        self.assertEqual(self.ext1.to_dict(), self.ext1_dict)
        self.assertEqual(self.ext2.to_dict(), self.ext2_dict)
        self.assertEqual(self.ext3.to_dict(), self.ext3_dict)
        # Decode from dict.
        parsed1 = StreamExtension(None, AnyMessage())
        parsed1.from_value(self.ext1_dict)
        self.assertEqual(parsed1.to_dict(), self.ext1_dict)
        parsed2 = StreamExtension(None, AnyMessage())
        parsed2.from_value(self.ext2_dict)
        self.assertEqual(parsed2.to_dict(), self.ext2_dict)
        parsed3 = StreamExtension(None, AnyMessage())
        parsed3.from_value(self.ext3_dict)
        self.assertEqual(parsed3.to_dict(), self.ext3_dict)
        # Decode from str (JSON).
        parsed1 = StreamExtension(None, AnyMessage())
        parsed1.from_value(self.ext1_json)
        self.assertEqual(parsed1.to_dict(), self.ext1_dict)
        parsed2 = StreamExtension(None, AnyMessage())
        parsed2.from_value(self.ext2_json)
        self.assertEqual(parsed2.to_dict(), self.ext2_dict)
        parsed3 = StreamExtension(None, AnyMessage())
        parsed3.from_value(self.ext3_json)
        self.assertEqual(parsed3.to_dict(), self.ext3_dict)

    def test_extension_clear_field(self):
        self.maxDiff = None
        ext = StreamExtension(None, AnyMessage())
        ext.from_value(self.ext1_dict)
        mod = StreamExtension(None, AnyMessage())
        # Delete non-existent item does nothing
        mod.from_value({ext.schema: {'material': 'PLA3'}})
        self.assertEqual(ext.merge(mod, delete=True).to_dict(), self.ext1_dict)
        # Delete one item.
        mod.from_value({ext.schema: {'material': 'PLA1'}})
        self.assertEqual(ext.merge(mod, delete=True).to_dict(), {'cad': {'material': 'PLA2', 'cubic_cm': '5'}})
        # Delete non-existent key.
        mod.from_value({ext.schema: {'size': []}})
        self.assertEqual(ext.merge(mod, delete=True).to_dict(), {'cad': {'material': 'PLA2', 'cubic_cm': '5'}})
        # Delete one key.
        mod.from_value({ext.schema: {'cubic_cm': []}})
        self.assertEqual(ext.merge(mod, delete=True).to_dict(), {'cad': {'material': 'PLA2'}})
        ext = StreamExtension(None, AnyMessage())
        ext.from_value(self.ext2_dict)
        mod = StreamExtension(None, AnyMessage())
        # Delete non-existent item does nothing
        mod.from_value({ext.schema: {'genre': 'rap'}})
        self.assertEqual(ext.merge(mod, delete=True).to_dict(), self.ext2_dict)
        # Delete one item.
        mod.from_value({ext.schema: {'instrument': 'guitar'}})
        self.assertEqual(ext.merge(mod, delete=True).to_dict(), {'music': {'genre': 'metal', 'venue': 'studio', 'instrument': ['drum', 'cymbal']}})
        # Delete non-existent key.
        mod.from_value({ext.schema: {'format': []}})
        self.assertEqual(ext.merge(mod, delete=True).to_dict(), {'music': {'genre': 'metal', 'venue': 'studio', 'instrument': ['drum', 'cymbal']}})
        # Delete one key.
        mod.from_value({ext.schema: {'instrument': ['drum']}})
        self.assertEqual(ext.merge(mod, delete=True).to_dict(), {'music': {'genre': 'metal', 'venue': 'studio', 'instrument': 'cymbal'}})

    def test_extension_set_field(self):
        self.maxDiff = None
        ext = StreamExtension(None, AnyMessage())
        ext.from_value(self.ext1_dict)
        mod = StreamExtension(None, AnyMessage())
        # Add item within existing key.
        mod.from_value({ext.schema: {'material': 'PLA3'}})
        self.assertEqual(ext.merge(mod).to_dict(), {'cad': {'material': ['PLA1', 'PLA2', 'PLA3'], 'cubic_cm': '5'}})
        # Add key with multiple items.
        mod.from_value({ext.schema: {'tool': ['drill', 'printer']}})
        self.assertEqual(ext.merge(mod).to_dict(), {'cad': {'material': ['PLA1', 'PLA2', 'PLA3'], 'tool': ['drill', 'printer'], 'cubic_cm': '5'}})
        # Add items within multiple keys.
        mod.from_value({ext.schema: {'tool': 'file', 'material': 'glue'}})
        self.assertEqual(ext.merge(mod).to_dict(), {'cad': {'material': ['PLA1', 'PLA2', 'PLA3', 'glue'], 'tool': ['drill', 'printer', 'file'], 'cubic_cm': '5'}})
        ext = StreamExtension(None, AnyMessage())
        ext.from_value(self.ext3_dict)
        mod = StreamExtension(None, AnyMessage())
        # Add item within existing key.
        mod.from_value({ext.schema: {'genre': 'scifi'}})
        self.assertEqual(ext.merge(mod).to_dict(), {'lit': {'genre': ['fiction', 'mystery', 'scifi'], 'format': 'epub', 'pages': '185'}})
        # Add key with multiple items.
        mod.from_value({ext.schema: {'toc': ['Intro', 'Chapter 1']}})
        self.assertEqual(ext.merge(mod).to_dict(), {'lit': {'genre': ['fiction', 'mystery', 'scifi'], 'format': 'epub', 'toc': ['Intro', 'Chapter 1'], 'pages': '185'}})
        # Add items within multiple keys.
        mod.from_value({ext.schema: {'toc': ['Chapter 2', 'Chapter 3'], 'genre': 'cyberpunk'}})
        self.assertEqual(ext.merge(mod).to_dict(), {'lit': {'genre': ['fiction', 'mystery', 'scifi', 'cyberpunk'], 'format': 'epub', 'toc': ['Intro', 'Chapter 1', 'Chapter 2', 'Chapter 3'], 'pages': '185'}})

    def test_stream_extension_update(self):
        self.maxDiff = None
        stream = Stream()

        # Add "cad".
        stream.update(extensions=self.ext1.to_dict())
        self.assertEqual(
            stream.to_dict(),
            {'extensions': {
                'cad': {
                    'material': ['PLA1', 'PLA2'],
                    'cubic_cm': '5',
                }
            }},
            stream.to_dict()
        )

        # Add "music".
        stream.update(extensions=self.ext2.to_dict())
        self.assertEqual(
            stream.to_dict(),
            {'extensions': {
                'cad': {
                    'material': ['PLA1', 'PLA2'],
                    'cubic_cm': '5',
                },
                'music': {
                    'genre': 'metal',
                    'venue': 'studio',
                    'instrument': ['drum', 'cymbal', 'guitar'],
                },
            }},
            stream.to_dict()
        )

        # Patch "music", changing "venue".
        stream.update(
            clear_extensions=['{"music": {"venue": ["studio"]}}'],
            extensions=['{"music": {"venue": ["live"]}}'],
        )
        self.assertEqual(
            stream.to_dict(),
            {'extensions': {
                'cad': {
                    'material': ['PLA1', 'PLA2'],
                    'cubic_cm': '5',
                },
                'music': {
                    'genre': 'metal',
                    'venue': 'studio',
                    'instrument': ['drum', 'cymbal', 'guitar'],
                },
            }},
            stream.to_dict()
        )

        # Remove "cad".
        stream.update(
            clear_extensions='{"cad": {}}',
        )
        self.assertEqual(
            stream.to_dict(),
            {'extensions': {
                'music': {
                    'genre': 'metal',
                    'venue': 'studio',
                    'instrument': ['drum', 'cymbal', 'guitar'],
                },
            }},
            stream.to_dict()
        )
