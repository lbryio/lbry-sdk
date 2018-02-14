import os
import shutil
import tempfile
import lbryum.wallet

from decimal import Decimal
from collections import defaultdict
from twisted.trial import unittest
from twisted.internet import threads, defer
from lbrynet.database.storage import SQLiteStorage
from lbrynet.tests.mocks import FakeNetwork
from lbrynet.core.Error import InsufficientFundsError
from lbrynet.core.Wallet import LBRYumWallet, ReservedPoints
from lbryum.commands import Commands
from lbryum.simple_config import SimpleConfig
from lbryschema.claim import ClaimDict

test_metadata = {
    'license': 'NASA',
    'version': '_0_1_0',
    'description': 'test',
    'language': 'en',
    'author': 'test',
    'title': 'test',
    'nsfw': False,
    'thumbnail': 'test'
}

test_claim_dict = {
    'version': '_0_0_1',
    'claimType': 'streamType',
    'stream': {'metadata': test_metadata, 'version': '_0_0_1', 'source':
        {'source': '8655f713819344980a9a0d67b198344e2c462c90f813e86f'
                   '0c63789ab0868031f25c54d0bb31af6658e997e2041806eb',
         'sourceType': 'lbry_sd_hash', 'contentType': 'video/mp4', 'version': '_0_0_1'},
               }}


class MocLbryumWallet(LBRYumWallet):
    def __init__(self, db_dir):
        LBRYumWallet.__init__(self, SQLiteStorage(db_dir), SimpleConfig(
            {"lbryum_path": db_dir, "wallet_path": os.path.join(db_dir, "testwallet")}
        ))
        self.db_dir = db_dir
        self.wallet_balance = Decimal(10.0)
        self.total_reserved_points = Decimal(0.0)
        self.queued_payments = defaultdict(Decimal)
        self.network = FakeNetwork()
        assert self.config.get_wallet_path() == os.path.join(self.db_dir, "testwallet")

    @defer.inlineCallbacks
    def setup(self, password=None, seed=None):
        yield self.storage.setup()
        seed = seed or "travel nowhere air position hill peace suffer parent beautiful rise " \
                       "blood power home crumble teach"
        storage = lbryum.wallet.WalletStorage(self.config.get_wallet_path())
        self.wallet = lbryum.wallet.NewWallet(storage)
        self.wallet.add_seed(seed, password)
        self.wallet.create_master_keys(password)
        self.wallet.create_main_account()

    @defer.inlineCallbacks
    def stop(self):
        yield self.storage.stop()
        yield threads.deferToThread(shutil.rmtree, self.db_dir)

    def get_least_used_address(self, account=None, for_change=False, max_count=100):
        return defer.succeed(None)

    def get_name_claims(self):
        return threads.deferToThread(lambda: [])

    def _save_name_metadata(self, name, claim_outpoint, sd_hash):
        return defer.succeed(True)

    def get_max_usable_balance_for_claim(self, name):
        return defer.succeed(3)

class WalletTest(unittest.TestCase):
    @defer.inlineCallbacks
    def setUp(self):
        user_dir = tempfile.mkdtemp()
        self.wallet = MocLbryumWallet(user_dir)
        yield self.wallet.setup()
        self.assertEqual(self.wallet.get_balance(), Decimal(10))

    def tearDown(self):
        return self.wallet.stop()

    def test_failed_send_name_claim(self):
        def not_enough_funds_send_name_claim(self, name, val, amount):
            claim_out = {'success': False, 'reason': 'Not enough funds'}
            return claim_out

        self.wallet._send_name_claim = not_enough_funds_send_name_claim
        d = self.wallet.claim_name('test', 1, test_claim_dict)
        self.assertFailure(d, Exception)
        return d

    @defer.inlineCallbacks
    def test_successful_send_name_claim(self):
        expected_claim_out = {
            "claim_id": "f43dc06256a69988bdbea09a58c80493ba15dcfa",
            "fee": "0.00012",
            "nout": 0,
            "success": True,
            "txid": "6f8180002ef4d21f5b09ca7d9648a54d213c666daf8639dc283e2fd47450269e",
            "value": ClaimDict.load_dict(test_claim_dict).serialized.encode('hex'),
            "claim_address": "",
            "channel_claim_id": "",
            "channel_name": ""
        }

        def success_send_name_claim(self, name, val, amount, certificate_id=None,
                                    claim_address=None, change_address=None):
            return defer.succeed(expected_claim_out)

        self.wallet._send_name_claim = success_send_name_claim
        claim_out = yield self.wallet.claim_name('test', 1, test_claim_dict)
        self.assertTrue('success' not in claim_out)
        self.assertEqual(expected_claim_out['claim_id'], claim_out['claim_id'])
        self.assertEqual(expected_claim_out['fee'], claim_out['fee'])
        self.assertEqual(expected_claim_out['nout'], claim_out['nout'])
        self.assertEqual(expected_claim_out['txid'], claim_out['txid'])
        self.assertEqual(expected_claim_out['value'], claim_out['value'])

    @defer.inlineCallbacks
    def test_failed_support(self):
        # wallet.support_claim will check the balance before calling _support_claim
        try:
            yield self.wallet.support_claim('test', "f43dc06256a69988bdbea09a58c80493ba15dcfa", 1000)
        except InsufficientFundsError:
            pass

    def test_succesful_support(self):
        expected_support_out = {
            "fee": "0.000129",
            "nout": 0,
            "success": True,
            "txid": "11030a76521e5f552ca87ad70765d0cc52e6ea4c0dc0063335e6cf2a9a85085f"
        }

        expected_result = {
            "fee": 0.000129,
            "nout": 0,
            "txid": "11030a76521e5f552ca87ad70765d0cc52e6ea4c0dc0063335e6cf2a9a85085f"
        }

        def check_out(claim_out):
            self.assertDictEqual(expected_result, claim_out)

        def success_support_claim(name, val, amount):
            return defer.succeed(expected_support_out)

        self.wallet._support_claim = success_support_claim
        d = self.wallet.support_claim('test', "f43dc06256a69988bdbea09a58c80493ba15dcfa", 1)
        d.addCallback(lambda claim_out: check_out(claim_out))
        return d

    @defer.inlineCallbacks
    def test_failed_abandon(self):
        try:
            yield self.wallet.abandon_claim("f43dc06256a69988bdbea09a58c80493ba15dcfa", None, None)
            raise Exception("test failed")
        except Exception as err:
            self.assertSubstring("claim not found", err.message)

    @defer.inlineCallbacks
    def test_successful_abandon(self):
        expected_abandon_out = {
            "fee": "0.000096",
            "success": True,
            "txid": "0578c161ad8d36a7580c557d7444f967ea7f988e194c20d0e3c42c3cabf110dd"
        }

        expected_abandon_result = {
            "fee": 0.000096,
            "txid": "0578c161ad8d36a7580c557d7444f967ea7f988e194c20d0e3c42c3cabf110dd"
        }

        def success_abandon_claim(claim_outpoint, txid, nout):
            return defer.succeed(expected_abandon_out)

        self.wallet._abandon_claim = success_abandon_claim
        claim_out = yield self.wallet.abandon_claim("f43dc06256a69988bdbea09a58c80493ba15dcfa", None, None)
        self.assertDictEqual(expected_abandon_result, claim_out)

    @defer.inlineCallbacks
    def test_point_reservation_and_balance(self):
        # check that point reservations and cancellation changes the balance
        # properly
        def update_balance():
            return defer.succeed(5)

        self.wallet._update_balance = update_balance
        yield self.wallet.update_balance()
        self.assertEqual(5, self.wallet.get_balance())

        # test point reservation
        yield self.wallet.reserve_points('testid', 2)
        self.assertEqual(3, self.wallet.get_balance())
        self.assertEqual(2, self.wallet.total_reserved_points)

        # test reserved points cancellation
        yield self.wallet.cancel_point_reservation(ReservedPoints('testid', 2))
        self.assertEqual(5, self.wallet.get_balance())
        self.assertEqual(0, self.wallet.total_reserved_points)

        # test point sending
        reserve_points = yield self.wallet.reserve_points('testid', 2)
        yield self.wallet.send_points_to_address(reserve_points, 1)
        self.assertEqual(3, self.wallet.get_balance())
        # test failed point reservation
        out = yield self.wallet.reserve_points('testid', 4)
        self.assertEqual(None, out)

    def test_point_reservation_and_claim(self):
        # check that claims take into consideration point reservations
        def update_balance():
            return defer.succeed(5)

        self.wallet._update_balance = update_balance
        d = self.wallet.update_balance()
        d.addCallback(lambda _: self.assertEqual(5, self.wallet.get_balance()))
        d.addCallback(lambda _: self.wallet.reserve_points('testid', 2))
        d.addCallback(lambda _: self.wallet.claim_name('test', 4, test_claim_dict))
        self.assertFailure(d, InsufficientFundsError)
        return d

    def test_point_reservation_and_support(self):
        # check that supports take into consideration point reservations
        def update_balance():
            return defer.succeed(5)

        self.wallet._update_balance = update_balance
        d = self.wallet.update_balance()
        d.addCallback(lambda _: self.assertEqual(5, self.wallet.get_balance()))
        d.addCallback(lambda _: self.wallet.reserve_points('testid', 2))
        d.addCallback(lambda _: self.wallet.support_claim(
            'test', "f43dc06256a69988bdbea09a58c80493ba15dcfa", 4))
        self.assertFailure(d, InsufficientFundsError)
        return d


class WalletEncryptionTests(unittest.TestCase):
    def setUp(self):
        user_dir = tempfile.mkdtemp()
        self.wallet = MocLbryumWallet(user_dir)
        return self.wallet.setup(password="password")

    def tearDown(self):
        return self.wallet.stop()

    def test_unlock_wallet(self):
        self.wallet._cmd_runner = Commands(
            self.wallet.config, self.wallet.wallet, self.wallet.network, None, "password")
        cmd_runner = self.wallet.get_cmd_runner()
        cmd_runner.unlock_wallet("password")
        self.assertIsNone(cmd_runner.new_password)
        self.assertEqual(cmd_runner._password, "password")

    def test_encrypt_decrypt_wallet(self):
        self.wallet._cmd_runner = Commands(
            self.wallet.config, self.wallet.wallet, self.wallet.network, None, "password")
        self.wallet.encrypt_wallet("secret2", False)
        self.wallet.decrypt_wallet()

    def test_update_password_keyring_off(self):
        self.wallet.config.use_keyring = False
        self.wallet._cmd_runner = Commands(
            self.wallet.config, self.wallet.wallet, self.wallet.network, None, "password")

        # no keyring available, so ValueError is expected
        with self.assertRaises(ValueError):
            self.wallet.encrypt_wallet("secret2", True)
