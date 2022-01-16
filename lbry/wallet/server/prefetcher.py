import asyncio
import typing

from lbry.wallet.server.util import chunks, class_logger
if typing.TYPE_CHECKING:
    from lbry.wallet.server.daemon import LBCDaemon
    from lbry.wallet.server.coin import Coin


class Prefetcher:
    """Prefetches blocks (in the forward direction only)."""

    def __init__(self, daemon: 'LBCDaemon', coin: 'Coin', blocks_event: asyncio.Event):
        self.logger = class_logger(__name__, self.__class__.__name__)
        self.daemon = daemon
        self.coin = coin
        self.blocks_event = blocks_event
        self.blocks = []
        self.caught_up = False
        # Access to fetched_height should be protected by the semaphore
        self.fetched_height = None
        self.semaphore = asyncio.Semaphore()
        self.refill_event = asyncio.Event()
        # The prefetched block cache size.  The min cache size has
        # little effect on sync time.
        self.cache_size = 0
        self.min_cache_size = 10 * 1024 * 1024
        # This makes the first fetch be 10 blocks
        self.ave_size = self.min_cache_size // 10
        self.polling_delay = 0.5

    async def main_loop(self, bp_height):
        """Loop forever polling for more blocks."""
        await self.reset_height(bp_height)
        try:
            while True:
                # Sleep a while if there is nothing to prefetch
                await self.refill_event.wait()
                if not await self._prefetch_blocks():
                    await asyncio.sleep(self.polling_delay)
        finally:
            self.logger.info("block pre-fetcher is shutting down")

    def get_prefetched_blocks(self):
        """Called by block processor when it is processing queued blocks."""
        blocks = self.blocks
        self.blocks = []
        self.cache_size = 0
        self.refill_event.set()
        return blocks

    async def reset_height(self, height):
        """Reset to prefetch blocks from the block processor's height.

        Used in blockchain reorganisations.  This coroutine can be
        called asynchronously to the _prefetch_blocks coroutine so we
        must synchronize with a semaphore.
        """
        async with self.semaphore:
            self.blocks.clear()
            self.cache_size = 0
            self.fetched_height = height
            self.refill_event.set()

        daemon_height = await self.daemon.height()
        behind = daemon_height - height
        if behind > 0:
            self.logger.info(f'catching up to daemon height {daemon_height:,d} '
                             f'({behind:,d} blocks behind)')
        else:
            self.logger.info(f'caught up to daemon height {daemon_height:,d}')

    async def _prefetch_blocks(self):
        """Prefetch some blocks and put them on the queue.

        Repeats until the queue is full or caught up.
        """
        daemon = self.daemon
        daemon_height = await daemon.height()
        async with self.semaphore:
            while self.cache_size < self.min_cache_size:
                # Try and catch up all blocks but limit to room in cache.
                # Constrain fetch count to between 0 and 500 regardless;
                # testnet can be lumpy.
                cache_room = self.min_cache_size // self.ave_size
                count = min(daemon_height - self.fetched_height, cache_room)
                count = min(500, max(count, 0))
                if not count:
                    self.caught_up = True
                    return False

                first = self.fetched_height + 1
                hex_hashes = await daemon.block_hex_hashes(first, count)
                if self.caught_up:
                    self.logger.info('new block height {:,d} hash {}'
                                     .format(first + count-1, hex_hashes[-1]))
                blocks = await daemon.raw_blocks(hex_hashes)

                assert count == len(blocks)

                # Special handling for genesis block
                if first == 0:
                    blocks[0] = self.coin.genesis_block(blocks[0])
                    self.logger.info(f'verified genesis block with hash {hex_hashes[0]}')

                # Update our recent average block size estimate
                size = sum(len(block) for block in blocks)
                if count >= 10:
                    self.ave_size = size // count
                else:
                    self.ave_size = (size + (10 - count) * self.ave_size) // 10

                self.blocks.extend(blocks)
                self.cache_size += size
                self.fetched_height += count
                self.blocks_event.set()

        self.refill_event.clear()
        return True
