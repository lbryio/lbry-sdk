#!/usr/bin/env python
# -*- coding: utf-8 -*-

import ecdsa
import binascii
from copy import deepcopy
import unittest

from .test_data import example_003, example_010, example_010_serialized
from .test_data import claim_id_1, claim_address_1, claim_address_2
from .test_data import binary_claim, expected_binary_claim_decoded
from .test_data import nist256p_private_key, claim_010_signed_nist256p, nist256p_cert
from .test_data import nist384p_private_key, claim_010_signed_nist384p, nist384p_cert
from .test_data import secp256k1_private_key, claim_010_signed_secp256k1, secp256k1_cert
from .test_data import hex_encoded_003, decoded_hex_encoded_003, malformed_secp256k1_cert
from lbrynet import schema
from lbrynet.schema.claim import ClaimDict
from lbrynet.schema.schema import NIST256p, NIST384p, SECP256k1
from lbrynet.schema.legacy.migrate import migrate
from lbrynet.schema.signer import get_signer
from lbrynet.schema.uri import URI, URIParseError
from lbrynet.schema.decode import smart_decode
from lbrynet.schema.error import DecodeError, InvalidAddress
from lbrynet.schema.address import decode_address, encode_address


parsed_uri_matches = [
    ("test", URI("test"), False, False, "test", None),
    ("test#%s" % claim_id_1, URI("test", claim_id=claim_id_1), False, False, "test", None),
    ("test:1", URI("test", claim_sequence=1), False, False, "test", None),
    ("test$1", URI("test", bid_position=1), False, False, "test", None),
    ("lbry://test", URI("test"), False, False, "test", None),
    ("lbry://test#%s" % claim_id_1, URI("test", claim_id=claim_id_1), False, False, "test", None),
    ("lbry://test:1", URI("test", claim_sequence=1), False, False, "test", None),
    ("lbry://test$1", URI("test", bid_position=1), False, False, "test", None),
    ("@test", URI("@test"), True, True, None, "@test"),
    ("@test#%s" % claim_id_1, URI("@test", claim_id=claim_id_1), True, True, None, "@test"),
    ("@test:1", URI("@test", claim_sequence=1), True, True, None, "@test"),
    ("@test$1", URI("@test", bid_position=1), True, True, None, "@test"),
    ("lbry://@test1:1/fakepath", URI("@test1", claim_sequence=1, path="fakepath"), True, False, "fakepath", "@test1"),
    ("lbry://@test1$1/fakepath", URI("@test1", bid_position=1, path="fakepath"), True, False, "fakepath", "@test1"),
    ("lbry://@test1#abcdef/fakepath", URI("@test1", claim_id="abcdef", path="fakepath"), True, False, "fakepath",
     "@test1"),
    ("@z", URI("@z"), True, True, None, "@z"),
    ("@yx", URI("@yx"), True, True, None, "@yx"),
    ("@abc", URI("@abc"), True, True, None, "@abc")
]

parsed_uri_raises = [
    ("lbry://", URIParseError),
    ("lbry://test:3$1", URIParseError),
    ("lbry://test$1:1", URIParseError),
    ("lbry://test#x", URIParseError),
    ("lbry://test#x/page", URIParseError),
    ("lbry://test$", URIParseError),
    ("lbry://test#", URIParseError),
    ("lbry://test:", URIParseError),
    ("lbry://test$x", URIParseError),
    ("lbry://test:x", URIParseError),
    ("lbry://@test@", URIParseError),
    ("lbry://@test:", URIParseError),
    ("lbry://test@", URIParseError),
    ("lbry://tes@t", URIParseError),
    ("lbry://test:1#%s" % claim_id_1, URIParseError),
    ("lbry://test:0", URIParseError),
    ("lbry://test$0", URIParseError),
    ("lbry://test/path", URIParseError),
    ("lbry://@test1#abcdef/fakepath:1", URIParseError),
    ("lbry://@test1:1/fakepath:1", URIParseError),
    ("lbry://@test1:1ab/fakepath", URIParseError),
    ("lbry://test:1:1:1", URIParseError),
    ("whatever/lbry://test", URIParseError),
    ("lbry://lbry://test", URIParseError),
    ("lbry://❀", URIParseError),
    ("lbry://@/what", URIParseError),
    ("lbry://abc:0x123", URIParseError),
    ("lbry://abc:0x123/page", URIParseError),
    ("lbry://@test1#ABCDEF/fakepath", URIParseError),
    ("test:0001", URIParseError),
    ("lbry://@test1$1/fakepath?arg1&arg2&arg3", URIParseError)
]


class UnitTest(unittest.TestCase):
    maxDiff = 4000


class TestURIParser(UnitTest):
    def setUp(self):
        self.longMessage = True

    def test_uri_parse(self):
        for test_string, expected_uri_obj, contains_channel, is_channel, claim_name, channel_name in parsed_uri_matches:
            try:
                # string -> URI
                self.assertEqual(URI.from_uri_string(test_string), expected_uri_obj, test_string)
                # URI -> dict -> URI
                self.assertEqual(URI.from_dict(expected_uri_obj.to_dict()), expected_uri_obj,
                                  test_string)
                # contains_channel
                self.assertEqual(URI.from_uri_string(test_string).contains_channel, contains_channel,
                                  test_string)
                # is_channel
                self.assertEqual(URI.from_uri_string(test_string).is_channel, is_channel,
                                  test_string)
                # claim_name
                self.assertEqual(URI.from_uri_string(test_string).claim_name, claim_name,
                                  test_string)
                # channel_name
                self.assertEqual(URI.from_uri_string(test_string).channel_name, channel_name,
                                  test_string)

                # convert-to-string test only works if protocol is present in test_string
                if test_string.startswith('lbry://'):
                    # string -> URI -> string
                    self.assertEqual(URI.from_uri_string(test_string).to_uri_string(), test_string,
                                      test_string)
                    # string -> URI -> dict -> URI -> string
                    uri_dict = URI.from_uri_string(test_string).to_dict()
                    self.assertEqual(URI.from_dict(uri_dict).to_uri_string(), test_string,
                                      test_string)
                    # URI -> dict -> URI -> string
                    self.assertEqual(URI.from_dict(expected_uri_obj.to_dict()).to_uri_string(),
                                      test_string, test_string)
            except URIParseError as err:
                print("ERROR: " + test_string)
                raise

    def test_uri_errors(self):
        for test_str, err in parsed_uri_raises:
            try:
                URI.from_uri_string(test_str)
            except URIParseError:
                pass
            else:
                print("\nSuccessfully parsed invalid url: " + test_str)
            self.assertRaises(err, URI.from_uri_string, test_str)


class TestEncoderAndDecoder(UnitTest):
    def test_encode_decode(self):
        test_claim = ClaimDict.load_dict(example_010)
        self.assertEqual(test_claim.is_certificate, False)
        self.assertDictEqual(test_claim.claim_dict, example_010)
        test_pb = test_claim.protobuf
        self.assertDictEqual(ClaimDict.load_protobuf(test_pb).claim_dict, example_010)
        self.assertEqual(test_pb.ByteSize(), ClaimDict.load_protobuf(test_pb).protobuf_len)
        self.assertEqual(test_claim.json_len, ClaimDict.load_protobuf(test_pb).json_len)

    def test_deserialize(self):
        deserialized_claim = ClaimDict.deserialize(binascii.unhexlify(example_010_serialized))
        self.assertDictEqual(ClaimDict.load_dict(example_010).claim_dict,
                             deserialized_claim.claim_dict)

    def test_stream_is_not_certificate(self):
        deserialized_claim = ClaimDict.deserialize(binascii.unhexlify(example_010_serialized))
        self.assertEqual(deserialized_claim.is_certificate, False)


class TestISO639(UnitTest):
    def test_alpha2(self):
        prefixes = ['en', 'aa', 'ab', 'ae', 'af', 'ak', 'am', 'an', 'ar', 'as', 'av', 'ay', 'az',
                    'ba', 'be', 'bg', 'bh', 'bi', 'bm', 'bn', 'bo', 'br', 'bs', 'ca', 'ce', 'ch',
                    'co', 'cr', 'cs', 'cu', 'cv', 'cy', 'da', 'de', 'dv', 'dz', 'ee', 'el', 'eo',
                    'es', 'et', 'eu', 'fa', 'ff', 'fi', 'fj', 'fo', 'fr', 'fy', 'ga', 'gd', 'gl',
                    'gn', 'gu', 'gv', 'ha', 'he', 'hi', 'ho', 'hr', 'ht', 'hu', 'hy', 'hz', 'ia',
                    'id', 'ie', 'ig', 'ii', 'ik', 'io', 'is', 'it', 'iu', 'ja', 'jv', 'ka', 'kg',
                    'ki', 'kj', 'kk', 'kl', 'km', 'kn', 'ko', 'kr', 'ks', 'ku', 'kv', 'kw', 'ky',
                    'la', 'lb', 'lg', 'li', 'ln', 'lo', 'lt', 'lu', 'lv', 'mg', 'mh', 'mi', 'mk',
                    'ml', 'mn', 'mr', 'ms', 'mt', 'my', 'na', 'nb', 'nd', 'ne', 'ng', 'nl', 'nn',
                    'no', 'nr', 'nv', 'ny', 'oc', 'oj', 'om', 'or', 'os', 'pa', 'pi', 'pl', 'ps',
                    'pt', 'qu', 'rm', 'rn', 'ro', 'ru', 'rw', 'sa', 'sc', 'sd', 'se', 'sg', 'si',
                    'sk', 'sl', 'sm', 'sn', 'so', 'sq', 'sr', 'ss', 'st', 'su', 'sv', 'sw', 'ta',
                    'te', 'tg', 'th', 'ti', 'tk', 'tl', 'tn', 'to', 'tr', 'ts', 'tt', 'tw', 'ty',
                    'ug', 'uk', 'ur', 'uz', 've', 'vi', 'vo', 'wa', 'wo', 'xh', 'yi', 'yo', 'za',
                    'zh', 'zu']
        for prefix in prefixes:
            metadata = deepcopy(example_010)
            metadata['stream']['metadata']['language'] = prefix
            claim = ClaimDict.load_dict(metadata)
            serialized = claim.serialized
            self.assertDictEqual(metadata, dict(ClaimDict.deserialize(serialized).claim_dict))

    def test_fake_alpha2(self):
        fake_codes = ["bb", "zz"]
        for fake_code in fake_codes:
            metadata = deepcopy(example_010)
            metadata['stream']['metadata']['language'] = fake_code
            self.assertRaises(DecodeError, ClaimDict.load_dict, metadata)


class TestMigration(UnitTest):
    def test_migrate_to_010(self):
        migrated_0_1_0 = migrate(example_003)
        self.assertDictEqual(migrated_0_1_0.claim_dict, example_010)
        self.assertEqual(migrated_0_1_0.is_certificate, False)


class TestNIST256pSignatures(UnitTest):
    def test_make_ecdsa_cert(self):
        cert = ClaimDict.generate_certificate(nist256p_private_key, curve=NIST256p)
        self.assertEqual(cert.is_certificate, True)
        self.assertDictEqual(cert.claim_dict, nist256p_cert)

    def test_validate_ecdsa_signature(self):
        cert = ClaimDict.generate_certificate(nist256p_private_key, curve=NIST256p)
        signed = ClaimDict.load_dict(example_010).sign(nist256p_private_key,
                                                       claim_address_2, claim_id_1, curve=NIST256p)
        self.assertDictEqual(signed.claim_dict, claim_010_signed_nist256p)
        signed_copy = ClaimDict.load_protobuf(signed.protobuf)
        self.assertEqual(signed_copy.validate_signature(claim_address_2, cert), True)

    def test_remove_signature_equals_unsigned(self):
        unsigned = ClaimDict.load_dict(example_010)
        signed = unsigned.sign(nist256p_private_key, claim_address_1, claim_id_1, curve=NIST256p)
        self.assertEqual(unsigned.serialized, signed.serialized_no_signature)

    def test_fail_to_validate_fake_ecdsa_signature(self):
        signed = ClaimDict.load_dict(example_010).sign(nist256p_private_key, claim_address_1,
                                                       claim_id_1, curve=NIST256p)
        signed_copy = ClaimDict.load_protobuf(signed.protobuf)
        fake_key = get_signer(NIST256p).generate().private_key.to_pem()
        fake_cert = ClaimDict.generate_certificate(fake_key, curve=NIST256p)
        self.assertRaises(ecdsa.keys.BadSignatureError, signed_copy.validate_signature,
                          claim_address_2, fake_cert)

    def test_fail_to_validate_ecdsa_sig_for_altered_claim(self):
        cert = ClaimDict.generate_certificate(nist256p_private_key, curve=NIST256p)
        altered = ClaimDict.load_dict(example_010).sign(nist256p_private_key, claim_address_1,
                                                        claim_id_1, curve=NIST256p)
        sd_hash = altered['stream']['source']['source']
        altered['stream']['source']['source'] = sd_hash[::-1]
        altered_copy = ClaimDict.load_dict(altered.claim_dict)
        self.assertRaises(ecdsa.keys.BadSignatureError, altered_copy.validate_signature,
                          claim_address_1, cert)


class TestNIST384pSignatures(UnitTest):
    def test_make_ecdsa_cert(self):
        cert = ClaimDict.generate_certificate(nist384p_private_key, curve=NIST384p)
        self.assertEqual(cert.is_certificate, True)
        self.assertDictEqual(cert.claim_dict, nist384p_cert)

    def test_validate_ecdsa_signature(self):
        cert = ClaimDict.generate_certificate(nist384p_private_key, curve=NIST384p)
        signed = ClaimDict.load_dict(example_010).sign(nist384p_private_key,
                                                       claim_address_2, claim_id_1, curve=NIST384p)
        self.assertDictEqual(signed.claim_dict, claim_010_signed_nist384p)
        signed_copy = ClaimDict.load_protobuf(signed.protobuf)
        self.assertEqual(signed_copy.validate_signature(claim_address_2, cert), True)

    def test_remove_signature_equals_unsigned(self):
        unsigned = ClaimDict.load_dict(example_010)
        signed = unsigned.sign(nist384p_private_key, claim_address_1, claim_id_1, curve=NIST384p)
        self.assertEqual(unsigned.serialized, signed.serialized_no_signature)

    def test_fail_to_validate_fake_ecdsa_signature(self):
        signed = ClaimDict.load_dict(example_010).sign(nist384p_private_key, claim_address_1,
                                                       claim_id_1, curve=NIST384p)
        signed_copy = ClaimDict.load_protobuf(signed.protobuf)
        fake_key = get_signer(NIST384p).generate().private_key.to_pem()
        fake_cert = ClaimDict.generate_certificate(fake_key, curve=NIST384p)
        self.assertRaises(ecdsa.keys.BadSignatureError, signed_copy.validate_signature,
                          claim_address_2, fake_cert)

    def test_fail_to_validate_ecdsa_sig_for_altered_claim(self):
        cert = ClaimDict.generate_certificate(nist384p_private_key, curve=NIST384p)
        altered = ClaimDict.load_dict(example_010).sign(nist384p_private_key, claim_address_1,
                                                        claim_id_1, curve=NIST384p)
        sd_hash = altered['stream']['source']['source']
        altered['stream']['source']['source'] = sd_hash[::-1]
        altered_copy = ClaimDict.load_dict(altered.claim_dict)
        self.assertRaises(ecdsa.keys.BadSignatureError, altered_copy.validate_signature,
                          claim_address_1, cert)


class TestSECP256k1Signatures(UnitTest):
    def test_make_ecdsa_cert(self):
        cert = ClaimDict.generate_certificate(secp256k1_private_key, curve=SECP256k1)
        self.assertEqual(cert.is_certificate, True)
        self.assertDictEqual(cert.claim_dict, secp256k1_cert)

    def test_validate_ecdsa_signature(self):
        cert = ClaimDict.generate_certificate(secp256k1_private_key, curve=SECP256k1)
        self.assertDictEqual(cert.claim_dict, secp256k1_cert)
        signed = ClaimDict.load_dict(example_010).sign(secp256k1_private_key, claim_address_2,
                                                       claim_id_1, curve=SECP256k1)
        self.assertDictEqual(signed.claim_dict, claim_010_signed_secp256k1)
        signed_copy = ClaimDict.load_protobuf(signed.protobuf)
        self.assertEqual(signed_copy.validate_signature(claim_address_2, cert), True)

    def test_fail_to_sign_with_no_claim_address(self):
        cert = ClaimDict.generate_certificate(secp256k1_private_key, curve=SECP256k1)
        self.assertDictEqual(cert.claim_dict, secp256k1_cert)
        self.assertRaises(Exception, ClaimDict.load_dict(example_010).sign, secp256k1_private_key,
                          None, claim_id_1, curve=SECP256k1)

    def test_fail_to_validate_with_no_claim_address(self):
        cert = ClaimDict.generate_certificate(secp256k1_private_key, curve=SECP256k1)
        self.assertDictEqual(cert.claim_dict, secp256k1_cert)
        signed = ClaimDict.load_dict(example_010).sign(secp256k1_private_key, claim_address_2,
                                                       claim_id_1, curve=SECP256k1)
        self.assertDictEqual(signed.claim_dict, claim_010_signed_secp256k1)
        signed_copy = ClaimDict.load_protobuf(signed.protobuf)
        self.assertRaises(Exception, signed_copy.validate_signature, None, cert)

    def test_remove_signature_equals_unsigned(self):
        unsigned = ClaimDict.load_dict(example_010)
        signed = unsigned.sign(secp256k1_private_key, claim_address_1, claim_id_1, curve=SECP256k1)
        self.assertEqual(unsigned.serialized, signed.serialized_no_signature)

    def test_fail_to_validate_fake_ecdsa_signature(self):
        signed = ClaimDict.load_dict(example_010).sign(secp256k1_private_key, claim_address_1,
                                                       claim_id_1, curve=SECP256k1)
        signed_copy = ClaimDict.load_protobuf(signed.protobuf)
        fake_key = get_signer(SECP256k1).generate().private_key.to_pem()
        fake_cert = ClaimDict.generate_certificate(fake_key, curve=SECP256k1)
        self.assertRaises(ecdsa.keys.BadSignatureError, signed_copy.validate_signature,
                          claim_address_2, fake_cert)

    def test_fail_to_validate_ecdsa_sig_for_altered_claim(self):
        cert = ClaimDict.generate_certificate(secp256k1_private_key, curve=SECP256k1)
        altered = ClaimDict.load_dict(example_010).sign(secp256k1_private_key, claim_address_1,
                                                        claim_id_1, curve=SECP256k1)
        sd_hash = altered['stream']['source']['source']
        altered['stream']['source']['source'] = sd_hash[::-1]
        altered_copy = ClaimDict.load_dict(altered.claim_dict)
        self.assertRaises(ecdsa.keys.BadSignatureError, altered_copy.validate_signature,
                          claim_address_1, cert)


class TestMetadata(UnitTest):
    def test_fail_with_fake_sd_hash(self):
        claim = deepcopy(example_010)
        sd_hash = claim['stream']['source']['source'][:-2]
        claim['stream']['source']['source'] = sd_hash
        self.assertRaises(AssertionError, ClaimDict.load_dict, claim)


class TestSmartDecode(UnitTest):
    def test_hex_decode(self):
        self.assertEqual(decoded_hex_encoded_003, smart_decode(hex_encoded_003).claim_dict)

    def test_binary_decode(self):
        self.assertEqual(expected_binary_claim_decoded, smart_decode(binary_claim).claim_dict)

    def test_smart_decode_raises(self):
        with self.assertRaises(TypeError):
            smart_decode(1)

        with self.assertRaises(DecodeError):
            smart_decode("aaab")

        with self.assertRaises(DecodeError):
            smart_decode("{'bogus_dict':1}")


class TestMainnetAddressValidation(UnitTest):
    def test_mainnet_address_encode_decode(self):
        valid_addr_hex = "55be482f953ed0feda4fc5c4d012681b6119274993dc96bf10"
        self.assertEqual(encode_address(binascii.unhexlify(valid_addr_hex)),
                         b"bW5PZEvEBNPQRVhwpYXSjabFgbSw1oaHyR")
        self.assertEqual(decode_address("bW5PZEvEBNPQRVhwpYXSjabFgbSw1oaHyR"),
                         binascii.unhexlify(valid_addr_hex))

    def test_mainnet_address_encode_error(self):
        invalid_prefix =   "54be482f953ed0feda4fc5c4d012681b6119274993dc96bf10"
        invalid_checksum = "55be482f953ed0feda4fc5c4d012681b6119274993dc96bf11"
        invalid_length =   "55482f953ed0feda4fc5c4d012681b6119274993dc96bf10"

        with self.assertRaises(InvalidAddress):
            encode_address(binascii.unhexlify(invalid_prefix))
            encode_address(binascii.unhexlify(invalid_checksum))
            encode_address(binascii.unhexlify(invalid_length))

    def test_mainnet_address_decode_error(self):
        with self.assertRaises(InvalidAddress):
            decode_address("bW5PZEvEBNPQRVhwpYXSjabFgbSw1oaHR")
        with self.assertRaises(InvalidAddress):
            decode_address("mzGSynizDwSgURdnFjosZwakSVuZrdE8V4")


class TestRegtestAddressValidation(UnitTest):
    def setUp(self):
        schema.BLOCKCHAIN_NAME = "lbrycrd_regtest"

    def tearDown(self):
        schema.BLOCKCHAIN_NAME = "lbrycrd_main"

    def test_regtest_address_encode_decode(self):
        valid_addr_hex = "6fcdac187757dbf05500f613ada6fdd953d59b9acbf3c9343f"
        self.assertEqual(encode_address(binascii.unhexlify(valid_addr_hex)),
                         b"mzGSynizDwSgURdnFjosZwakSVuZrdE8V4")
        self.assertEqual(decode_address("mzGSynizDwSgURdnFjosZwakSVuZrdE8V4"),
                         binascii.unhexlify(valid_addr_hex))

    def test_regtest_address_encode_error(self):
        invalid_prefix =   "6dcdac187757dbf05500f613ada6fdd953d59b9acbf3c9343f"
        invalid_checksum = "6fcdac187757dbf05500f613ada6fdd953d59b9acbf3c9343d"
        invalid_length =   "6fcdac187757dbf05500f613ada6fdd953d59b9acbf3c934"

        with self.assertRaises(InvalidAddress):
            encode_address(binascii.unhexlify(invalid_prefix))
            encode_address(binascii.unhexlify(invalid_checksum))
            encode_address(binascii.unhexlify(invalid_length))

    def test_regtest_address_decode_error(self):
        with self.assertRaises(InvalidAddress):
            decode_address("bW5PZEvEBNPQRVhwpYXSjabFgbSw1oaHyR")
        with self.assertRaises(InvalidAddress):
            decode_address("mzGSynizDwSgURdnFjosZwakSVuZrdE8V5")


class TestInvalidCertificateCurve(UnitTest):
    def test_invalid_cert_curve(self):
        with self.assertRaises(Exception):
            ClaimDict.load_dict(malformed_secp256k1_cert)


class TestValidatePrivateKey(UnitTest):
    def test_valid_private_key_for_cert(self):
        cert_claim = ClaimDict.load_dict(secp256k1_cert)
        self.assertEqual(cert_claim.validate_private_key(secp256k1_private_key, claim_id_1),
                         True)

    def test_fail_to_load_wrong_private_key_for_cert(self):
        cert_claim = ClaimDict.load_dict(secp256k1_cert)
        self.assertEqual(cert_claim.validate_private_key(nist256p_private_key, claim_id_1),
                         False)


if __name__ == '__main__':
    unittest.main()
