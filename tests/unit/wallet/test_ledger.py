from torba.testcase import AsyncioTestCase
from torba.client.wallet import Wallet

from lbrynet.extras.wallet.account import Account
from lbrynet.extras.wallet.transaction import Transaction, Output, Input
from lbrynet.extras.wallet.ledger import MainNetLedger


class LedgerTestCase(AsyncioTestCase):

    async def asyncSetUp(self):
        self.ledger = MainNetLedger({
            'db': MainNetLedger.database_class(':memory:'),
            'headers': MainNetLedger.headers_class(':memory:')
        })
        self.account = Account.generate(self.ledger, Wallet(), "lbryum")
        await self.ledger.db.open()

    async def asyncTearDown(self):
        await self.ledger.db.close()


class BasicAccountingTests(LedgerTestCase):

    async def test_empty_state(self):
        self.assertEqual(await self.account.get_balance(), 0)

    async def test_balance(self):
        address = await self.account.receiving.get_or_create_usable_address()
        hash160 = self.ledger.address_to_hash160(address)

        tx = Transaction(is_verified=True)\
            .add_outputs([Output.pay_pubkey_hash(100, hash160)])
        await self.ledger.db.insert_transaction(tx)
        await self.ledger.db.save_transaction_io(
            tx, address, hash160, '{}:{}:'.format(tx.id, 1)
        )
        self.assertEqual(await self.account.get_balance(), 100)

        tx = Transaction(is_verified=True)\
            .add_outputs([Output.pay_claim_name_pubkey_hash(100, 'foo', b'', hash160)])
        await self.ledger.db.insert_transaction(tx)
        await self.ledger.db.save_transaction_io(
            tx, address, hash160, '{}:{}:'.format(tx.id, 1)
        )
        self.assertEqual(await self.account.get_balance(), 100)  # claim names don't count towards balance
        self.assertEqual(await self.account.get_balance(include_claims=True), 200)

    async def test_get_utxo(self):
        address = yield self.account.receiving.get_or_create_usable_address()
        hash160 = self.ledger.address_to_hash160(address)

        tx = Transaction(is_verified=True)\
            .add_outputs([Output.pay_pubkey_hash(100, hash160)])
        await self.ledger.db.save_transaction_io(
            'insert', tx, address, hash160, '{}:{}:'.format(tx.id, 1)
        )

        utxos = await self.account.get_utxos()
        self.assertEqual(len(utxos), 1)

        tx = Transaction(is_verified=True)\
            .add_inputs([Input.spend(utxos[0])])
        await self.ledger.db.save_transaction_io(
            'insert', tx, address, hash160, '{}:{}:'.format(tx.id, 1)
        )
        self.assertEqual(await self.account.get_balance(include_claims=True), 0)

        utxos = await self.account.get_utxos()
        self.assertEqual(len(utxos), 0)
