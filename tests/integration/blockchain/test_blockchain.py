import os
import time
import asyncio
import logging
from binascii import unhexlify, hexlify
from random import choice

from lbry.testcase import AsyncioTestCase
from lbry.crypto.base58 import Base58
from lbry.blockchain import Lbrycrd, BlockchainSync
from lbry.db import Database
from lbry.blockchain.block import Block
from lbry.schema.claim import Stream
from lbry.wallet.transaction import Transaction, Output
from lbry.wallet.constants import CENT
from lbry.wallet.bcd_data_stream import BCDataStream

#logging.getLogger('lbry.blockchain').setLevel(logging.DEBUG)
log = logging.getLogger(__name__)


class TestBlockchain(AsyncioTestCase):

    async def asyncSetUp(self):
        await super().asyncSetUp()
        #self.chain = Lbrycrd.temp_regtest()
        self.chain = Lbrycrd('/tmp/tmp0429f0ku/', True)#.temp_regtest()
        await self.chain.ensure()
        await self.chain.start('-maxblockfilesize=8', '-rpcworkqueue=128')
        self.addCleanup(self.chain.stop, False)

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
        self.assertEqual([0, 1, 2, 3, 4, 7, 8, 9], msgs)

    async def test_sync(self):
        if False:
            names = ['one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']
            await self.chain.generate(101)
            address = Base58.decode(await self.chain.get_new_address())
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

        self.assertEqual(
            [(0, 191, 280), (1, 89, 178), (2, 12, 24)],
            [(file['file_number'], file['blocks'], file['txs'])
             for file in await self.chain.get_block_files()]
        )
        self.assertEqual(191, len(await self.chain.get_file_details(0)))

        db = Database(os.path.join(self.chain.actual_data_dir, 'lbry.db'))
        self.addCleanup(db.close)
        await db.open()

        sync = BlockchainSync(self.chain, use_process_pool=False)
        await sync.load_blocks()
