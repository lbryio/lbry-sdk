import asyncio
import random
from itertools import chain

from lbry.wallet.transaction import Transaction, Output, Input
from lbry.testcase import IntegrationTestCase
from lbry.wallet.util import satoshis_to_coins, coins_to_satoshis
from lbry.wallet.manager import WalletManager


class BasicTransactionTests(IntegrationTestCase):

    async def test_variety_of_transactions_and_longish_history(self):
        await self.blockchain.generate(300)
        await self.assertBalance(self.account, '0.0')
        addresses = await self.account.receiving.get_addresses()

        # send 10 coins to first 10 receiving addresses and then 10 transactions worth 10 coins each
        # to the 10th receiving address for a total of 30 UTXOs on the entire account
        for i in range(10):
            txid = await self.blockchain.send_to_address(addresses[i], 10)
            await self.wait_for_txid(addresses[i])
            txid = await self.blockchain.send_to_address(addresses[9], 10)
            await self.wait_for_txid(addresses[9])

        # use batching to reduce issues with send_to_address on cli
        await self.assertBalance(self.account, '200.0')
        self.assertEqual(20, await self.account.get_utxo_count())

        # address gap should have increase by 10 to cover the first 10 addresses we've used up
        addresses = await self.account.receiving.get_addresses()
        self.assertEqual(30, len(addresses))

        # there used to be a sync bug which failed to save TXIs between
        # daemon restarts, clearing cache replicates that behavior
        self.ledger._tx_cache.clear()

        # spend from each of the first 10 addresses to the subsequent 10 addresses
        txs = []
        for address in addresses[10:20]:
            txs.append(await Transaction.create(
                [],
                [Output.pay_pubkey_hash(
                    coins_to_satoshis('1.0'), self.ledger.address_to_hash160(address)
                )],
                [self.account], self.account
            ))
        await asyncio.wait([self.broadcast(tx) for tx in txs])
        await asyncio.wait([self.ledger.wait(tx) for tx in txs])

        # verify that a previous bug which failed to save TXIs doesn't come back
        # this check must happen before generating a new block
        self.assertTrue(all([
            tx.inputs[0].txo_ref.txo is not None
            for tx in await self.ledger.db.get_transactions(txid__in=[tx.id for tx in txs])
        ]))

        await self.blockchain.generate(1)
        await asyncio.wait([self.ledger.wait(tx) for tx in txs])
        await self.assertBalance(self.account, '199.99876')

        # 10 of the UTXOs have been split into a 1 coin UTXO and a 9 UTXO change
        self.assertEqual(30, await self.account.get_utxo_count())

        # spend all 30 UTXOs into a a 199 coin UTXO and change
        tx = await Transaction.create(
            [],
            [Output.pay_pubkey_hash(
                coins_to_satoshis('199.0'), self.ledger.address_to_hash160(addresses[-1])
            )],
            [self.account], self.account
        )
        await self.broadcast(tx)
        await self.ledger.wait(tx)
        await self.blockchain.generate(1)
        await self.ledger.wait(tx)

        self.assertEqual(2, await self.account.get_utxo_count())  # 199 + change
        await self.assertBalance(self.account, '199.99649')

    async def test_sending_and_receiving(self):
        account1, account2 = self.account, self.wallet.generate_account(self.ledger)
        await self.ledger.subscribe_account(account2)

        await self.assertBalance(account1, '0.0')
        await self.assertBalance(account2, '0.0')

        addresses = await account1.receiving.get_addresses()
        txids = await asyncio.gather(*(
            self.blockchain.send_to_address(address, 1.1) for address in addresses[:5]
        ))
        await asyncio.wait([self.on_transaction_id(txid) for txid in txids])  # mempool
        await self.blockchain.generate(1)
        await asyncio.wait([self.on_transaction_id(txid) for txid in txids])  # confirmed
        await self.assertBalance(account1, '5.5')
        await self.assertBalance(account2, '0.0')

        address2 = await account2.receiving.get_or_create_usable_address()
        tx = await Transaction.create(
            [],
            [Output.pay_pubkey_hash(
                coins_to_satoshis('2.0'), self.ledger.address_to_hash160(address2)
            )],
            [account1], account1
        )
        await self.broadcast(tx)
        await self.ledger.wait(tx)  # mempool
        await self.blockchain.generate(1)
        await self.ledger.wait(tx)  # confirmed

        await self.assertBalance(account1, '3.499802')
        await self.assertBalance(account2, '2.0')

        utxos = await self.account.get_utxos()
        tx = await Transaction.create(
            [Input.spend(utxos[0])],
            [],
            [account1], account1
        )
        await self.broadcast(tx)
        await self.ledger.wait(tx)  # mempool
        await self.blockchain.generate(1)
        await self.ledger.wait(tx)  # confirmed

        tx = (await account1.get_transactions(include_is_my_input=True, include_is_my_output=True))[1]
        self.assertEqual(satoshis_to_coins(tx.inputs[0].amount), '1.1')
        self.assertEqual(satoshis_to_coins(tx.inputs[1].amount), '1.1')
        self.assertEqual(satoshis_to_coins(tx.outputs[0].amount), '2.0')
        self.assertEqual(tx.outputs[0].get_address(self.ledger), address2)
        self.assertTrue(tx.outputs[0].is_internal_transfer)
        self.assertTrue(tx.outputs[1].is_internal_transfer)

    async def test_history_edge_cases(self):
        await self.blockchain.generate(300)
        await self.assertBalance(self.account, '0.0')
        address = await self.account.receiving.get_or_create_usable_address()
        # evil trick: mempool is unsorted on real life, but same order between python instances. reproduce it
        original_summary = self.conductor.spv_node.server.bp.mempool.transaction_summaries

        def random_summary(*args, **kwargs):
            summary = original_summary(*args, **kwargs)
            if summary and len(summary) > 2:
                ordered = summary.copy()
                while summary == ordered:
                    random.shuffle(summary)
            return summary
        self.conductor.spv_node.server.bp.mempool.transaction_summaries = random_summary
        # 10 unconfirmed txs, all from blockchain wallet
        sends = [self.blockchain.send_to_address(address, 10) for _ in range(10)]
        # use batching to reduce issues with send_to_address on cli
        for batch in range(0, len(sends), 10):
            txids = await asyncio.gather(*sends[batch:batch + 10])
            await asyncio.wait([self.on_transaction_id(txid) for txid in txids])
        remote_status = await self.ledger.network.subscribe_address(address)
        self.assertTrue(await self.ledger.update_history(address, remote_status))
        # 20 unconfirmed txs, 10 from blockchain, 10 from local to local
        utxos = await self.account.get_utxos()
        txs = []
        for utxo in utxos:
            tx = await Transaction.create(
                [Input.spend(utxo)],
                [],
                [self.account], self.account
            )
            await self.broadcast(tx)
            txs.append(tx)
        await asyncio.wait([self.on_transaction_address(tx, address) for tx in txs], timeout=1)
        remote_status = await self.ledger.network.subscribe_address(address)
        self.assertTrue(await self.ledger.update_history(address, remote_status))
        # server history grows unordered
        txid = await self.blockchain.send_to_address(address, 1)
        await self.on_transaction_id(txid)
        self.assertTrue(await self.ledger.update_history(address, remote_status))
        self.assertEqual(21, len((await self.ledger.get_local_status_and_history(address))[1]))
        self.assertEqual(0, len(self.ledger._known_addresses_out_of_sync))

    def wait_for_txid(self, address):
        return asyncio.ensure_future(self.ledger.on_transaction.where(
            lambda e: e.address == address
        ))

    async def _test_transaction(self, send_amount, address, inputs, change):
        tx = await Transaction.create(
            [], [Output.pay_pubkey_hash(send_amount, self.ledger.address_to_hash160(address))], [self.account],
            self.account
        )
        await self.ledger.broadcast(tx)
        input_amounts = [txi.amount for txi in tx.inputs]
        self.assertListEqual(inputs, input_amounts)
        self.assertEqual(len(inputs), len(tx.inputs))
        self.assertEqual(2, len(tx.outputs))
        self.assertEqual(send_amount, tx.outputs[0].amount)
        self.assertEqual(change, tx.outputs[1].amount)
        return tx

    async def assertSpendable(self, amounts):
        spendable = await self.ledger.db.get_spendable_utxos(
                self.ledger, 2000000000000, [self.account], set_reserved=False, return_insufficient_funds=True
            )
        got_amounts = [estimator.effective_amount for estimator in spendable]
        self.assertListEqual(amounts, got_amounts)

    async def test_sqlite_coin_chooser(self):
        wallet_manager = WalletManager([self.wallet], {self.ledger.get_id(): self.ledger})
        await self.blockchain.generate(300)
        await self.assertBalance(self.account, '0.0')
        address = await self.account.receiving.get_or_create_usable_address()
        other_account = self.wallet.generate_account(self.ledger)
        other_address = await other_account.receiving.get_or_create_usable_address()
        self.ledger.coin_selection_strategy = 'sqlite'
        await self.ledger.subscribe_account(self.account)
        accepted = self.wait_for_txid(address)

        txid = await self.blockchain.send_to_address(address, 1.0)
        await accepted

        accepted = self.wait_for_txid(address)
        txid = await self.blockchain.send_to_address(address, 1.0)
        await accepted

        accepted = self.wait_for_txid(address)
        txid = await self.blockchain.send_to_address(address, 3.0)
        await accepted

        accepted = self.wait_for_txid(address)
        txid = await self.blockchain.send_to_address(address, 5.0)
        await accepted

        accepted = self.wait_for_txid(address)
        txid = await self.blockchain.send_to_address(address, 10.0)
        await accepted

        await self.assertBalance(self.account, '20.0')
        await self.assertSpendable([99992600, 99992600, 299992600, 499992600, 999992600])

        # send 1.5 lbc

        first_tx = await Transaction.create(
            [], [Output.pay_pubkey_hash(150000000, self.ledger.address_to_hash160(other_address))], [self.account],
            self.account
        )

        self.assertEqual(2, len(first_tx.inputs))
        self.assertEqual(2, len(first_tx.outputs))
        self.assertEqual(100000000, first_tx.inputs[0].amount)
        self.assertEqual(100000000, first_tx.inputs[1].amount)
        self.assertEqual(150000000, first_tx.outputs[0].amount)
        self.assertEqual(49980200, first_tx.outputs[1].amount)

        await self.assertBalance(self.account, '18.0')
        await self.assertSpendable([299992600, 499992600, 999992600])

        await wallet_manager.broadcast_or_release(first_tx, blocking=True)
        await self.assertSpendable([49972800, 299992600, 499992600, 999992600])
        # 0.499, 3.0, 5.0, 10.0
        await self.assertBalance(self.account, '18.499802')

        # send 1.5lbc again

        second_tx = await self._test_transaction(150000000, other_address, [49980200, 300000000], 199960400)
        await self.assertSpendable([499992600, 999992600])

        # replicate cancelling the api call after the tx broadcast while ledger.wait'ing it
        e = asyncio.Event()

        real_broadcast = self.ledger.broadcast

        async def broadcast(tx):
            try:
                return await real_broadcast(tx)
            finally:
                e.set()

        self.ledger.broadcast = broadcast

        broadcast_task = asyncio.create_task(wallet_manager.broadcast_or_release(second_tx, blocking=True))
        # wait for the broadcast to finish
        await e.wait()
        # cancel the api call
        broadcast_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await broadcast_task

        # test if sending another 1.5 lbc will try to double spend the inputs from the cancelled tx
        tx1 = await self._test_transaction(150000000, other_address, [500000000], 349987600)
        await self.ledger.wait(tx1, timeout=1)
        # wait for the cancelled transaction too, so that it's in the database
        # needed to keep everything deterministic
        await self.ledger.wait(second_tx, timeout=1)
        await self.assertSpendable([199953000, 349980200, 999992600])

        # spend deep into the mempool and see what else breaks
        tx2 = await self._test_transaction(150000000, other_address, [199960400], 49948000)
        await self.assertSpendable([349980200, 999992600])
        await self.ledger.wait(tx2, timeout=1)
        await self.assertSpendable([49940600, 349980200, 999992600])

        tx3 = await self._test_transaction(150000000, other_address, [49948000, 349987600], 249915800)
        await self.assertSpendable([999992600])
        await self.ledger.wait(tx3, timeout=1)
        await self.assertSpendable([249908400, 999992600])

        tx4 = await self._test_transaction(150000000, other_address, [249915800], 99903400)
        await self.assertSpendable([999992600])
        await self.ledger.wait(tx4, timeout=1)
        await self.assertBalance(self.account, '10.999034')
        await self.assertSpendable([99896000, 999992600])

        # spend more
        tx5 = await self._test_transaction(100000000, other_address, [99903400, 1000000000], 999883600)
        await self.assertSpendable([])
        await self.ledger.wait(tx5, timeout=1)
        await self.assertSpendable([999876200])
        await self.assertBalance(self.account, '9.998836')
