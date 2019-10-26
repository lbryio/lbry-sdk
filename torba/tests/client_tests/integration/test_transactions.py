import logging
import asyncio
import random
from itertools import chain
from random import shuffle

from torba.testcase import IntegrationTestCase
from torba.client.util import satoshis_to_coins, coins_to_satoshis


class BasicTransactionTests(IntegrationTestCase):

    VERBOSITY = logging.WARN

    async def test_variety_of_transactions_and_longish_history(self):
        await self.blockchain.generate(300)
        await self.assertBalance(self.account, '0.0')
        addresses = await self.account.receiving.get_addresses()

        # send 10 coins to first 10 receiving addresses and then 10 transactions worth 10 coins each
        # to the 10th receiving address for a total of 30 UTXOs on the entire account
        sends = list(chain(
            (self.blockchain.send_to_address(address, 10) for address in addresses[:10]),
            (self.blockchain.send_to_address(addresses[9], 10) for _ in range(10))
        ))
        # use batching to reduce issues with send_to_address on cli
        for batch in range(0, len(sends), 10):
            txids = await asyncio.gather(*sends[batch:batch+10])
            await asyncio.wait([self.on_transaction_id(txid) for txid in txids])
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
            txs.append(await self.ledger.transaction_class.create(
                [],
                [self.ledger.transaction_class.output_class.pay_pubkey_hash(
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
        tx = await self.ledger.transaction_class.create(
            [],
            [self.ledger.transaction_class.output_class.pay_pubkey_hash(
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
        tx = await self.ledger.transaction_class.create(
            [],
            [self.ledger.transaction_class.output_class.pay_pubkey_hash(
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
        tx = await self.ledger.transaction_class.create(
            [self.ledger.transaction_class.input_class.spend(utxos[0])],
            [],
            [account1], account1
        )
        await self.broadcast(tx)
        await self.ledger.wait(tx)  # mempool
        await self.blockchain.generate(1)
        await self.ledger.wait(tx)  # confirmed

        tx = (await account1.get_transactions())[1]
        self.assertEqual(satoshis_to_coins(tx.inputs[0].amount), '1.1')
        self.assertEqual(satoshis_to_coins(tx.inputs[1].amount), '1.1')
        self.assertEqual(satoshis_to_coins(tx.outputs[0].amount), '2.0')
        self.assertEqual(tx.outputs[0].get_address(self.ledger), address2)
        self.assertFalse(tx.outputs[0].is_change)
        self.assertTrue(tx.outputs[1].is_change)

    async def test_history_edge_cases(self):
        await self.assertBalance(self.account, '0.0')
        address = await self.account.receiving.get_or_create_usable_address()
        # evil trick: mempool is unsorted on real life, but same order between python instances. reproduce it
        original_summary = self.conductor.spv_node.server.mempool.transaction_summaries

        async def random_summary(*args, **kwargs):
            summary = await original_summary(*args, **kwargs)
            if summary and len(summary) > 2:
                ordered = summary.copy()
                while summary == ordered:
                    random.shuffle(summary)
            return summary
        self.conductor.spv_node.server.mempool.transaction_summaries = random_summary
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
            tx = await self.ledger.transaction_class.create(
                [self.ledger.transaction_class.input_class.spend(utxo)],
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
        # should be another test, but it would be too much to setup just for that and it affects sync
        self.assertIsNone(await self.ledger.network.retriable_call(self.ledger.network.get_transaction, '1'*64))
