import os
import time
import asyncio
import tempfile
from binascii import hexlify, unhexlify
from distutils.dir_util import copy_tree, remove_tree

from lbry import Config, Database, RegTestLedger, Transaction, Output
from lbry.crypto.base58 import Base58
from lbry.schema.claim import Stream, Channel
from lbry.schema.support import Support
from lbry.blockchain.lbrycrd import Lbrycrd
from lbry.blockchain.sync import BlockchainSync
from lbry.blockchain.dewies import dewies_to_lbc
from lbry.constants import CENT
from lbry.testcase import AsyncioTestCase

import logging
#logging.getLogger('lbry.blockchain').setLevel(logging.DEBUG)


class BasicBlockchainTestCase(AsyncioTestCase):

    LBRYCRD_ARGS = '-rpcworkqueue=128',

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.chain = self.make_chain()
        await self.chain.ensure()
        self.addCleanup(self.chain.stop)
        await self.chain.start(*self.LBRYCRD_ARGS)

    @staticmethod
    def make_chain():
        return Lbrycrd.temp_regtest()

    async def make_db(self, chain):
        db = Database.temp_sqlite_regtest(chain.ledger.conf.lbrycrd_dir)
        self.addCleanup(remove_tree, db.ledger.conf.data_dir)
        await db.open()
        self.addCleanup(db.close)
        return db


class SyncingBlockchainTestCase(BasicBlockchainTestCase):

    async def asyncSetUp(self):
        await super().asyncSetUp()

        self.current_height = 0
        await self.generate(101, wait=False)

        self.db = await self.make_db(self.chain)
        self.chain.ledger.conf.spv_address_filters = False
        self.sync = BlockchainSync(self.chain, self.db)
        await self.sync.start()
        self.addCleanup(self.sync.stop)

        self.last_block_hash = None
        self.address = await self.chain.get_new_address()

        self.channel_keys = {}

    async def generate(self, blocks, wait=True):
        block_hashes = await self.chain.generate(blocks)
        self.current_height += blocks
        self.last_block_hash = block_hashes[-1]
        if wait:
            await self.sync.on_block.where(lambda b: self.current_height == b.height)
        return block_hashes

    async def get_transaction(self, txid: str) -> Transaction:
        raw = await self.chain.get_raw_transaction(txid)
        tx = Transaction(unhexlify(raw))
        txo = self.find_claim_txo(tx)
        if txo and txo.is_claim and txo.claim.is_channel:
            txo.private_key = self.channel_keys.get(txo.claim_hash)
        return tx

    async def get_last_block(self):
        return await self.chain.get_block(self.last_block_hash)

    def find_claim_txo(self, tx):
        for txo in tx.outputs:
            if txo.is_claim or txo.is_support:
                return txo

    async def create_claim(self, title='', amount=CENT, name='foo', claim_id_startswith='', sign=None, is_channel=False):
        if not claim_id_startswith and sign is None and not is_channel:
            claim = Stream().update(title=title).claim
            return await self.chain.claim_name(
                name, hexlify(claim.to_bytes()).decode(), amount
            )
        meta_class = Channel if is_channel else Stream
        tx = Transaction().add_outputs([
            Output.pay_claim_name_pubkey_hash(
                CENT, name, meta_class().update(title='claim #001').claim,
                Base58.decode(self.address)
            )
        ])
        private_key = None
        if is_channel:
            private_key = await self.find_claim_txo(tx).generate_channel_private_key()
        funded = await self.chain.fund_raw_transaction(hexlify(tx.raw).decode())
        tx = Transaction(unhexlify(funded['hex']))
        i = 1
        if '!' in claim_id_startswith:
            claim_id_startswith, not_after_startswith = claim_id_startswith.split('!')
            not_after_startswith = tuple(not_after_startswith)
        else:
            claim_id_startswith, not_after_startswith = claim_id_startswith, ()
        while True:
            if sign:
                self.find_claim_txo(tx).sign(sign)
            tx._reset()
            signed = await self.chain.sign_raw_transaction_with_wallet(hexlify(tx.raw).decode())
            tx = Transaction(unhexlify(signed['hex']))
            txo = self.find_claim_txo(tx)
            claim = txo.claim.channel if is_channel else txo.claim.stream
            if txo.claim_id.startswith(claim_id_startswith):
                if txo.claim_id[len(claim_id_startswith)] not in not_after_startswith:
                    break
            i += 1
            claim.update(title=f'claim #{i:03}')
            txo.script.generate()
        if private_key:
            self.channel_keys[self.find_claim_txo(tx).claim_hash] = private_key
        return await self.chain.send_raw_transaction(hexlify(tx.raw).decode())

    async def update_claim(self, txo, amount):
        return await self.chain.update_claim(
            txo.tx_ref.id, hexlify(txo.claim.to_bytes()).decode(), amount
        )

    async def abandon_claim(self, txid):
        return await self.chain.abandon_claim(txid, self.address)

    async def support_claim(self, txo, amount):
        response = await self.chain.support_claim(
            txo.claim_name, txo.claim_id, amount
        )
        return response['txId']

    async def get_takeovers(self):
        takeovers = []
        for takeover in await self.chain.db.get_takeover():
            takeovers.append({
                'name': takeover['name'],
                'height': takeover['height'],
                'claim_id': hexlify(takeover['claimID'][::-1]).decode()
            })
        return takeovers

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
                txid = await self.create_claim(value, amount)
            elif op_type == 'update':
                txid = await self.update_claim(value, amount)
            elif op_type == 'abandon':
                txid = await self.abandon_claim(value)
            elif op_type == 'support':
                txid = await self.support_claim(value, amount)
            else:
                raise ValueError(f'"{op_type}" is unknown operation')
            txs.append(await self.get_transaction(txid))
        await self.generate(1)
        return [self.find_claim_txo(tx) for tx in txs]

    async def get_controlling(self):
        for txo in await self.db.search_claims(is_controlling=True):
            return (
                txo.claim.stream.title, dewies_to_lbc(txo.amount),
                dewies_to_lbc(txo.meta['effective_amount']), txo.meta['takeover_height']
            )

    async def get_active(self):
        controlling = await self.get_controlling()
        active = []
        for txo in await self.db.search_claims(
                activation_height__lte=self.current_height,
                expiration_height__gt=self.current_height):
            if controlling and controlling[0] == txo.claim.stream.title:
                continue
            active.append((
                txo.claim.stream.title, dewies_to_lbc(txo.amount),
                dewies_to_lbc(txo.meta['effective_amount']), txo.meta['activation_height']
            ))
        return active

    async def get_accepted(self):
        accepted = []
        for txo in await self.db.search_claims(
                activation_height__gt=self.current_height,
                expiration_height__gt=self.current_height):
            accepted.append((
                txo.claim.stream.title, dewies_to_lbc(txo.amount),
                dewies_to_lbc(txo.meta['effective_amount']), txo.meta['activation_height']
            ))
        return accepted

    async def state(self, controlling=None, active=None, accepted=None):
        self.assertEqual(controlling, await self.get_controlling())
        self.assertEqual(active or [], await self.get_active())
        self.assertEqual(accepted or [], await self.get_accepted())


class TestBlockchainEvents(BasicBlockchainTestCase):

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
        self.assertEqual([
            0, 1, 2, 3, 4,
            # 5, 6 "missed"
            7, 8, 9
        ], msgs)


class TestMultiBlockFileSyncing(BasicBlockchainTestCase):

    TEST_DATA_CACHE_DIR = os.path.join(tempfile.gettempdir(), 'tmp-lbry-sync-test-data')
    LBRYCRD_ARGS = '-maxblockfilesize=8', '-rpcworkqueue=128'

    def make_chain(self):
        if os.path.exists(self.TEST_DATA_CACHE_DIR):
            temp_dir = tempfile.mkdtemp()
            copy_tree(self.TEST_DATA_CACHE_DIR, temp_dir)
            return Lbrycrd(RegTestLedger(Config.with_same_dir(temp_dir)))
        else:
            return Lbrycrd.temp_regtest()

    async def asyncSetUp(self):
        await super().asyncSetUp()
        generate = not os.path.exists(self.TEST_DATA_CACHE_DIR)

        self.db = await self.make_db(self.chain)
        self.chain.ledger.conf.spv_address_filters = False
        self.sync = BlockchainSync(self.chain, self.db)

        if not generate:
            return

        print(f'generating sample claims... ', end='', flush=True)

        await self.chain.generate(101)

        address = Base58.decode(self.chain.get_new_address())

        start = time.perf_counter()
        for _ in range(190):
            tx = Transaction().add_outputs([
                Output.pay_claim_name_pubkey_hash(
                    CENT, ["one", "two"][i % 2],
                    Stream().update(
                        title='a claim title',
                        description='Lorem ipsum '*400,
                        tag=['crypto', 'health', 'space'],
                    ).claim,
                    address)
                for i in range(1, 20)
            ])
            funded = await self.chain.fund_raw_transaction(hexlify(tx.raw).decode())
            signed = await self.chain.sign_raw_transaction_with_wallet(funded['hex'])
            await self.chain.send_raw_transaction(signed['hex'])
            await self.chain.generate(1)

        claim = tx.outputs[0]
        tx = Transaction().add_outputs([
            Output.pay_support_pubkey_hash(CENT, claim.claim_name, claim.claim_id, address),
            Output.pay_support_data_pubkey_hash(
                CENT, claim.claim_name, claim.claim_id, Support('🚀'), address
            ),
        ])
        funded = await self.chain.fund_raw_transaction(hexlify(tx.raw).decode())
        signed = await self.chain.sign_raw_transaction_with_wallet(funded['hex'])
        await self.chain.send_raw_transaction(signed['hex'])
        await self.chain.generate(1)

        print(f'took {time.perf_counter()-start}s to generate {190*19} claims ', flush=True)

        await self.chain.stop(False)
        copy_tree(self.chain.ledger.conf.lbrycrd_dir, self.TEST_DATA_CACHE_DIR)
        await self.chain.start(*self.LBRYCRD_ARGS)

    @staticmethod
    def extract_events(name, events):
        return sorted([
            [p['data'].get('block_file'), p['data']['step'], p['data']['total']]
            for p in events if p['event'].endswith(name)
        ])

    def assertEventsAlmostEqual(self, actual, expected):
        # this is needed because the sample tx data created
        # by lbrycrd does not have deterministic number of TXIs,
        # which throws off the progress reporting steps.
        # adjust the 'actual' to match 'expected' if it's only off by 1:
        for e, a in zip(expected, actual):
            if a[1] != e[1] and abs(a[1]-e[1]) <= 1:
                a[1] = e[1]
        self.assertEqual(expected, actual)

    async def test_lbrycrd_database_queries(self):
        db = self.chain.db

        # get_best_height
        self.assertEqual(292, await db.get_best_height())

        # get_block_files
        self.assertEqual(
            [(0, 191, 280), (1, 89, 178), (2, 13, 26)],
            [(file['file_number'], file['blocks'], file['txs'])
             for file in await db.get_block_files()]
        )
        self.assertEqual(
            [(1, 29, 58)],
            [(file['file_number'], file['blocks'], file['txs'])
             for file in await db.get_block_files(1, 250)]
        )

        # get_blocks_in_file
        self.assertEqual(279, (await db.get_blocks_in_file(1))[88]['height'])
        self.assertEqual(279, (await db.get_blocks_in_file(1, 250))[28]['height'])

        # get_takeover_count
        self.assertEqual(0, await db.get_takeover_count(0, 101))
        self.assertEqual(2, await db.get_takeover_count(101, 102))
        self.assertEqual(1, await db.get_takeover_count(102, 250))
        self.assertEqual(0, await db.get_takeover_count(250, 291))

        # get_takeovers
        self.assertEqual(
            [
                {'height': 102, 'name': b'one'},
                {'height': 102, 'name': b'two'},
                {'height': 250, 'name': b''}  # normalization on regtest kicks-in
            ],
            [{'name': takeover['normalized'], 'height': takeover['height']}
             for takeover in await db.get_takeovers(0, 291)]
        )

        # get_claim_metadata_count
        self.assertEqual(3610, await db.get_claim_metadata_count(0, 500))
        self.assertEqual(0, await db.get_claim_metadata_count(500, 1000))

        # get_claim_metadata
        self.assertEqual(
            [
                {'name': b'two', 'activation_height': 102, 'takeover_height': 102, 'is_controlling': True},
                {'name': b'one', 'activation_height': 102, 'takeover_height': 102, 'is_controlling': True},
                {'name': b'two', 'activation_height': 102, 'takeover_height': None, 'is_controlling': False},
                {'name': b'one', 'activation_height': 102, 'takeover_height': None, 'is_controlling': False},
            ],
            [{
                'name': c['name'], 'is_controlling': bool(c['is_controlling']),
                'activation_height': c['activation_height'], 'takeover_height': c['takeover_height'],
            } for c in (await db.get_claim_metadata(0, 103))[:4]]
        )

        # get_support_metadata_count
        self.assertEqual(1, await db.get_support_metadata_count(0, 500))
        self.assertEqual(0, await db.get_support_metadata_count(500, 1000))

        def foo(c):
            return

        # get_support_metadata
        self.assertEqual(
            [{'name': b'two', 'activation_height': 297, 'expiration_height': 792}],
            [{'name': c['name'], 'activation_height': c['activation_height'], 'expiration_height': c['expiration_height']}
             for c in await db.get_support_metadata(0, 500)]
        )

    async def test_multi_block_file_sync(self):
        events = []
        self.sync.on_progress.listen(events.append)

        await self.sync.advance()
        await asyncio.sleep(1)  # give it time to collect events
        self.assertEqual(
            events[0], {
                "event": "blockchain.sync.start",
                "data": {
                    "starting_height": -1,
                    "ending_height": 292,
                    "files": 3,
                    "blocks": 293,
                    "txs": 484
                }
            }
        )
        self.assertEqual(
            self.extract_events('block.read', events), [
                [0, 0, 191],
                [0, 100, 191],
                [0, 191, 191],
                [1, 0, 89],
                [1, 89, 89],
                [2, 0, 13],
                [2, 13, 13],
            ]
        )
        self.assertEventsAlmostEqual(
            self.extract_events('block.save', events), [
                [0, 0, 280],
                [0, 19, 280],
                [0, 47, 280],
                [0, 267, 280],
                [0, 278, 280],
                [0, 280, 280],
                [1, 0, 178],
                [1, 6, 178],
                [1, 19, 178],
                [1, 166, 178],
                [1, 175, 178],
                [1, 178, 178],
                [2, 0, 26],
                [2, 1, 26],
                [2, 3, 26],
                [2, 24, 26],
                [2, 26, 26],
                [2, 26, 26]
            ]
        )
        claim_events = self.extract_events('claim.insert', events)
        self.assertEqual([3402, 3610], claim_events[2][1:])
        self.assertEqual([3610, 3610], claim_events[-1][1:])

        events.clear()
        await self.sync.advance()  # should be no-op
        await asyncio.sleep(1)  # give it time to collect events
        self.assertListEqual([], events)

        await self.chain.generate(1)

        events.clear()

        await self.sync.advance()
        await asyncio.sleep(1)  # give it time to collect events
        self.assertEqual(
            events[0], {
                "event": "blockchain.sync.start",
                "data": {
                    "starting_height": 292,
                    "ending_height": 293,
                    "files": 1,
                    "blocks": 1,
                    "txs": 1
                }
            }
        )
        self.assertEqual(
            self.extract_events('block.read', events), [
                [2, 0, 1],
                [2, 1, 1],
            ]
        )
        self.assertEqual(
            self.extract_events('block.save', events), [
                [2, 0, 1],
                [2, 1, 1],
            ]
        )


class TestBasicBlockchainSync(SyncingBlockchainTestCase):

    async def test_sync_advances(self):
        blocks = []
        self.sync.on_block.listen(blocks.append)
        await self.generate(1)
        await self.generate(1)
        await self.generate(1)
        self.assertEqual([102, 103, 104], [b.height for b in blocks])
        self.assertEqual(104, self.current_height)
        blocks.clear()
        await self.generate(6)
        self.assertEqual([110], [b.height for b in blocks])
        self.assertEqual(110, self.current_height)

    async def test_claim_create_update_and_delete(self):
        await self.create_claim('foo', '0.01')
        await self.generate(1)
        claims = await self.db.search_claims()
        self.assertEqual(1, len(claims))
        self.assertEqual(claims[0].claim_name, 'foo')
        self.assertEqual(dewies_to_lbc(claims[0].amount), '0.01')
        await self.support_claim(claims[0], '0.08')
        await self.update_claim(claims[0], '0.02')
        await self.generate(1)
        claims = await self.db.search_claims()
        self.assertEqual(1, len(claims))
        self.assertEqual(claims[0].claim_name, 'foo')
        self.assertEqual(dewies_to_lbc(claims[0].amount), '0.02')
        self.assertEqual(dewies_to_lbc(claims[0].meta['effective_amount']), '0.1')
        await self.abandon_claim(claims[0].tx_ref.id)
        await self.generate(1)
        claims = await self.db.search_claims()
        self.assertEqual(0, len(claims))


class TestClaimtrieSync(SyncingBlockchainTestCase):

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
        await advance(510, [('support', stream, '14.0')])
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
        if block['tx'][1] == claim_a.tx_ref.id:
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

    async def winning_claim_deleted_test(self):
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
            ('abandon', claim2.tx_ref.id),
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
            controlling=('Claim B', '1.0', '1.0', 610),
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
        await self.generate(10)
        txid = await self.create_claim('Claim A', '1.0')
        txid = await self.update_claim(self.find_claim_txo(await self.get_transaction(txid)), '2.0')
        await self.update_claim(self.find_claim_txo(await self.get_transaction(txid)), '3.0')
        await self.generate(1)
        await self.sync.advance()
        await self.state(
            controlling=('Claim A', '3.0', '3.0', 112),
            active=[],
            accepted=[]
        )

    async def test_create_and_abandon_in_same_block(self):
        await self.generate(10)
        txid = await self.create_claim('Claim A', '1.0')
        await self.abandon_claim(txid)
        await self.generate(1)
        await self.sync.advance()
        await self.state(
            controlling=None,
            active=[],
            accepted=[]
        )


class TestResolve(SyncingBlockchainTestCase):

    async def create_claim_txo(self, title='', amount=CENT, name=None, claim_id_startswith=None, sign=None, is_channel=False):
        tx = await self.get_transaction(await self.create_claim(
            title=title, amount=amount, name=name or ('@foo' if is_channel else 'foo'),
            claim_id_startswith=claim_id_startswith, sign=sign, is_channel=is_channel
        ))
        return self.find_claim_txo(tx)

    async def test_canonical_url_and_channel_validation(self):
        advance, search = self.advance, self.db.search_claims

        txo_chan_a = await self.create_claim_txo(claim_id_startswith='a!b', is_channel=True)
        await self.generate(1)
        txo_chan_ab = await self.create_claim_txo(claim_id_startswith='ab', is_channel=True)
        await self.generate(1)
        (r_ab, r_a) = await search(order_by=['creation_height'], limit=2)
        self.assertEqual("@foo#a", r_a.meta['short_url'])
        self.assertEqual("@foo#ab", r_ab.meta['short_url'])
        self.assertIsNone(r_a.meta['canonical_url'])
        self.assertIsNone(r_ab.meta['canonical_url'])
        self.assertEqual(0, r_a.meta['claims_in_channel_count'])
        self.assertEqual(0, r_ab.meta['claims_in_channel_count'])

        await self.create_claim_txo(claim_id_startswith='a!b')
        await self.generate(1)
        await self.create_claim_txo(claim_id_startswith='ab!c')
        await self.generate(1)
        await self.create_claim_txo(claim_id_startswith='abc')
        await self.generate(1)
        (r_abc, r_ab, r_a) = await search(order_by=['creation_height'], limit=3)
        self.assertEqual("foo#a", r_a.meta['short_url'])
        self.assertEqual("foo#ab", r_ab.meta['short_url'])
        self.assertEqual("foo#abc", r_abc.meta['short_url'])
        self.assertIsNone(r_a.meta['canonical_url'])
        self.assertIsNone(r_ab.meta['canonical_url'])
        self.assertIsNone(r_abc.meta['canonical_url'])

        a2_claim = await self.create_claim_txo(claim_id_startswith='a!b'+r_a.claim_id[1], sign=txo_chan_a)
        await self.generate(1)
        ab2_claim = await self.create_claim_txo(claim_id_startswith='ab!c'+r_ab.claim_id[2], sign=txo_chan_a)
        await self.generate(1)
        r_ab2, r_a2 = await search(order_by=['creation_height'], limit=2)
        r_a2url, r_ab2url = f"foo#{a2_claim.claim_id[:2]}", f"foo#{ab2_claim.claim_id[:3]}"
        self.assertEqual(r_a2url, r_a2.meta['short_url'])
        self.assertEqual(r_ab2url, r_ab2.meta['short_url'])
        self.assertEqual(f"@foo#a/{r_a2url}", r_a2.meta['canonical_url'])
        self.assertEqual(f"@foo#a/{r_ab2url}", r_ab2.meta['canonical_url'])
        self.assertEqual(2, (await search(claim_id=txo_chan_a.claim_id, limit=1))[0].meta['claims_in_channel_count'])

        # change channel public key, invaliding stream claim signatures
        await advance(8, [self.get_channel_update(txo_chan_a, COIN, key=b'a')])
        (r_ab2, r_a2) = search(order_by=['creation_height'], limit=2)
        self.assertEqual(f"foo#{a2_claim.claim_id[:2]}", r_a2['short_url'])
        self.assertEqual(f"foo#{ab2_claim.claim_id[:4]}", r_ab2['short_url'])
        self.assertIsNone(r_a2['canonical_url'])
        self.assertIsNone(r_ab2['canonical_url'])
        self.assertEqual(0, search(claim_id=txo_chan_a.claim_id, limit=1)[0]['claims_in_channel'])

        # reinstate previous channel public key (previous stream claim signatures become valid again)
        channel_update = self.get_channel_update(txo_chan_a, COIN, key=b'c')
        await advance(9, [channel_update])
        (r_ab2, r_a2) = search(order_by=['creation_height'], limit=2)
        self.assertEqual(f"foo#{a2_claim.claim_id[:2]}", r_a2['short_url'])
        self.assertEqual(f"foo#{ab2_claim.claim_id[:4]}", r_ab2['short_url'])
        self.assertEqual("@foo#a/foo#a", r_a2['canonical_url'])
        self.assertEqual("@foo#a/foo#ab", r_ab2['canonical_url'])
        self.assertEqual(2, search(claim_id=txo_chan_a.claim_id, limit=1)[0]['claims_in_channel'])
        self.assertEqual(0, search(claim_id=txo_chan_ab.claim_id, limit=1)[0]['claims_in_channel'])

        # change channel of stream
        self.assertEqual("@foo#a/foo#ab", search(claim_id=ab2_claim.claim_id, limit=1)[0]['canonical_url'])
        tx_ab2 = self.get_stream_update(tx_ab2, COIN, txo_chan_ab)
        await advance(10, [tx_ab2])
        self.assertEqual("@foo#ab/foo#a", search(claim_id=ab2_claim.claim_id, limit=1)[0]['canonical_url'])
        # TODO: currently there is a bug where stream leaving a channel does not update that channels claims count
        self.assertEqual(2, search(claim_id=txo_chan_a.claim_id, limit=1)[0]['claims_in_channel'])
        # TODO: after bug is fixed remove test above and add test below
        #self.assertEqual(1, search(claim_id=txo_chan_a.claim_id, limit=1)[0]['claims_in_channel'])
        self.assertEqual(1, search(claim_id=txo_chan_ab.claim_id, limit=1)[0]['claims_in_channel'])

        # claim abandon updates claims_in_channel
        await advance(11, [self.get_abandon(tx_ab2)])
        self.assertEqual(0, search(claim_id=txo_chan_ab.claim_id, limit=1)[0]['claims_in_channel'])

        # delete channel, invaliding stream claim signatures
        await advance(12, [self.get_abandon(channel_update)])
        (r_a2,) = search(order_by=['creation_height'], limit=1)
        self.assertEqual(f"foo#{a2_claim.claim_id[:2]}", r_a2['short_url'])
        self.assertIsNone(r_a2['canonical_url'])

    def test_resolve_issue_2448(self):
        advance = self.advance

        tx_chan_a = self.get_channel_with_claim_id_prefix('a', 1, key=b'c')
        tx_chan_ab = self.get_channel_with_claim_id_prefix('ab', 72, key=b'c')
        txo_chan_a = tx_chan_a[0].outputs[0]
        txo_chan_ab = tx_chan_ab[0].outputs[0]
        advance(1, [tx_chan_a])
        advance(2, [tx_chan_ab])

        self.assertEqual(reader.resolve_url("@foo#a")['claim_hash'], txo_chan_a.claim_hash)
        self.assertEqual(reader.resolve_url("@foo#ab")['claim_hash'], txo_chan_ab.claim_hash)

        # update increase last height change of channel
        advance(9, [self.get_channel_update(txo_chan_a, COIN, key=b'c')])

        # make sure that activation_height is used instead of height (issue #2448)
        self.assertEqual(reader.resolve_url("@foo#a")['claim_hash'], txo_chan_a.claim_hash)
        self.assertEqual(reader.resolve_url("@foo#ab")['claim_hash'], txo_chan_ab.claim_hash)

    def test_canonical_find_shortest_id(self):
        new_hash = 'abcdef0123456789beef'
        other0 = '1bcdef0123456789beef'
        other1 = 'ab1def0123456789beef'
        other2 = 'abc1ef0123456789beef'
        other3 = 'abcdef0123456789bee1'
        f = FindShortestID()
        f.step(other0, new_hash)
        self.assertEqual('#a', f.finalize())
        f.step(other1, new_hash)
        self.assertEqual('#abc', f.finalize())
        f.step(other2, new_hash)
        self.assertEqual('#abcd', f.finalize())
        f.step(other3, new_hash)
        self.assertEqual('#abcdef0123456789beef', f.finalize())


class TestTrending(SyncingBlockchainTestCase):

    def test_trending(self):
        advance = self.advance
        no_trend = self.get_stream('Claim A', COIN)
        downwards = self.get_stream('Claim B', COIN)
        up_small = self.get_stream('Claim C', COIN)
        up_medium = self.get_stream('Claim D', COIN)
        up_biggly = self.get_stream('Claim E', COIN)
        claims = advance(1, [up_biggly, up_medium, up_small, no_trend, downwards])
        for window in range(1, 8):
            advance(zscore.TRENDING_WINDOW * window, [
                self.get_support(downwards, (20-window)*COIN),
                self.get_support(up_small, int(20+(window/10)*COIN)),
                self.get_support(up_medium, (20+(window*(2 if window == 7 else 1)))*COIN),
                self.get_support(up_biggly, (20+(window*(3 if window == 7 else 1)))*COIN),
            ])
        results = search(order_by=['trending_local'])
        self.assertEqual([c.claim_id for c in claims], [hexlify(c['claim_hash'][::-1]).decode() for c in results])
        self.assertEqual([10, 6, 2, 0, -2], [int(c['trending_local']) for c in results])
        self.assertEqual([53, 38, -32, 0, -6], [int(c['trending_global']) for c in results])
        self.assertEqual([4, 4, 2, 0, 1], [int(c['trending_group']) for c in results])
        self.assertEqual([53, 38, 2, 0, -6], [int(c['trending_mixed']) for c in results])

    def test_edge(self):
        problematic = self.get_stream('Problem', COIN)
        self.advance(1, [problematic])
        self.advance(zscore.TRENDING_WINDOW, [self.get_support(problematic, 53000000000)])
        self.advance(zscore.TRENDING_WINDOW * 2, [self.get_support(problematic, 500000000)])


class TestContentBlocking(SyncingBlockchainTestCase):

    def test_blocking_and_filtering(self):
        # content claims and channels
        tx0 = self.get_channel('A Channel', COIN, '@channel1')
        regular_channel = tx0[0].outputs[0]
        tx1 = self.get_stream('Claim One', COIN, 'claim1')
        tx2 = self.get_stream('Claim Two', COIN, 'claim2', regular_channel)
        tx3 = self.get_stream('Claim Three', COIN, 'claim3')
        self.advance(1, [tx0, tx1, tx2, tx3])
        claim1, claim2, claim3 = tx1[0].outputs[0], tx2[0].outputs[0], tx3[0].outputs[0]

        # block and filter channels
        tx0 = self.get_channel('Blocking Channel', COIN, '@block')
        tx1 = self.get_channel('Filtering Channel', COIN, '@filter')
        blocking_channel = tx0[0].outputs[0]
        filtering_channel = tx1[0].outputs[0]
        self.sql.blocking_channel_hashes.add(blocking_channel.claim_hash)
        self.sql.filtering_channel_hashes.add(filtering_channel.claim_hash)
        self.advance(2, [tx0, tx1])
        self.assertEqual({}, dict(self.sql.blocked_streams))
        self.assertEqual({}, dict(self.sql.blocked_channels))
        self.assertEqual({}, dict(self.sql.filtered_streams))
        self.assertEqual({}, dict(self.sql.filtered_channels))

        # nothing blocked
        results, _ = reader.resolve([
            claim1.claim_name, claim2.claim_name,
            claim3.claim_name, regular_channel.claim_name
        ])
        self.assertEqual(claim1.claim_hash, results[0]['claim_hash'])
        self.assertEqual(claim2.claim_hash, results[1]['claim_hash'])
        self.assertEqual(claim3.claim_hash, results[2]['claim_hash'])
        self.assertEqual(regular_channel.claim_hash, results[3]['claim_hash'])

        # nothing filtered
        results, censor = censored_search()
        self.assertEqual(6, len(results))
        self.assertEqual(0, censor.total)
        self.assertEqual({}, censor.censored)

        # block claim reposted to blocking channel, also gets filtered
        repost_tx1 = self.get_repost(claim1.claim_id, COIN, blocking_channel)
        repost1 = repost_tx1[0].outputs[0]
        self.advance(3, [repost_tx1])
        self.assertEqual(
            {repost1.claim.repost.reference.claim_hash: blocking_channel.claim_hash},
            dict(self.sql.blocked_streams)
        )
        self.assertEqual({}, dict(self.sql.blocked_channels))
        self.assertEqual(
            {repost1.claim.repost.reference.claim_hash: blocking_channel.claim_hash},
            dict(self.sql.filtered_streams)
        )
        self.assertEqual({}, dict(self.sql.filtered_channels))

        # claim is blocked from results by direct repost
        results, censor = censored_search(text='Claim')
        self.assertEqual(2, len(results))
        self.assertEqual(claim2.claim_hash, results[0]['claim_hash'])
        self.assertEqual(claim3.claim_hash, results[1]['claim_hash'])
        self.assertEqual(1, censor.total)
        self.assertEqual({blocking_channel.claim_hash: 1}, censor.censored)
        results, _ = reader.resolve([claim1.claim_name])
        self.assertEqual(
            f"Resolve of 'claim1' was censored by channel with claim id '{blocking_channel.claim_id}'.",
            results[0].args[0]
        )
        results, _ = reader.resolve([
            claim2.claim_name, regular_channel.claim_name  # claim2 and channel still resolved
        ])
        self.assertEqual(claim2.claim_hash, results[0]['claim_hash'])
        self.assertEqual(regular_channel.claim_hash, results[1]['claim_hash'])

        # block claim indirectly by blocking its parent channel
        repost_tx2 = self.get_repost(regular_channel.claim_id, COIN, blocking_channel)
        repost2 = repost_tx2[0].outputs[0]
        self.advance(4, [repost_tx2])
        self.assertEqual(
            {repost1.claim.repost.reference.claim_hash: blocking_channel.claim_hash},
            dict(self.sql.blocked_streams)
        )
        self.assertEqual(
            {repost2.claim.repost.reference.claim_hash: blocking_channel.claim_hash},
            dict(self.sql.blocked_channels)
        )
        self.assertEqual(
            {repost1.claim.repost.reference.claim_hash: blocking_channel.claim_hash},
            dict(self.sql.filtered_streams)
        )
        self.assertEqual(
            {repost2.claim.repost.reference.claim_hash: blocking_channel.claim_hash},
            dict(self.sql.filtered_channels)
        )

        # claim in blocked channel is filtered from search and can't resolve
        results, censor = censored_search(text='Claim')
        self.assertEqual(1, len(results))
        self.assertEqual(claim3.claim_hash, results[0]['claim_hash'])
        self.assertEqual(2, censor.total)
        self.assertEqual({blocking_channel.claim_hash: 2}, censor.censored)
        results, _ = reader.resolve([
            claim2.claim_name, regular_channel.claim_name  # claim2 and channel don't resolve
        ])
        self.assertEqual(
            f"Resolve of 'claim2' was censored by channel with claim id '{blocking_channel.claim_id}'.",
            results[0].args[0]
        )
        self.assertEqual(
            f"Resolve of '@channel1' was censored by channel with claim id '{blocking_channel.claim_id}'.",
            results[1].args[0]
        )
        results, _ = reader.resolve([claim3.claim_name])  # claim3 still resolved
        self.assertEqual(claim3.claim_hash, results[0]['claim_hash'])

        # filtered claim is only filtered and not blocked
        repost_tx3 = self.get_repost(claim3.claim_id, COIN, filtering_channel)
        repost3 = repost_tx3[0].outputs[0]
        self.advance(5, [repost_tx3])
        self.assertEqual(
            {repost1.claim.repost.reference.claim_hash: blocking_channel.claim_hash},
            dict(self.sql.blocked_streams)
        )
        self.assertEqual(
            {repost2.claim.repost.reference.claim_hash: blocking_channel.claim_hash},
            dict(self.sql.blocked_channels)
        )
        self.assertEqual(
            {repost1.claim.repost.reference.claim_hash: blocking_channel.claim_hash,
             repost3.claim.repost.reference.claim_hash: filtering_channel.claim_hash},
            dict(self.sql.filtered_streams)
        )
        self.assertEqual(
            {repost2.claim.repost.reference.claim_hash: blocking_channel.claim_hash},
            dict(self.sql.filtered_channels)
        )

        # filtered claim doesn't return in search but is resolveable
        results, censor = censored_search(text='Claim')
        self.assertEqual(0, len(results))
        self.assertEqual(3, censor.total)
        self.assertEqual({blocking_channel.claim_hash: 2, filtering_channel.claim_hash: 1}, censor.censored)
        results, _ = reader.resolve([claim3.claim_name])  # claim3 still resolved
        self.assertEqual(claim3.claim_hash, results[0]['claim_hash'])

        # abandon unblocks content
        self.advance(6, [
            self.get_abandon(repost_tx1),
            self.get_abandon(repost_tx2),
            self.get_abandon(repost_tx3)
        ])
        self.assertEqual({}, dict(self.sql.blocked_streams))
        self.assertEqual({}, dict(self.sql.blocked_channels))
        self.assertEqual({}, dict(self.sql.filtered_streams))
        self.assertEqual({}, dict(self.sql.filtered_channels))
        results, censor = censored_search(text='Claim')
        self.assertEqual(3, len(results))
        self.assertEqual(0, censor.total)
        results, censor = censored_search()
        self.assertEqual(6, len(results))
        self.assertEqual(0, censor.total)
        results, _ = reader.resolve([
            claim1.claim_name, claim2.claim_name,
            claim3.claim_name, regular_channel.claim_name
        ])
        self.assertEqual(claim1.claim_hash, results[0]['claim_hash'])
        self.assertEqual(claim2.claim_hash, results[1]['claim_hash'])
        self.assertEqual(claim3.claim_hash, results[2]['claim_hash'])
        self.assertEqual(regular_channel.claim_hash, results[3]['claim_hash'])

    def test_pagination(self):
        one, two, three, four, five, six, seven, filter_channel = self.advance(1, [
            self.get_stream('One', COIN),
            self.get_stream('Two', COIN),
            self.get_stream('Three', COIN),
            self.get_stream('Four', COIN),
            self.get_stream('Five', COIN),
            self.get_stream('Six', COIN),
            self.get_stream('Seven', COIN),
            self.get_channel('Filtering Channel', COIN, '@filter'),
        ])
        self.sql.filtering_channel_hashes.add(filter_channel.claim_hash)

        # nothing filtered
        results, censor = censored_search(order_by='^height', offset=1, limit=3)
        self.assertEqual(3, len(results))
        self.assertEqual(
            [two.claim_hash, three.claim_hash, four.claim_hash],
            [r['claim_hash'] for r in results]
        )
        self.assertEqual(0, censor.total)

        # content filtered
        repost1, repost2 = self.advance(2, [
            self.get_repost(one.claim_id, COIN, filter_channel),
            self.get_repost(two.claim_id, COIN, filter_channel),
        ])
        results, censor = censored_search(order_by='^height', offset=1, limit=3)
        self.assertEqual(3, len(results))
        self.assertEqual(
            [four.claim_hash, five.claim_hash, six.claim_hash],
            [r['claim_hash'] for r in results]
        )
        self.assertEqual(2, censor.total)
        self.assertEqual({filter_channel.claim_hash: 2}, censor.censored)
