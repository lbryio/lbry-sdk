import json
import asyncio
from unittest import skip

from sqlalchemy import event

from lbry.wallet.wallet import ENCRYPT_ON_DISK
from lbry.error import InvalidPasswordError
from lbry.testcase import CommandTestCase
from lbry.blockchain.dewies import dict_values_to_lbc


class WalletCommands(CommandTestCase):

    async def test_list_create_add_and_remove(self):
        self.assertEqual(await self.wallet_list(), [{'id': 'default_wallet', 'name': 'Wallet'}])
        self.assertEqual(
            await self.wallet_create('another', "Another"),
            {'id': 'another', 'name': 'Another'}
        )
        self.assertEqual(await self.wallet_list(), [
            {'id': 'default_wallet', 'name': 'Wallet'},
            {'id': 'another', 'name': 'Another'}
        ])
        self.assertEqual(await self.wallet_remove('another'), {'id': 'another', 'name': 'Another'})
        self.assertEqual(await self.wallet_list(), [{'id': 'default_wallet', 'name': 'Wallet'}])
        self.assertEqual(await self.wallet_add('another'), {'id': 'another', 'name': 'Another'})
        self.assertEqual(await self.wallet_list(), [
            {'id': 'default_wallet', 'name': 'Wallet'},
            {'id': 'another', 'name': 'Another'}
        ])

    @skip
    async def test_reconnect(self):
        await self.conductor.spv_node.stop(True)
        self.conductor.spv_node.port = 54320
        await self.conductor.spv_node.start(self.conductor.blockchain_node)
        status = await self.daemon.jsonrpc_status()
        self.assertEqual(len(status['wallet']['servers']), 1)
        self.assertEqual(status['wallet']['servers'][0]['port'], 50002)
        self.daemon.jsonrpc_settings_set('lbryum_servers', ['localhost:54320'])
        await self.daemon.jsonrpc_wallet_reconnect()
        status = await self.daemon.jsonrpc_status()
        self.assertEqual(len(status['wallet']['servers']), 1)
        self.assertEqual(status['wallet']['servers'][0]['port'], 54320)

    async def test_granular_balances(self):
        account2 = (await self.account_create("Tip-er"))["id"]
        wallet2 = (await self.wallet_create("foo", create_account=True))["id"]
        account3 = (await self.account_list(wallet_id=wallet2))[0]["id"]
        address3 = await self.address_unused(account3, wallet2)
        await self.chain.send_to_address(address3, 1)
        await self.generate(1)

        expected = {
            'total': '10.0',
            'available': '10.0',
            'reserved': '0.0',
            'reserved_subtotals': {'claims': '0.0', 'supports': '0.0', 'tips': '0.0'}
        }
        self.assertEqual(await self.account_balance(), expected)
        self.assertEqual(await self.wallet_balance(), expected)

        # claim with update + supporting our own claim
        stream1 = await self.stream_create('granularity', '3.0')
        await self.generate(1)
        await self.stream_update(self.get_claim_id(stream1), data=b'news', bid='1.0')
        await self.generate(1)
        await self.support_create(self.get_claim_id(stream1), '2.0')
        expected = {
            'total': '9.977558',
            'available': '6.977558',
            'reserved': '3.0',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.0'}
        }
        self.assertEqual(await self.account_balance(), expected)
        self.assertEqual(await self.wallet_balance(), expected)

        address2 = await self.address_unused(account2)

        # send lbc to someone else
        tx = await self.wallet_send('1.0', address2, fund_account_id=self.account.id)
        await self.generate(1)
        self.assertEqual(await self.account_balance(), {
            'total': '8.977434',
            'available': '5.977434',
            'reserved': '3.0',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.0'}
        })
        self.assertEqual(await self.wallet_balance(), {
            'total': '9.977434',
            'available': '6.977434',
            'reserved': '3.0',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.0'}
        })

        # tip received
        support1 = await self.support_create(
            self.get_claim_id(stream1), '0.3', tip=True, wallet_id=wallet2
        )
        self.assertEqual(await self.account_balance(), {
            'total': '9.277434',
            'available': '5.977434',
            'reserved': '3.3',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.3'}
        })
        self.assertEqual(await self.wallet_balance(), {
            'total': '10.277434',
            'available': '6.977434',
            'reserved': '3.3',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.3'}
        })

        # tip claimed
        tx = await self.support_abandon(txid=support1['txid'])
        await self.generate(1)
        self.assertEqual(await self.account_balance(), {
            'total': '9.277327',
            'available': '6.277327',
            'reserved': '3.0',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.0'}
        })
        self.assertEqual(await self.wallet_balance(), {
            'total': '10.277327',
            'available': '7.277327',
            'reserved': '3.0',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.0'}
        })

        stream2 = await self.stream_create(
            'granularity-is-cool', '0.1',
            account_id=account2, fund_account_id=[account2], change_account_id=account2
        )

        # tip another claim
        await self.support_create(
            self.get_claim_id(stream2), '0.2', tip=True, wallet_id=wallet2
        )
        self.assertEqual(await self.account_balance(), {
            'total': '9.277327',
            'available': '6.277327',
            'reserved': '3.0',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.0'}
        })
        self.assertEqual(await self.wallet_balance(), {
            'total': '10.43922',
            'available': '7.13922',
            'reserved': '3.3',
            'reserved_subtotals': {'claims': '1.1', 'supports': '2.0', 'tips': '0.2'}
        })


class WalletEncryptionAndSynchronization(CommandTestCase):

    SEED = (
        "carbon smart garage balance margin twelve chest "
        "sword toast envelope bottom stomach absent"
    )

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.daemon2 = await self.add_full_node(
            seed="chest sword toast envelope bottom stomach absent "
                 "carbon smart garage balance margin twelve"
        )
        address = (await self.daemon2.wallet_manager.default_account.receiving.get_addresses(limit=1, only_usable=True))[0]
        sendtxid = await self.blockchain.send_to_address(address, 1)
        await self.confirm_tx(sendtxid, self.daemon2.ledger)

    def assertWalletEncrypted(self, wallet_path, encrypted):
        with open(wallet_path) as opened:
            wallet = json.load(opened)
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

        self.assertItemCount(await daemon.jsonrpc_account_list(), 1)

        data = await daemon2.jsonrpc_sync_apply('password')
        await daemon.jsonrpc_sync_apply('password', data=data['data'], blocking=True)

        self.assertItemCount(await daemon.jsonrpc_account_list(), 2)
        self.assertDictEqual(
            # "two" key added and "conflict" value changed to "2"
            daemon.jsonrpc_preference_get(),
            {"one": "1", "two": "2", "conflict": "2", "another": "B", "fruit": ["peach", "apricot"]}
        )

        # Channel Certificate
        channel = await daemon2.jsonrpc_channel_create('@foo', '0.1')
        await self.confirm_tx(channel.id, self.daemon2.ledger)

        # both daemons will have the channel but only one has the cert so far
        self.assertItemCount(await daemon.jsonrpc_channel_list(), 1)
        self.assertEqual(len(daemon.wallet_manager.default_wallet.accounts[1].channel_keys), 0)
        self.assertItemCount(await daemon2.jsonrpc_channel_list(), 1)
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

        self.assertEqual(daemon.jsonrpc_wallet_status(), {
            'is_locked': False, 'is_encrypted': False, 'is_syncing': False
        })
        self.assertIsNone(daemon.jsonrpc_preference_get(ENCRYPT_ON_DISK))
        self.assertWalletEncrypted(wallet.storage.path, False)

        # can't lock an unencrypted account
        with self.assertRaisesRegex(AssertionError, "Cannot lock an unencrypted wallet, encrypt first."):
            daemon.jsonrpc_wallet_lock()
        # safe to call unlock and decrypt, they are no-ops at this point
        daemon.jsonrpc_wallet_unlock('password')  # already unlocked
        daemon.jsonrpc_wallet_decrypt()  # already not encrypted

        daemon.jsonrpc_wallet_encrypt('password')
        self.assertEqual(daemon.jsonrpc_wallet_status(), {'is_locked': False, 'is_encrypted': True,
                                                          'is_syncing': False})
        self.assertEqual(daemon.jsonrpc_preference_get(ENCRYPT_ON_DISK), {'encrypt-on-disk': True})
        self.assertWalletEncrypted(wallet.storage.path, True)

        daemon.jsonrpc_wallet_lock()
        self.assertEqual(daemon.jsonrpc_wallet_status(), {'is_locked': True, 'is_encrypted': True,
                                                          'is_syncing': False})

        # can't sign transactions with locked wallet
        with self.assertRaises(AssertionError):
            await daemon.jsonrpc_channel_create('@foo', '1.0')
        daemon.jsonrpc_wallet_unlock('password')
        self.assertEqual(daemon.jsonrpc_wallet_status(), {'is_locked': False, 'is_encrypted': True,
                                                          'is_syncing': False})
        await daemon.jsonrpc_channel_create('@foo', '1.0')

        daemon.jsonrpc_wallet_decrypt()
        self.assertEqual(daemon.jsonrpc_wallet_status(), {'is_locked': False, 'is_encrypted': False,
                                                          'is_syncing': False})
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
        self.assertEqual(daemon2.jsonrpc_wallet_status(),
                         {'is_locked': False, 'is_encrypted': True, 'is_syncing': False})

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
        with self.assertRaises(InvalidPasswordError):
            await daemon.jsonrpc_sync_apply('password', data=data['data'], blocking=True)
        await daemon.jsonrpc_sync_apply('password2', data=data['data'], blocking=True)
        # sync_apply with new password2 also sets it as new local password
        self.assertEqual(wallet.encryption_password, 'password2')
        self.assertEqual(daemon.jsonrpc_wallet_status(), {'is_locked': False, 'is_encrypted': True,
                                                          'is_syncing': True})
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
        self.assertEqual(daemon2.jsonrpc_wallet_status(), {'is_locked': False, 'is_encrypted': True,
                                                           'is_syncing': True})
        self.assertEqual(daemon2.jsonrpc_preference_get(ENCRYPT_ON_DISK), {'encrypt-on-disk': True})
        self.assertWalletEncrypted(wallet2.storage.path, True)

        daemon2.jsonrpc_wallet_lock()
        self.assertTrue(daemon2.jsonrpc_wallet_unlock('password3'))
