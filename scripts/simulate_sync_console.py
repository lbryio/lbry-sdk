import asyncio
from random import randrange
from lbry.blockchain import Ledger
from lbry.service import FullNode
from lbry.console import Advanced
from lbry.conf import Config


class Simulator:

    def __init__(self, progress, ending_height, files, txs, processes):
        self.progress = progress
        self.starting_height = 0
        self.ending_height = ending_height
        self.starting_file = 0
        self.ending_file = files
        self.txs = txs
        self.processes = processes

    @property
    def blocks(self):
        return self.ending_height-self.starting_height

    @property
    def files(self):
        return self.ending_file-self.starting_file

    async def advance(self):
        await self.progress.add({
            "event": "blockchain.sync.start",
            "data": {
                "starting_height": self.starting_height,
                "ending_height": self.ending_height,
                "files": self.files,
                "blocks": self.blocks,
                "txs": self.txs
            }
        })
        blocks_synced = txs_synced = 0
        for starting_file in range(self.starting_file, self.ending_file, self.processes):
            tasks = []
            for b in range(starting_file, min(self.ending_file, starting_file+self.processes)):
                if b == (self.ending_file-1):
                    tasks.append(self.sync_block_file(b, self.blocks-blocks_synced, self.txs-txs_synced))
                else:
                    blocks = int(self.blocks / self.files)
                    blocks_synced += blocks
                    txs = int(self.txs / self.files)
                    txs_synced += txs
                    tasks.append(self.sync_block_file(b, blocks, txs))
            await asyncio.wait(tasks)
        await self.progress.add({
            "event": "blockchain.sync.block.done",
            "data": {"step": 1, "total": 1, "unit": "tasks", "best_height_processed": self.ending_height}
        })
        await self.process()
        self.processes = 1
        self.txs = 25
        self.starting_height = self.ending_height
        self.ending_height += 1

    async def sync_block_file(self, block_file, blocks, txs):
        for i in range(0, blocks, 1000):
            await self.progress.add({
                "event": "blockchain.sync.block.read",
                "data": {"step": i, "total": blocks, "unit": "blocks", "block_file": block_file}
            })
            await asyncio.sleep(randrange(1, 10)/10)
        await self.progress.add({
            "event": "blockchain.sync.block.read",
            "data": {"step": blocks, "total": blocks, "unit": "blocks", "block_file": block_file}
        })
        await asyncio.sleep(0.5)
        for i in range(0, txs, 10000):
            await self.progress.add({
                "event": "blockchain.sync.block.save",
                "data": {"step": i, "total": txs, "unit": "txs", "block_file": block_file}
            })
            await asyncio.sleep(randrange(1, 10) / 10)
        await self.progress.add({
            "event": "blockchain.sync.block.save",
            "data": {"step": txs, "total": txs, "unit": "txs", "block_file": block_file}
        })

    async def process(self):
        for i in range(3):
            await self.progress.add({
                "event": "db.sync.input",
                "data": {"step": i, "total": 2, "unit": "txis"}
            })
            await asyncio.sleep(1)
        claims = int(self.txs/4)
        for i in range(0, claims+1, 10_000):
            await self.progress.add({
                "event": "blockchain.sync.claim.update",
                "data": {"step": i, "total": claims, "unit": "claims"}
            })
            await asyncio.sleep(0.1)


async def main():
    console = Advanced(FullNode(Ledger(Config(processes=4))))
    progress = console.service.sync._on_progress_controller
    sim = Simulator(progress, 200_000, 7, 1_000_000, console.service.db.processes)
    console.starting()
    await sim.advance()
    console.stopping()


if __name__ == "__main__":
    asyncio.run(main())
