import asyncio
from random import randrange
from typing import List
from lbry.blockchain import Ledger
from lbry.service import FullNode
from lbry.console import Advanced, Basic
from lbry.conf import Config
from lbry.db.utils import chunk


class Simulator:

    def __init__(self, console):
        self.console = console
        self.sync = console.service.sync
        self.progress = self.sync._on_progress_controller
        self.starting_height = 0
        self.ending_height = 0
        self.starting_file = 0
        self.processes = console.service.db.processes

        self.steps = []
        self.txs = 0
        self.claims = 0
        self.supports = 0

    @property
    def blocks(self, ):
        if self.starting_height == 0:
            return self.ending_height-self.starting_height
        return (self.ending_height-self.starting_height)+1

    async def advance(self, initial_sync: bool, ending_height: int, files: List[int], txs: int):
        self.ending_height = ending_height
        self.steps = self.sync.get_steps(initial_sync)
        self.txs = txs
        self.claims = int(txs/4)
        self.supports = int(txs/2)
        await self.progress.add({
            "event": "blockchain.sync.start",
            "data": {
                "starting_height": self.starting_height,
                "ending_height": ending_height,
                "files": len(files),
                "blocks": self.blocks,
                "sync_steps": self.steps,
                "txs": self.txs,
                "claims": self.claims,
                "supports": self.supports,
            }
        })
        blocks_synced = txs_synced = 0
        for file_group in chunk(files, self.processes):
            tasks = []
            for file in file_group:
                if file == files[-1]:
                    tasks.append(self.sync_block_file(file, self.blocks-blocks_synced, self.txs-txs_synced))
                else:
                    blocks = int(self.blocks / len(files))
                    blocks_synced += blocks
                    txs = int(self.txs / len(files))
                    txs_synced += txs
                    tasks.append(self.sync_block_file(file, blocks, txs))
            await asyncio.wait(tasks)
        for step in self.steps:
            if step in ("blockchain.sync.block.read", "blockchain.sync.block.save"):
                continue
            await getattr(self, step.replace('.', '_'))()
        await self.progress.add({
            "event": "blockchain.sync.complete",
            "data": {"step": len(self.steps), "total": len(self.steps), "unit": "tasks"}
        })
        self.ending_height = ending_height+1
        self.starting_height = self.ending_height

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
        for i in range(0, txs, 2000):
            await self.progress.add({
                "event": "blockchain.sync.block.save",
                "data": {"step": i, "total": txs, "unit": "txs", "block_file": block_file}
            })
            await asyncio.sleep(randrange(1, 10) / 10)
        await self.progress.add({
            "event": "blockchain.sync.block.save",
            "data": {"step": txs, "total": txs, "unit": "txs", "block_file": block_file}
        })

    async def generate_steps(self, event, steps, unit, delay=1.0, step=1):
        await self.progress.add({"event": event, "data": {"step": 0, "total": steps, "unit": unit}})
        remaining = steps
        for i in range(1, steps+1, step):
            await asyncio.sleep(delay)
            await self.progress.add({"event": event, "data": {"step": i, "total": steps, "unit": unit}})
            remaining -= i
        if remaining:
            await asyncio.sleep(delay)
            await self.progress.add({"event": event, "data": {"step": steps, "total": steps, "unit": unit}})

    async def db_sync_input(self):
        await self.generate_steps("db.sync.input", 2, "txis")

    async def db_sync_claim_delete(self):
        await self.generate_steps("db.sync.claim.delete", 1, "claims")

    async def db_sync_claim_insert(self):
        await self.generate_steps("db.sync.claim.insert", 1, "claims")

    async def db_sync_claim_update(self):
        await self.generate_steps("db.sync.claim.update", 0, "claims")

    async def db_sync_support_delete(self):
        await self.generate_steps("db.sync.support.delete", 1, "supports")

    async def db_sync_support_insert(self):
        await self.generate_steps("db.sync.support.insert", 1, "supports")

    async def blockchain_sync_claim_trie(self):
        await self.generate_steps("blockchain.sync.claim.trie", 1, "claims")

    async def blockchain_sync_claim_meta(self):
        for i in range(0, self.claims, 1_000):
            await self.progress.add({
                "event": "blockchain.sync.claim.meta",
                "data": {"step": i, "total": self.claims, "unit": "claims"}
            })
            await asyncio.sleep(0.1)
        await self.progress.add({
            "event": "blockchain.sync.claim.meta",
            "data": {"step": self.claims, "total": self.claims, "unit": "claims"}
        })

    async def blockchain_sync_claim_signatures(self):
        await self.generate_steps("blockchain.sync.claim.signatures", self.claims, "claims", 0.5, 1000)

    async def blockchain_sync_support_signatures(self):
        await self.generate_steps("blockchain.sync.support.signatures", self.supports, "supports", 0.5, 1000)

    async def blockchain_sync_claim_stakes(self):
        await self.generate_steps("blockchain.sync.claim.stakes", 1, "claims", 0.5)

    async def blockchain_sync_claim_channels(self):
        await self.generate_steps("blockchain.sync.claim.channels", 0, "supports", 0.5)


async def main():
    console = Advanced(FullNode(Ledger(Config(processes=3, spv_address_filters=False))))
    sim = Simulator(console)
    console.starting()
    await sim.advance(True, 100_000, [1, 2, 3, 4, 5], 100_000)
    await sim.advance(False, 100_001, [5], 100)
    console.stopping()


if __name__ == "__main__":
    asyncio.run(main())
