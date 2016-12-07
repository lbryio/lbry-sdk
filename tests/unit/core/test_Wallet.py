from twisted.trial import unittest

from twisted.internet import threads, defer
from lbrynet.core.Wallet import Wallet

test_metadata = {
'license': 'NASA',
'fee': {'USD': {'amount': 0.01, 'address': 'baBYSK7CqGSn5KrEmNmmQwAhBSFgo6v47z'}},
'ver': '0.0.3',
'description': 'test',
'language': 'en',
'author': 'test',
'title': 'test',
'sources': {
    'lbry_sd_hash': '8655f713819344980a9a0d67b198344e2c462c90f813e86f0c63789ab0868031f25c54d0bb31af6658e997e2041806eb'},
'nsfw': False,
'content_type': 'video/mp4',
'thumbnail': 'test'
}


class MocLbryumWallet(Wallet):
    def __init__(self):
        pass
    def get_name_claims(self):
        return threads.deferToThread(lambda: [])

    def _save_name_metadata(self, name, claim_outpoint, sd_hash):
        return defer.succeed(True)


class WalletTest(unittest.TestCase):

    def _check_exception(self, d):
        def check(err):
            with self.assertRaises(Exception):
                err.raiseException()
        d.addCallbacks(lambda _: self.assertTrue(False), lambda err: check(err))

    def test_failed_send_name_claim(self):
        def not_enough_funds_send_name_claim(self, name, val, amount):
            claim_out = {'success':False, 'reason':'Not enough funds'}
            return claim_out
        MocLbryumWallet._send_name_claim = not_enough_funds_send_name_claim
        wallet = MocLbryumWallet()
        d = wallet.claim_name('test', 1, test_metadata)
        self._check_exception(d)
        return d

    def test_successful_send_name_claim(self):
        test_claim_out = {
            "claimid": "f43dc06256a69988bdbea09a58c80493ba15dcfa",
            "fee": "0.00012",
            "nout": 0,
            "success": True,
            "txid": "6f8180002ef4d21f5b09ca7d9648a54d213c666daf8639dc283e2fd47450269e"
         }

        def check_out(claim_out):
            self.assertTrue('success' not in claim_out)
            self.assertEqual(claim_out['claimid'], test_claim_out['claimid'])
            self.assertEqual(claim_out['fee'], test_claim_out['fee'])
            self.assertEqual(claim_out['nout'], test_claim_out['nout'])
            self.assertEqual(claim_out['txid'], test_claim_out['txid'])

        def success_send_name_claim(self, name, val, amount):
            return test_claim_out

        MocLbryumWallet._send_name_claim = success_send_name_claim
        wallet = MocLbryumWallet()
        d = wallet.claim_name('test', 1, test_metadata)
        d.addCallback(lambda claim_out: check_out(claim_out))
        return d

    def test_failed_support(self):
        def failed_support_claim(self, name, claim_id, amount):
            claim_out = {'success':False, 'reason':'Not enough funds'}
            return threads.deferToThread(lambda: claim_out)
        MocLbryumWallet._support_claim = failed_support_claim
        wallet = MocLbryumWallet()
        d = wallet.support_claim('test', "f43dc06256a69988bdbea09a58c80493ba15dcfa", 1)
        self._check_exception(d)
        return d

    def test_succesful_support(self):
        test_support_out = {
            "fee": "0.000129",
            "nout": 0,
            "success": True,
            "txid": "11030a76521e5f552ca87ad70765d0cc52e6ea4c0dc0063335e6cf2a9a85085f"
        }

        def check_out(claim_out):
            self.assertTrue('success' not in claim_out)
            self.assertEqual(claim_out['fee'], test_support_out['fee'])
            self.assertEqual(claim_out['nout'], test_support_out['nout'])
            self.assertEqual(claim_out['txid'], test_support_out['txid'])

        def success_support_claim(self, name, val, amount):
            return threads.deferToThread(lambda: test_support_out)
        MocLbryumWallet._support_claim = success_support_claim
        wallet = MocLbryumWallet()
        d = wallet.support_claim('test', "f43dc06256a69988bdbea09a58c80493ba15dcfa", 1)
        d.addCallback(lambda claim_out: check_out(claim_out))
        return d

    def test_failed_abandon(self):
        def failed_abandon_claim(self, claim_outpoint):
            claim_out = {'success':False, 'reason':'Not enough funds'}
            return threads.deferToThread(lambda: claim_out)
        MocLbryumWallet._abandon_claim = failed_abandon_claim
        wallet = MocLbryumWallet()
        d = wallet.abandon_claim("11030a76521e5f552ca87ad70765d0cc52e6ea4c0dc0063335e6cf2a9a85085f", 1)
        self._check_exception(d)
        return d

    def test_successful_abandon(self):
        test_abandon_out = {
            "fee": "0.000096",
            "success": True,
            "txid": "0578c161ad8d36a7580c557d7444f967ea7f988e194c20d0e3c42c3cabf110dd"
        }

        def check_out(claim_out):
            self.assertTrue('success' not in claim_out)
            self.assertEqual(claim_out['fee'], test_abandon_out['fee'])
            self.assertEqual(claim_out['txid'], test_abandon_out['txid'])

        def success_abandon_claim(self, claim_outpoint):
            return threads.deferToThread(lambda: test_abandon_out)

        MocLbryumWallet._abandon_claim = success_abandon_claim
        wallet = MocLbryumWallet()
        d = wallet.abandon_claim("0578c161ad8d36a7580c557d7444f967ea7f988e194c20d0e3c42c3cabf110dd", 1)
        d.addCallback(lambda claim_out: check_out(claim_out))
        return d
