import asyncio
import json
from lbry.testcase import CommandTestCase
from torba.client.wallet import ENCRYPT_ON_DISK


class WalletEncryptionAndSynchronization(CommandTestCase):

    SEED = (
        "carbon smart garage balance margin twelve chest "
        "sword toast envelope bottom stomach absent"
    )

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.daemon2 = await self.add_daemon(
            seed="chest sword toast envelope bottom stomach absent "
                 "carbon smart garage balance margin twelve"
        )
        address = (await self.daemon2.wallet_manager.default_account.receiving.get_addresses(limit=1, only_usable=True))[0]
        sendtxid = await self.blockchain.send_to_address(address, 1)
        await self.confirm_tx(sendtxid, self.daemon2.ledger)

    def assertWalletEncrypted(self, wallet_path, encrypted):
        wallet = json.load(open(wallet_path))
        self.assertEqual(wallet['accounts'][0]['private_key'][1:4] != 'prv', encrypted)

    async def test_sync(self):
        daemon, daemon2 = self.daemon, self.daemon2

        # Preferences
        self.assertFalse(daemon.jsonrpc_preference_get())
        self.assertFalse(daemon2.jsonrpc_preference_get())

        daemon.jsonrpc_preference_set("fruit", '["peach", "apricot"]')
        daemon.jsonrpc_preference_set("one", "1")
        daemon.jsonrpc_preference_set("conflict", "1")
        daemon2.jsonrpc_preference_set("another", "A")
        await asyncio.sleep(1)
        # these preferences will win after merge since they are "newer"
        daemon2.jsonrpc_preference_set("two", "2")
        daemon2.jsonrpc_preference_set("conflict", "2")
        daemon.jsonrpc_preference_set("another", "B")

        self.assertDictEqual(daemon.jsonrpc_preference_get(), {
            "one": "1", "conflict": "1", "another": "B", "fruit": ["peach", "apricot"]
        })
        self.assertDictEqual(daemon2.jsonrpc_preference_get(), {
            "two": "2", "conflict": "2", "another": "A"
        })

        self.assertEqual(len((await daemon.jsonrpc_account_list())['lbc_regtest']), 1)

        data = await daemon2.jsonrpc_sync_apply('password')
        await daemon.jsonrpc_sync_apply('password', data=data['data'], blocking=True)

        self.assertEqual(len((await daemon.jsonrpc_account_list())['lbc_regtest']), 2)
        self.assertDictEqual(
            # "two" key added and "conflict" value changed to "2"
            daemon.jsonrpc_preference_get(),
            {"one": "1", "two": "2", "conflict": "2", "another": "B", "fruit": ["peach", "apricot"]}
        )

        # Channel Certificate
        channel = await daemon2.jsonrpc_channel_create('@foo', '0.1')
        await self.confirm_tx(channel.id, self.daemon2.ledger)

        # both daemons will have the channel but only one has the cert so far
        self.assertEqual(len(await daemon.jsonrpc_channel_list()), 1)
        self.assertEqual(len(daemon.wallet_manager.default_wallet.accounts[1].channel_keys), 0)
        self.assertEqual(len(await daemon2.jsonrpc_channel_list()), 1)
        self.assertEqual(len(daemon2.wallet_manager.default_account.channel_keys), 1)

        data = await daemon2.jsonrpc_sync_apply('password')
        await daemon.jsonrpc_sync_apply('password', data=data['data'], blocking=True)

        # both daemons have the cert after sync'ing
        self.assertEqual(
            daemon2.wallet_manager.default_account.channel_keys,
            daemon.wallet_manager.default_wallet.accounts[1].channel_keys
        )

    async def test_encryption_and_locking(self):
        daemon = self.daemon
        wallet = daemon.wallet_manager.default_wallet
        wallet.save()

        self.assertEqual(daemon.jsonrpc_wallet_status(), {'is_locked': False, 'is_encrypted': False})
        self.assertIsNone(daemon.jsonrpc_preference_get(ENCRYPT_ON_DISK))
        self.assertWalletEncrypted(wallet.storage.path, False)

        # can't lock an unencrypted account
        with self.assertRaisesRegex(AssertionError, "Cannot lock an unencrypted wallet, encrypt first."):
            daemon.jsonrpc_wallet_lock()
        # safe to call unlock and decrypt, they are no-ops at this point
        daemon.jsonrpc_wallet_unlock('password')  # already unlocked
        daemon.jsonrpc_wallet_decrypt()  # already not encrypted

        daemon.jsonrpc_wallet_encrypt('password')
        self.assertEqual(daemon.jsonrpc_wallet_status(), {'is_locked': False, 'is_encrypted': True})
        self.assertEqual(daemon.jsonrpc_preference_get(ENCRYPT_ON_DISK), {'encrypt-on-disk': True})
        self.assertWalletEncrypted(wallet.storage.path, True)

        daemon.jsonrpc_wallet_lock()
        self.assertEqual(daemon.jsonrpc_wallet_status(), {'is_locked': True, 'is_encrypted': True})

        # can't sign transactions with locked wallet
        with self.assertRaises(AssertionError):
            await daemon.jsonrpc_channel_create('@foo', '1.0')
        daemon.jsonrpc_wallet_unlock('password')
        self.assertEqual(daemon.jsonrpc_wallet_status(), {'is_locked': False, 'is_encrypted': True})
        await daemon.jsonrpc_channel_create('@foo', '1.0')

        daemon.jsonrpc_wallet_decrypt()
        self.assertEqual(daemon.jsonrpc_wallet_status(), {'is_locked': False, 'is_encrypted': False})
        self.assertEqual(daemon.jsonrpc_preference_get(ENCRYPT_ON_DISK), {'encrypt-on-disk': False})
        self.assertWalletEncrypted(wallet.storage.path, False)

    async def test_encryption_with_imported_channel(self):
        daemon, daemon2 = self.daemon, self.daemon2
        channel = await self.channel_create()
        exported = await daemon.jsonrpc_channel_export(self.get_claim_id(channel))
        await daemon2.jsonrpc_channel_import(exported)
        self.assertTrue(daemon2.jsonrpc_wallet_encrypt('password'))
        self.assertTrue(daemon2.jsonrpc_wallet_lock())
        self.assertTrue(daemon2.jsonrpc_wallet_unlock("password"))
        self.assertEqual(daemon2.jsonrpc_wallet_status(), {'is_locked': False, 'is_encrypted': True})

    async def test_sync_with_encryption_and_password_change(self):
        daemon, daemon2 = self.daemon, self.daemon2
        wallet, wallet2 = daemon.wallet_manager.default_wallet, daemon2.wallet_manager.default_wallet

        self.assertEqual(wallet2.encryption_password, None)
        self.assertEqual(wallet2.encryption_password, None)

        daemon.jsonrpc_wallet_encrypt('password')
        self.assertEqual(wallet.encryption_password, 'password')

        data = await daemon2.jsonrpc_sync_apply('password2')
        # sync_apply doesn't save password if encrypt-on-disk is False
        self.assertEqual(wallet2.encryption_password, None)
        # need to use new password2 in sync_apply
        with self.assertRaises(ValueError):  # wrong password
            await daemon.jsonrpc_sync_apply('password', data=data['data'], blocking=True)
        await daemon.jsonrpc_sync_apply('password2', data=data['data'], blocking=True)
        # sync_apply with new password2 also sets it as new local password
        self.assertEqual(wallet.encryption_password, 'password2')
        self.assertEqual(daemon.jsonrpc_wallet_status(), {'is_locked': False, 'is_encrypted': True})
        self.assertEqual(daemon.jsonrpc_preference_get(ENCRYPT_ON_DISK), {'encrypt-on-disk': True})
        self.assertWalletEncrypted(wallet.storage.path, True)

        # check new password is active
        daemon.jsonrpc_wallet_lock()
        self.assertFalse(daemon.jsonrpc_wallet_unlock('password'))
        self.assertTrue(daemon.jsonrpc_wallet_unlock('password2'))

        # propagate disk encryption to daemon2
        data = await daemon.jsonrpc_sync_apply('password3')
        # sync_apply (even with no data) on wallet with encrypt-on-disk updates local password
        self.assertEqual(wallet.encryption_password, 'password3')
        self.assertEqual(wallet2.encryption_password, None)
        await daemon2.jsonrpc_sync_apply('password3', data=data['data'], blocking=True)
        # the other device got new password and on disk encryption
        self.assertEqual(wallet2.encryption_password, 'password3')
        self.assertEqual(daemon2.jsonrpc_wallet_status(), {'is_locked': False, 'is_encrypted': True})
        self.assertEqual(daemon2.jsonrpc_preference_get(ENCRYPT_ON_DISK), {'encrypt-on-disk': True})
        self.assertWalletEncrypted(wallet2.storage.path, True)

        daemon2.jsonrpc_wallet_lock()
        self.assertTrue(daemon2.jsonrpc_wallet_unlock('password3'))
