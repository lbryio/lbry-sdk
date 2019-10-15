import asyncio
from lbry.testcase import CommandTestCase
from binascii import unhexlify


class WalletSynchronization(CommandTestCase):
    SEED = "carbon smart garage balance margin twelve chest sword toast envelope bottom stomach absent"

    async def test_sync(self):
        daemon = self.daemon
        daemon2 = await self.add_daemon(
            seed="chest sword toast envelope bottom stomach absent "
                 "carbon smart garage balance margin twelve"
        )
        address = (await daemon2.wallet_manager.default_account.receiving.get_addresses(limit=1, only_usable=True))[0]
        sendtxid = await self.blockchain.send_to_address(address, 1)
        await self.confirm_tx(sendtxid, daemon2.ledger)

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
        self.assertDictEqual(daemon2.jsonrpc_preference_get(), {"two": "2", "conflict": "2"})

        self.assertEqual(len((await daemon.jsonrpc_account_list())['lbc_regtest']), 1)

        daemon2.jsonrpc_wallet_encrypt('password')
        daemon2.jsonrpc_wallet_lock()
        with self.assertRaises(AssertionError):
            await daemon2.jsonrpc_sync_apply('password')

        daemon2.jsonrpc_wallet_unlock('password')
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
        await daemon2.ledger.wait(channel)
        await self.generate(1)
        await daemon2.ledger.wait(channel)

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
