import asyncio
import argparse
from random import randrange
from typing import List
from binascii import unhexlify
from google.protobuf.message import DecodeError

from lbry import Config, Ledger, FullNode
from lbry.console import Advanced, Basic
from lbry.schema.claim import Claim
from lbry.db.utils import chunk
from lbry.testcase import EventGenerator


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
        self.starting_height = 0
        self.ending_height = 0
        self.starting_file = 0
        self.workers = console.service.db.workers

        self.txs = 0
        self.claims = 0
        self.supports = 0

    @property
    def blocks(self, ):
        if self.starting_height == 0:
            return self.ending_height-self.starting_height
        return (self.ending_height-self.starting_height)+1

    async def generate(self, name, units, eid, label, total, steps):
        loop_time = min(5.0 / (total[0]/steps[0]), 1.0)
        done = (0,)*len(total)
        while not all(d >= t for d, t in zip(done, total)):
            if done[0] == 0:
                first_event = {
                    "event": name,
                    "data": {
                        "id": eid,
                        "done": done,
                        "total": total,
                        "units": units,
                    }
                }
                if label is not None:
                    first_event["data"]["label"] = label
                await self.progress.add(first_event)
            await asyncio.sleep(loop_time)
            done = tuple(min(d+s, t) for d, s, t in zip(done, steps, total))
            await self.progress.add({
                "event": name,
                "data": {
                    "id": eid,
                    "done": done,
                }
            })

    async def generate_group(self, name, unit, init_steps, total, increment):
        await self.generate(f"{name}.init", ("steps",), 0, None, (init_steps,), (1,))
        await self.progress.add({
            "event": f"{name}.main",
            "data": {"id": 0, "done": (0,), "total": (total,), "units": (unit,)}
        })
        tasks = []
        for group_range in self.make_ranges(total, max(int(total/self.workers), 1)):
            tasks.append(self.generate(
                f"{name}.insert", (unit,),
                group_range[0], f"add {unit} at {group_range[0]}-{group_range[1]}",
                (group_range[1] - group_range[0],), (increment,)
            ))
        await asyncio.wait(tasks)
        await self.close_event(f"{name}.main")

    async def close_event(self, name):
        await self.progress.add({"event": name, "data": {"id": 0, "done": (-1, -1)}})

    @staticmethod
    def make_ranges(num, size=1000):
        ranges = []
        for i in range(0, num, size):
            if ranges:
                ranges[-1][-1] = i-1
            ranges.append([i, 0])
        ranges[-1][-1] = num
        return ranges

    async def advance(self, initial_sync: bool, ending_height: int, files: List[int], txs: int):
        self.ending_height = ending_height
        self.txs = txs
        self.claims = int(txs/4)
        self.supports = int(txs/2)
        eg = EventGenerator(
            initial_sync=initial_sync,
            start=self.starting_height,
            end=ending_height,
            block_files=[
                (0, 191, 280, ((100, 0), (191, 280))),
                (1, 89, 178, ((89, 178),)),
                (2, 73, 86, ((73, 86),)),
                (3, 73, 86, ((73, 86),)),
                (4, 73, 86, ((73, 86),)),
                (5, 73, 86, ((73, 86),)),
            ],
            claims=[
                (102, 120, 361, 361),
                (121, 139, 361, 361),
                (140, 158, 361, 361),
                (159, 177, 361, 361),
                (178, 196, 361, 361),
                (197, 215, 361, 361),
                (216, 234, 361, 361),
                (235, 253, 361, 361),
                (254, 272, 361, 361),
                (273, 291, 361, 361),
            ],
            supports=[
                (352, 352, 2, 2),
            ]
        )
        for event in eg.events:
            await self.progress.add(event)
            await asyncio.sleep(0.5)
        return
        blocks_synced = txs_synced = 0
        for file_group in chunk(files, self.workers):
            tasks = []
            for file in file_group:
                if file == files[-1]:
                    cause_protobuf_stderr()
                    tasks.append(self.generate(
                        "blockchain.sync.block.file", ("blocks", "txs"), file, f"blk0000{file}.dat",
                        (self.blocks-blocks_synced, self.txs-txs_synced),
                        (50, 100)
                    ))
                    cause_protobuf_stderr()
                else:
                    blocks = int(self.blocks / len(files))
                    blocks_synced += blocks
                    txs = int(self.txs / len(files))
                    txs_synced += txs
                    tasks.append(self.generate(
                        "blockchain.sync.block.file", ("blocks", "txs"), file, f"blk0000{file}.dat",
                        (blocks, txs), (50, 100)
                    ))
            await asyncio.wait(tasks)
        self.ending_height = ending_height+1
        self.starting_height = self.ending_height


async def main(console):
    sim = Simulator(console)
    await sim.advance(True, 10_000, [1, 2, 3, 4, 5], 10_000)
    #await sim.advance(True, 100_000, [1, 2, 3, 4, 5], 100_000)
    #await sim.advance(False, 100_001, [5], 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--basic", default=False, action="store_true")
    parser.add_argument("--workers", default=3)
    args = parser.parse_args()

    node = FullNode(Ledger(Config(
        workers=args.workers,
        spv_address_filters=False
    )))
    console = Basic(node) if args.basic else Advanced(node)

    try:
        console.starting()
        asyncio.run(main(console))
    except KeyboardInterrupt:
        pass
    finally:
        console.stopping()
