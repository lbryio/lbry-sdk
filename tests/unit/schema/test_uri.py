import unittest

from lbrynet.schema.uri import URI, URIParseError

claim_id_1 = "63f2da17b0d90042c559cc73b6b17f853945c43e"

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
    ("lbry://@/what", URIParseError),
    ("lbry://abc:0x123", URIParseError),
    ("lbry://abc:0x123/page", URIParseError),
    ("lbry://@test1#ABCDEF/fakepath", URIParseError),
    ("test:0001", URIParseError),
    ("lbry://@test1$1/fakepath?arg1&arg2&arg3", URIParseError)
]


class TestURIParser(unittest.TestCase):

    maxDiff = 4000
    longMessage = True

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
