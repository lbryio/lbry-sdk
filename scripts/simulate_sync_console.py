import asyncio
import argparse
from typing import List
from binascii import unhexlify
from google.protobuf.message import DecodeError

from lbry import Config, Ledger, FullNode
from lbry.console import Advanced, Basic
from lbry.schema.claim import Claim
from lbry.testcase import EventGenerator
from lbry.blockchain.sync import BlockchainSync


def cause_protobuf_stderr():
    try:
        Claim.from_bytes(unhexlify(
            '005a3c63779597cba4c0e6ee45c3074fc389bd564ccc5d4a90eb4baacb0b028f2f4930'
            '0db003d6a27f0cac8be8b45fdda597303208b81845534e4543494c07123e0a420a'
        ))
    except DecodeError:
        pass


class Simulator:

    def __init__(self, console):
        self.console = console
        self.sync = console.service.sync
        self.progress = self.sync._on_progress_controller
        self.workers = console.service.db.workers

    @staticmethod
    def block_file_events(start, end, files, txs):
        return [
            (0, 191, 280, ((100, 0), (191, 280))),
            (1, 89, 178, ((89, 178),)),
            (2, 73, 86, ((73, 86),)),
            (3, 73, 86, ((73, 86),)),
            (4, 73, 86, ((73, 86),)),
            (5, 73, 86, ((73, 86),)),
        ]

    def claim_events(self, initial_sync: bool, start: int, end: int, total: int):
        if initial_sync:
            blocks = (end - start) + 1
            blocks_step = int(blocks/self.workers)
            done = claims_step = int(total/self.workers)
            for i in range(0, blocks, blocks_step):
                yield i, min(i+blocks_step, blocks), min(done, total), BlockchainSync.CLAIM_FLUSH_SIZE
                done += claims_step
        else:
            yield start, end, total, BlockchainSync.CLAIM_FLUSH_SIZE

    def support_events(self, initial_sync: bool, start: int, end: int, total: int):
        if initial_sync:
            blocks = (end - start) + 1
            blocks_step = int(blocks/self.workers)
            done = support_step = int(total/self.workers)
            for i in range(0, blocks, blocks_step):
                yield i, min(i+blocks_step, blocks), min(done, total), BlockchainSync.SUPPORT_FLUSH_SIZE
                done += support_step
        else:
            yield start, end, total, BlockchainSync.SUPPORT_FLUSH_SIZE

    async def advance(self, initial_sync: bool, start: int, end: int, files: List[int], txs: int):
        txs = txs
        claims = int(txs/4)
        supports = int(txs/2)
        eg = EventGenerator(
            initial_sync=initial_sync,
            start=start, end=end,
            block_files=list(self.block_file_events(start, end, files, txs)),
            claims=list(self.claim_events(initial_sync, start, end, claims)),
            supports=list(self.support_events(initial_sync, start, end, supports)),
        )
        for event in eg.events:
            await self.progress.add(event)
            await asyncio.sleep(0.5)


async def main(console):
    sim = Simulator(console)
    await sim.advance(True, 0, 10_000, [1, 2, 3, 4, 5], 10_000)
    await sim.advance(False, 10_001, 10_101, [5], 5000)
    await sim.advance(False, 10_102, 10_102, [5], 200)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--basic", default=False, action="store_true")
    parser.add_argument("--workers", default=5)
    args = parser.parse_args()

    node = FullNode(Ledger(Config(
        workers=args.workers,
        spv_address_filters=False
    )))
    console_instance = Basic(node) if args.basic else Advanced(node)

    try:
        console_instance.starting()
        asyncio.run(main(console_instance))
    except KeyboardInterrupt:
        pass
    finally:
        console_instance.stopping()
