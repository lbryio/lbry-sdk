from torba.testcase import AsyncioTestCase
import hashlib
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
            'comment': comment,
            'comment_id': hashlib.sha256(comment.encode()).hexdigest()
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

    def test03_successful_sign_abandon_comment(self):
        rswanson = get_channel('@RonSwanson')
        dsilver = get_stream('Welcome to the Pawnee, and give a big round for Ron Swanson, AKA Duke Silver')
        comment_body = self.create_claim_comment_body('COMPUTER, DELETE ALL VIDEOS OF RON.', dsilver, rswanson)
        sign_comment(comment_body, rswanson, abandon=True)
        self.assertTrue(is_comment_signed_by_channel(comment_body, rswanson, abandon=True))

    def test04_invalid_signature(self):
        rswanson = get_channel('@RonSwanson')
        jeanralphio = get_channel('@JeanRalphio')
        chair = get_stream('This is a nice chair. I made it with Mahogany wood and this electric saw')
        chair_comment = self.create_claim_comment_body(
            'Hah. You use an electric saw? Us swansons have been making chairs with handsaws just three after birth.',
            chair,
            rswanson
        )
        sign_comment(chair_comment, rswanson)
        self.assertTrue(is_comment_signed_by_channel(chair_comment, rswanson))
        self.assertFalse(is_comment_signed_by_channel(chair_comment, jeanralphio))
        fake_abandon_signal = chair_comment.copy()
        sign_comment(fake_abandon_signal, jeanralphio, abandon=True)
        self.assertFalse(is_comment_signed_by_channel(fake_abandon_signal, rswanson, abandon=True))
        self.assertFalse(is_comment_signed_by_channel(fake_abandon_signal, jeanralphio, abandon=True))

