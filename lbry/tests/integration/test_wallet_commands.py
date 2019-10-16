import asyncio
import json
from lbry import error
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

        daemon.jsonrpc_preference_set("one", "1")
        daemon.jsonrpc_preference_set("conflict", "1")
        daemon.jsonrpc_preference_set("fruit", '["peach", "apricot"]')
        await asyncio.sleep(1)
        daemon2.jsonrpc_preference_set("two", "2")
        daemon2.jsonrpc_preference_set("conflict", "2")

        self.assertDictEqual(daemon.jsonrpc_preference_get(), {
            "one": "1", "conflict": "1", "fruit": ["peach", "apricot"]
        })
        self.assertDictEqual(daemon2.jsonrpc_preference_get(), {
            "two": "2", "conflict": "2"
        })

        self.assertEqual(len((await daemon.jsonrpc_account_list())['lbc_regtest']), 1)

        data = await daemon2.jsonrpc_sync_apply('password')
        await daemon.jsonrpc_sync_apply('password', data=data['data'], blocking=True)

        self.assertEqual(len((await daemon.jsonrpc_account_list())['lbc_regtest']), 2)
        self.assertDictEqual(
            # "two" key added and "conflict" value changed to "2"
            daemon.jsonrpc_preference_get(),
            {"one": "1", "two": "2", "conflict": "2", "fruit": ["peach", "apricot"]}
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

        self.assertEqual(
            daemon.jsonrpc_wallet_status(),
            {'is_locked': False, 'is_encrypted': False}
        )
        self.assertIsNone(daemon.jsonrpc_preference_get(ENCRYPT_ON_DISK))
        self.assertWalletEncrypted(wallet.storage.path, False)

        # can't lock an unencrypted account
        with self.assertRaisesRegex(AssertionError, "Cannot lock an unencrypted wallet, encrypt first."):
            daemon.jsonrpc_wallet_lock()
        # safe to call unlock and decrypt, they are no-ops at this point
        daemon.jsonrpc_wallet_unlock('password')  # already unlocked
        daemon.jsonrpc_wallet_decrypt()  # already not encrypted

        daemon.jsonrpc_wallet_encrypt('password')

        self.assertEqual(
            daemon.jsonrpc_wallet_status(),
            {'is_locked': False, 'is_encrypted': True}
        )
        self.assertEqual(
            daemon.jsonrpc_preference_get(ENCRYPT_ON_DISK),
            {'encrypt-on-disk': True}
        )
        self.assertWalletEncrypted(wallet.storage.path, True)

        daemon.jsonrpc_wallet_lock()

        self.assertEqual(
            daemon.jsonrpc_wallet_status(),
            {'is_locked': True, 'is_encrypted': True}
        )

        with self.assertRaises(error.ComponentStartConditionNotMet):
            await daemon.jsonrpc_channel_create('@foo', '1.0')

        daemon.jsonrpc_wallet_unlock('password')
        await daemon.jsonrpc_channel_create('@foo', '1.0')

        daemon.jsonrpc_wallet_decrypt()
        self.assertEqual(
            daemon.jsonrpc_wallet_status(),
            {'is_locked': False, 'is_encrypted': False}
        )
        self.assertEqual(
            daemon.jsonrpc_preference_get(ENCRYPT_ON_DISK),
            {'encrypt-on-disk': False}
        )
        self.assertWalletEncrypted(wallet.storage.path, False)

    async def test_sync_with_encryption_and_password_change(self):
        daemon, daemon2 = self.daemon, self.daemon2
        wallet, wallet2 = daemon.wallet_manager.default_wallet, daemon2.wallet_manager.default_wallet

        daemon.jsonrpc_wallet_encrypt('password')

        self.assertEqual(daemon.jsonrpc_wallet_status(), {'is_locked': False, 'is_encrypted': True})
        self.assertEqual(daemon2.jsonrpc_wallet_status(), {'is_locked': False, 'is_encrypted': False})
        self.assertEqual(daemon.jsonrpc_preference_get(ENCRYPT_ON_DISK), {'encrypt-on-disk': True})
        self.assertIsNone(daemon2.jsonrpc_preference_get(ENCRYPT_ON_DISK))
        self.assertWalletEncrypted(wallet.storage.path, True)
        self.assertWalletEncrypted(wallet2.storage.path, False)

        data = await daemon2.jsonrpc_sync_apply('password2')
        with self.assertRaises(ValueError):  # wrong password
            await daemon.jsonrpc_sync_apply('password', data=data['data'], blocking=True)
        await daemon.jsonrpc_sync_apply('password2', data=data['data'], blocking=True)

        # encryption did not change from before sync_apply
        self.assertEqual(daemon.jsonrpc_wallet_status(), {'is_locked': False, 'is_encrypted': True})
        self.assertEqual(daemon.jsonrpc_preference_get(ENCRYPT_ON_DISK), {'encrypt-on-disk': True})
        self.assertWalletEncrypted(wallet.storage.path, True)

        # old password is still used
        daemon.jsonrpc_wallet_lock()
        self.assertFalse(daemon.jsonrpc_wallet_unlock('password2'))
        self.assertTrue(daemon.jsonrpc_wallet_unlock('password'))

        # encrypt using new password
        daemon.jsonrpc_wallet_encrypt('password2')
        daemon.jsonrpc_wallet_lock()
        self.assertFalse(daemon.jsonrpc_wallet_unlock('password'))
        self.assertTrue(daemon.jsonrpc_wallet_unlock('password2'))

        data = await daemon.jsonrpc_sync_apply('password2')
        await daemon2.jsonrpc_sync_apply('password2', data=data['data'], blocking=True)

        # wallet2 is now encrypted using new password
        self.assertEqual(daemon2.jsonrpc_wallet_status(), {'is_locked': False, 'is_encrypted': True})
        self.assertEqual(daemon2.jsonrpc_preference_get(ENCRYPT_ON_DISK), {'encrypt-on-disk': True})
        self.assertWalletEncrypted(wallet.storage.path, True)

        daemon2.jsonrpc_wallet_lock()
        self.assertTrue(daemon2.jsonrpc_wallet_unlock('password2'))
