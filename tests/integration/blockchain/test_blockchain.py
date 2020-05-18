import os
import time
import asyncio
import shutil
import tempfile
from binascii import hexlify, unhexlify
from random import choice

from lbry.conf import Config
from lbry.db import Database
from lbry.crypto.base58 import Base58
from lbry.schema.claim import Stream
from lbry.blockchain.lbrycrd import Lbrycrd
from lbry.blockchain.dewies import dewies_to_lbc, lbc_to_dewies
from lbry.blockchain.transaction import Transaction, Output
from lbry.constants import CENT
from lbry.blockchain.ledger import RegTestLedger
from lbry.testcase import AsyncioTestCase

from lbry.service.full_node import FullNode
from lbry.service.light_client import LightClient
from lbry.service.daemon import Daemon
from lbry.service.api import Client


class BlockchainTestCase(AsyncioTestCase):

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.chain = Lbrycrd.temp_regtest()
        self.ledger = self.chain.ledger
        await self.chain.ensure()
        await self.chain.start('-maxblockfilesize=8', '-rpcworkqueue=128')
        self.addCleanup(self.chain.stop)


class TestEvents(BlockchainTestCase):

    async def test_block_event(self):
        msgs = []

        self.chain.subscribe()
        self.chain.on_block.listen(lambda e: msgs.append(e['msg']))
        res = await self.chain.generate(5)
        await self.chain.on_block.where(lambda e: e['msg'] == 4)
        self.assertEqual([0, 1, 2, 3, 4], msgs)
        self.assertEqual(5, len(res))

        self.chain.unsubscribe()
        res = await self.chain.generate(2)
        self.assertEqual(2, len(res))
        await asyncio.sleep(0.1)  # give some time to "miss" the new block events

        self.chain.subscribe()
        res = await self.chain.generate(3)
        await self.chain.on_block.where(lambda e: e['msg'] == 9)
        self.assertEqual(3, len(res))
        self.assertEqual([0, 1, 2, 3, 4, 7, 8, 9], msgs)  # 5, 6 "missed"


class TestBlockchainSync(BlockchainTestCase):

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.service = FullNode(
            self.ledger, f'sqlite:///{self.chain.data_dir}/lbry.db', Lbrycrd(self.ledger)
        )
        #self.service.conf.spv_address_filters = False
        self.sync = self.service.sync
        self.db = self.service.db
        await self.db.open()
        self.addCleanup(self.db.close)
        await self.sync.chain.open()
        self.addCleanup(self.sync.chain.close)

    async def test_multi_block_file_sync(self):
        names = ['one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']
        await self.chain.generate(101)
        address = Base58.decode(await self.chain.get_new_address())
        start = time.perf_counter()
        for _ in range(190):
            tx = Transaction().add_outputs([
                Output.pay_claim_name_pubkey_hash(
                    CENT, f'{choice(names)}{i}',
                    Stream().update(
                        title='a claim title',
                        description='Lorem ipsum '*400,
                        tags=['crypto', 'health', 'space'],
                    ).claim,
                    address)
                for i in range(1, 20)
            ])
            funded = await self.chain.fund_raw_transaction(hexlify(tx.raw).decode())
            signed = await self.chain.sign_raw_transaction_with_wallet(funded['hex'])
            await self.chain.send_raw_transaction(signed['hex'])
            await self.chain.generate(1)

        print(f'generating {190*20} transactions took {time.perf_counter()-start}s')

        self.assertEqual(
            [(0, 191, 280), (1, 89, 178), (2, 12, 24)],
            [(file['file_number'], file['blocks'], file['txs'])
             for file in await self.chain.db.get_block_files()]
        )
        self.assertEqual(191, len(await self.chain.db.get_file_details(0)))

        await self.sync.advance()

        print('here')


class FullNodeTestCase(BlockchainTestCase):

    async def asyncSetUp(self):
        await super().asyncSetUp()

        self.current_height = 0
        await self.generate(101, wait=False)

        self.service = FullNode(self.ledger, f'sqlite:///{self.chain.data_dir}/lbry.db')
        self.service.conf.spv_address_filters = False
        self.sync = self.service.sync
        self.db = self.service.db

        self.daemon = Daemon(self.service)
        self.api = self.daemon.api
        self.addCleanup(self.daemon.stop)
        await self.daemon.start()

        if False: #os.environ.get('TEST_LBRY_API', 'light_client') == 'light_client':
            light_dir = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, light_dir, True)

            ledger = RegTestLedger(Config(
                data_dir=light_dir,
                wallet_dir=light_dir,
                api='localhost:5389',
            ))

            self.light_client = self.service = LightClient(
                ledger, f'sqlite:///{light_dir}/light_client.db'
            )
            self.light_api = Daemon(self.service)
            await self.light_api.start()
            self.addCleanup(self.light_api.stop)
        #else:
        #    self.service = self.full_node

        #self.client = Client(self.service, self.ledger.conf.api_connection_url)

    async def generate(self, blocks, wait=True):
        block_hashes = await self.chain.generate(blocks)
        self.current_height += blocks
        if wait:
            await self.service.sync.on_block.where(
                lambda b: self.current_height == b.height
            )
        return block_hashes


class TestFullNode(FullNodeTestCase):

    async def test_foo(self):
        await self.generate(10)
        wallet = self.service.wallet_manager.default_wallet #create_wallet('test_wallet')
        account = wallet.accounts[0]
        addresses = await account.ensure_address_gap()
        await self.chain.send_to_address(addresses[0], '5.0')
        await self.generate(1)
        self.assertEqual(await account.get_balance(), lbc_to_dewies('5.0'))
        #self.assertEqual((await self.client.account_balance())['total'], '5.0')

        tx = await wallet.create_channel('@foo', lbc_to_dewies('1.0'), account, [account], addresses[0])
        await self.service.broadcast(tx)
        await self.generate(1)
        channels = await wallet.get_channels()
        print(channels)


class TestClaimtrieSync(FullNodeTestCase):

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.last_block_hash = None
        self.address = await self.chain.get_new_address()

    def find_claim_txo(self, tx):
        for txo in tx.outputs:
            if txo.is_claim:
                return txo

    async def get_transaction(self, txid):
        raw = await self.chain.get_raw_transaction(txid)
        return Transaction(unhexlify(raw))

    async def claim_name(self, title, amount):
        claim = Stream().update(title=title).claim
        return await self.chain.claim_name(
            'foo', hexlify(claim.to_bytes()).decode(), amount
        )

    async def claim_update(self, tx, amount):
        claim = self.find_claim_txo(tx).claim
        return await self.chain.update_claim(
            tx.outputs[0].tx_ref.id, hexlify(claim.to_bytes()).decode(), amount
        )

    async def claim_abandon(self, tx):
        return await self.chain.abandon_claim(tx.id, self.address)

    async def support_claim(self, tx, amount):
        txo = self.find_claim_txo(tx)
        response = await self.chain.support_claim(
            txo.claim_name, txo.claim_id, amount
        )
        return response['txId']

    async def advance(self, new_height, ops):
        blocks = (new_height-self.current_height)-1
        if blocks > 0:
            await self.generate(blocks)
        txs = []
        for op in ops:
            if len(op) == 3:
                op_type, value, amount = op
            else:
                (op_type, value), amount = op, None
            if op_type == 'claim':
                txid = await self.claim_name(value, amount)
            elif op_type == 'update':
                txid = await self.claim_update(value, amount)
            elif op_type == 'abandon':
                txid = await self.claim_abandon(value)
            elif op_type == 'support':
                txid = await self.support_claim(value, amount)
            else:
                raise ValueError(f'"{op_type}" is unknown operation')
            txs.append(await self.get_transaction(txid))
        self.last_block_hash, = await self.generate(1)
        self.current_height = new_height
        return txs

    async def get_last_block(self):
        return await self.chain.get_block(self.last_block_hash)

    async def get_controlling(self):
        sql = f"""
            select
                tx.height, tx.raw, txo.position, effective_amount, activation_height
            from claimtrie
                join claim using (claim_hash)
                join txo using (txo_hash)
                join tx using (tx_hash)
            where
                txo.txo_type in (1, 2) and
                expiration_height > {self.current_height}
        """
        for claim in await self.db.execute_fetchall(sql):
            tx = Transaction(claim['raw'], height=claim['height'])
            txo = tx.outputs[claim['position']]
            return (
                txo.claim.stream.title, dewies_to_lbc(txo.amount),
                dewies_to_lbc(claim['effective_amount']), claim['activation_height']
            )

    async def get_active(self):
        controlling = await self.get_controlling()
        active = []
        sql = f"""
        select tx.height, tx.raw, txo.position, effective_amount, activation_height
        from txo
            join tx using (tx_hash)
            join claim using (claim_hash)
        where
            txo.txo_type in (1, 2) and
            activation_height <= {self.current_height} and
            expiration_height > {self.current_height}
        """
        for claim in await self.db.execute_fetchall(sql):
            tx = Transaction(claim['raw'], height=claim['height'])
            txo = tx.outputs[claim['position']]
            if controlling and controlling[0] == txo.claim.stream.title:
                continue
            active.append((
                txo.claim.stream.title, dewies_to_lbc(txo.amount),
                dewies_to_lbc(claim['effective_amount']), claim['activation_height']
            ))
        return active

    async def get_accepted(self):
        accepted = []
        sql = f"""
        select tx.height, tx.raw, txo.position, effective_amount, activation_height
        from txo
            join tx using (tx_hash)
            join claim using (claim_hash)
        where
            txo.txo_type in (1, 2) and
            activation_height > {self.current_height} and
            expiration_height > {self.current_height}
        """
        for claim in await self.db.execute_fetchall(sql):
            tx = Transaction(claim['raw'], height=claim['height'])
            txo = tx.outputs[claim['position']]
            accepted.append((
                txo.claim.stream.title, dewies_to_lbc(txo.amount),
                dewies_to_lbc(claim['effective_amount']), claim['activation_height']
            ))
        return accepted

    async def state(self, controlling=None, active=None, accepted=None):
        self.assertEqual(controlling, await self.get_controlling())
        self.assertEqual(active or [], await self.get_active())
        self.assertEqual(accepted or [], await self.get_accepted())

    async def test_example_from_spec(self):
        # https://spec.lbry.com/#claim-activation-example
        advance, state = self.advance, self.state
        stream, = await advance(113, [('claim', 'Claim A', '10.0')])
        await state(
            controlling=('Claim A', '10.0', '10.0', 113),
            active=[],
            accepted=[]
        )
        await advance(501, [('claim', 'Claim B', '20.0')])
        await state(
            controlling=('Claim A', '10.0', '10.0', 113),
            active=[],
            accepted=[('Claim B', '20.0', '0.0', 513)]
        )
        await advance(510, [('support', stream, '14')])
        await state(
            controlling=('Claim A', '10.0', '24.0', 113),
            active=[],
            accepted=[('Claim B', '20.0', '0.0', 513)]
        )
        await advance(512, [('claim', 'Claim C', '50.0')])
        await state(
            controlling=('Claim A', '10.0', '24.0', 113),
            active=[],
            accepted=[
                ('Claim B', '20.0', '0.0', 513),
                ('Claim C', '50.0', '0.0', 524)]
        )
        await advance(513, [])
        await state(
            controlling=('Claim A', '10.0', '24.0', 113),
            active=[('Claim B', '20.0', '20.0', 513)],
            accepted=[('Claim C', '50.0', '0.0', 524)]
        )
        await advance(520, [('claim', 'Claim D', '60.0')])
        await state(
            controlling=('Claim A', '10.0', '24.0', 113),
            active=[('Claim B', '20.0', '20.0', 513)],
            accepted=[
                ('Claim C', '50.0', '0.0', 524),
                ('Claim D', '60.0', '0.0', 532)]
        )
        await advance(524, [])
        await state(
            controlling=('Claim D', '60.0', '60.0', 524),
            active=[
                ('Claim A', '10.0', '24.0', 113),
                ('Claim B', '20.0', '20.0', 513),
                ('Claim C', '50.0', '50.0', 524)],
            accepted=[]
        )
        # beyond example
        await advance(525, [('update', stream, '70.0')])
        await state(
            controlling=('Claim A', '70.0', '84.0', 525),
            active=[
                ('Claim B', '20.0', '20.0', 513),
                ('Claim C', '50.0', '50.0', 524),
                ('Claim D', '60.0', '60.0', 524),
            ],
            accepted=[]
        )

    async def test_competing_claims_subsequent_blocks_height_wins(self):
        advance, state = self.advance, self.state
        await advance(113, [('claim', 'Claim A', '1.0')])
        await state(
            controlling=('Claim A', '1.0', '1.0', 113),
            active=[],
            accepted=[]
        )
        await advance(114, [('claim', 'Claim B', '1.0')])
        await state(
            controlling=('Claim A', '1.0', '1.0', 113),
            active=[('Claim B', '1.0', '1.0', 114)],
            accepted=[]
        )
        await advance(115, [('claim', 'Claim C', '1.0')])
        await state(
            controlling=('Claim A', '1.0', '1.0', 113),
            active=[
                ('Claim B', '1.0', '1.0', 114),
                ('Claim C', '1.0', '1.0', 115)],
            accepted=[]
        )

    async def test_competing_claims_in_single_block_position_wins(self):
        claim_a, claim_b = await self.advance(113, [
            ('claim', 'Claim A', '1.0'),
            ('claim', 'Claim B', '1.0')
        ])
        block = await self.get_last_block()
        # order of tx in block is non-deterministic,
        # figure out what ordered we ended up with
        if block['tx'][1] == claim_a.id:
            winner, other = 'Claim A', 'Claim B'
        else:
            winner, other = 'Claim B', 'Claim A'
        await self.state(
            controlling=(winner, '1.0', '1.0', 113),
            active=[(other, '1.0', '1.0', 113)],
            accepted=[]
        )

    async def test_competing_claims_in_single_block_effective_amount_wins(self):
        await self.advance(113, [
            ('claim', 'Claim A', '1.0'),
            ('claim', 'Claim B', '2.0')
        ])
        await self.state(
            controlling=('Claim B', '2.0', '2.0', 113),
            active=[('Claim A', '1.0', '1.0', 113)],
            accepted=[]
        )

    async def test_winning_claim_deleted(self):
        claim1, claim2 = await self.advance(113, [
            ('claim', 'Claim A', '1.0'),
            ('claim', 'Claim B', '2.0')
        ])
        await self.state(
            controlling=('Claim B', '2.0', '2.0', 113),
            active=[('Claim A', '1.0', '1.0', 113)],
            accepted=[]
        )
        await self.advance(114, [('abandon', claim2)])
        await self.state(
            controlling=('Claim A', '1.0', '1.0', 113),
            active=[],
            accepted=[]
        )

    async def test_winning_claim_deleted_and_new_claim_becomes_winner(self):
        claim1, claim2 = await self.advance(113, [
            ('claim', 'Claim A', '1.0'),
            ('claim', 'Claim B', '2.0')
        ])
        await self.state(
            controlling=('Claim B', '2.0', '2.0', 113),
            active=[('Claim A', '1.0', '1.0', 113)],
            accepted=[]
        )
        await self.advance(115, [
            ('abandon', claim2),
            ('claim', 'Claim C', '3.0')
        ])
        await self.state(
            controlling=('Claim C', '3.0', '3.0', 115),
            active=[('Claim A', '1.0', '1.0', 113)],
            accepted=[]
        )

    async def test_winning_claim_expires_and_another_takes_over(self):
        await self.advance(110, [('claim', 'Claim A', '2.0')])
        await self.advance(120, [('claim', 'Claim B', '1.0')])
        await self.state(
            controlling=('Claim A', '2.0', '2.0', 110),
            active=[('Claim B', '1.0', '1.0', 120)],
            accepted=[]
        )
        await self.advance(610, [])
        await self.state(
            controlling=('Claim B', '1.0', '1.0', 120),
            active=[],
            accepted=[]
        )
        await self.advance(620, [])
        await self.state(
            controlling=None,
            active=[],
            accepted=[]
        )

    async def test_create_and_multiple_updates_in_same_block(self):
        await self.chain.generate(10)
        txid = await self.claim_name('Claim A', '1.0')
        txid = await self.claim_update(await self.get_transaction(txid), '2.0')
        await self.claim_update(await self.get_transaction(txid), '3.0')
        await self.chain.generate(1)
        await self.sync.advance()
        self.current_height += 11
        await self.state(
            controlling=('Claim A', '3.0', '3.0', 112),
            active=[],
            accepted=[]
        )

    async def test_create_and_abandon_in_same_block(self):
        await self.chain.generate(10)
        txid = await self.claim_name('Claim A', '1.0')
        await self.claim_abandon(await self.get_transaction(txid))
        await self.chain.generate(1)
        await self.sync.advance()
        self.current_height += 11
        await self.state(
            controlling=None,
            active=[],
            accepted=[]
        )
