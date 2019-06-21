from torba.testcase import AsyncioTestCase

from lbry.extras.daemon.comment_client import sign_comment
from lbry.extras.daemon.comment_client import is_comment_signed_by_channel

from tests.unit.wallet.test_schema_signing import get_stream, get_channel


class TestSigningComments(AsyncioTestCase):

    @staticmethod
    def create_claim_comment_body(comment, claim, channel):
        return {
            'claim_id': claim.claim_id,
            'channel_name': channel.claim_name,
            'channel_id': channel.claim_id,
            'comment': comment
        }

    def test01_successful_create_sign_and_validate_comment(self):
        channel = get_channel('@BusterBluth')
        stream = get_stream('pop secret')
        comment = self.create_claim_comment_body('Cool stream', stream, channel)
        sign_comment(comment, channel)
        self.assertTrue(is_comment_signed_by_channel(comment, channel))

    def test02_fail_to_validate_spoofed_channel(self):
        pdiddy = get_channel('@PDitty')
        channel2 = get_channel('@TomHaverford')
        stream = get_stream()
        comment = self.create_claim_comment_body('Woahh This is Sick!! Shout out 2 my boy Tommy H', stream, pdiddy)
        sign_comment(comment, channel2)
        self.assertFalse(is_comment_signed_by_channel(comment, pdiddy))
