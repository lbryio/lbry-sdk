import asyncio
import json

from torba.client.wallet import ENCRYPT_ON_DISK
from lbry.testcase import CommandTestCase
from lbry.wallet.dewies import dict_values_to_lbc
from lbry.error import InvalidPasswordError


class WalletCommands(CommandTestCase):

    async def test_wallet_create_and_add_subscribe(self):
        session = next(iter(self.conductor.spv_node.server.session_mgr.sessions))
        self.assertEqual(len(session.hashX_subs), 27)
        wallet = await self.daemon.jsonrpc_wallet_create('foo', create_account=True, single_key=True)
        self.assertEqual(len(session.hashX_subs), 28)
        await self.daemon.jsonrpc_wallet_remove(wallet.id)
        self.assertEqual(len(session.hashX_subs), 27)
        await self.daemon.jsonrpc_wallet_add(wallet.id)
        self.assertEqual(len(session.hashX_subs), 28)

    async def test_balance_caching(self):
        account2 = await self.daemon.jsonrpc_account_create("Tip-er")
        address2 = await self.daemon.jsonrpc_address_unused(account2.id)
        sendtxid = await self.blockchain.send_to_address(address2, 10)
        await self.confirm_tx(sendtxid)
        await self.generate(1)

        wallet_balance = self.daemon.jsonrpc_wallet_balance
        ledger = self.ledger
        query_count = self.ledger.db.db.query_count

        expected = {
            'total': '20.0',
            'available': '20.0',
            'reserved': '0.0',
            'reserved_subtotals': {'claims': '0.0', 'supports': '0.0', 'tips': '0.0'}
        }
        self.assertIsNone(ledger._balance_cache.get(self.account.id))

        query_count += 6
        self.assertEqual(await wallet_balance(), expected)
        self.assertEqual(self.ledger.db.db.query_count, query_count)
        self.assertEqual(dict_values_to_lbc(ledger._balance_cache.get(self.account.id))['total'], '10.0')
        self.assertEqual(dict_values_to_lbc(ledger._balance_cache.get(account2.id))['total'], '10.0')

        # calling again uses cache
        self.assertEqual(await wallet_balance(), expected)
        self.assertEqual(self.ledger.db.db.query_count, query_count)
        self.assertEqual(dict_values_to_lbc(ledger._balance_cache.get(self.account.id))['total'], '10.0')
        self.assertEqual(dict_values_to_lbc(ledger._balance_cache.get(account2.id))['total'], '10.0')

        await self.stream_create()
        await self.generate(1)

        expected = {
            'total': '19.979893',
            'available': '18.979893',
            'reserved': '1.0',
            'reserved_subtotals': {'claims': '1.0', 'supports': '0.0', 'tips': '0.0'}
        }
        # on_transaction event reset balance cache
        query_count = self.ledger.db.db.query_count
        self.assertEqual(await wallet_balance(), expected)
        query_count += 3  # only one of the accounts changed
        self.assertEqual(dict_values_to_lbc(ledger._balance_cache.get(self.account.id))['total'], '9.979893')
        self.assertEqual(dict_values_to_lbc(ledger._balance_cache.get(account2.id))['total'], '10.0')
        self.assertEqual(self.ledger.db.db.query_count, query_count)

    async def test_granular_balances(self):
        account2 = await self.daemon.jsonrpc_account_create("Tip-er")

        account_balance = self.daemon.jsonrpc_account_balance
        wallet_balance = self.daemon.jsonrpc_wallet_balance

        expected = {
            'total': '10.0',
            'available': '10.0',
            'reserved': '0.0',
            'reserved_subtotals': {'claims': '0.0', 'supports': '0.0', 'tips': '0.0'}
        }
        self.assertEqual(await account_balance(), expected)
        self.assertEqual(await wallet_balance(), expected)

        # claim with update + supporting our own claim
        stream1 = await self.stream_create('granularity', '3.0')
        await self.stream_update(self.get_claim_id(stream1), data=b'news', bid='1.0')
        await self.support_create(self.get_claim_id(stream1), '2.0')
        expected = {
            'total': '9.977534',
            'available': '6.977534',
            'reserved': '3.0',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.0'}
        }
        self.assertEqual(await account_balance(), expected)
        self.assertEqual(await wallet_balance(), expected)

        address2 = await self.daemon.jsonrpc_address_unused(account2.id)

        # send lbc to someone else
        tx = await self.daemon.jsonrpc_account_send('1.0', address2)
        await self.confirm_tx(tx.id)
        self.assertEqual(await account_balance(), {
            'total': '8.97741',
            'available': '5.97741',
            'reserved': '3.0',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.0'}
        })
        self.assertEqual(await wallet_balance(), {
            'total': '9.97741',
            'available': '6.97741',
            'reserved': '3.0',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.0'}
        })

        # tip received
        support1 = await self.support_create(
            self.get_claim_id(stream1), '0.3', tip=True, funding_account_ids=[account2.id]
        )
        self.assertEqual(await account_balance(), {
            'total': '9.27741',
            'available': '5.97741',
            'reserved': '3.3',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.3'}
        })
        self.assertEqual(await wallet_balance(), {
            'total': '9.977268',
            'available': '6.677268',
            'reserved': '3.3',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.3'}
        })

        # tip claimed
        tx = await self.daemon.jsonrpc_support_abandon(txid=support1['txid'], nout=0)
        await self.confirm_tx(tx.id)
        self.assertEqual(await account_balance(), {
            'total': '9.277303',
            'available': '6.277303',
            'reserved': '3.0',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.0'}
        })
        self.assertEqual(await wallet_balance(), {
            'total': '9.977161',
            'available': '6.977161',
            'reserved': '3.0',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.0'}
        })

        stream2 = await self.stream_create(
            'granularity-is-cool', '0.1', account_id=account2.id, funding_account_ids=[account2.id]
        )

        # tip another claim
        await self.support_create(
            self.get_claim_id(stream2), '0.2', tip=True, funding_account_ids=[self.account.id]
        )
        self.assertEqual(await account_balance(), {
            'total': '9.077157',
            'available': '6.077157',
            'reserved': '3.0',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.0'}
        })
        self.assertEqual(await wallet_balance(), {
            'total': '9.938908',
            'available': '6.638908',
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
        with self.assertRaises(InvalidPasswordError):
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
