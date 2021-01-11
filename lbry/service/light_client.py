import asyncio
import logging
from typing import Dict
from typing import List, Optional, Tuple
from binascii import hexlify, unhexlify

from lbry.blockchain.block import Block
from lbry.event import EventController, BroadcastSubscription
from lbry.crypto.hash import double_sha256
from lbry.wallet import WalletManager
from lbry.blockchain import Ledger, Transaction
from lbry.db import Database

from .base import Service, Sync
from .api import Client as APIClient


log = logging.getLogger(__name__)


class LightClient(Service):

    name = "client"

    sync: 'FastSync'

    def __init__(self, ledger: Ledger):
        super().__init__(ledger)
        self.client = APIClient(
            f"http://{ledger.conf.full_nodes[0][0]}:{ledger.conf.full_nodes[0][1]}/ws"
        )
        self.sync = FastSync(self, self.client)

    async def start(self):
        await self.client.connect()
        await super().start()
        await self.client.start_event_streams()
        self.wallets.on_change.listen(
            lambda _: self.sync.on_block_event.set()
        )

    async def stop(self):
        await super().stop()
        await self.client.disconnect()

    async def search_transactions(self, txids, raw: bool = False):
        return await self.client.first.transaction_search(txids=txids, raw=raw)

    async def get_address_filters(self, start_height: int, end_height: int = None, granularity: int = 0):
        return await self.client.first.address_filter(
            granularity=granularity, start_height=start_height, end_height=end_height
        )

    async def broadcast(self, tx):
        return await self.client.first.transaction_broadcast(tx=hexlify(tx.raw).decode())

    async def wait(self, tx: Transaction, height=-1, timeout=1):
        pass

    async def resolve(self, urls, **kwargs):
        pass

    async def search_claims(self, accounts, **kwargs):
        pass

    async def search_supports(self, accounts, **kwargs):
        pass

    async def sum_supports(
        self, claim_hash: bytes, include_channel_content=False, exclude_own_supports=False
    ) -> Tuple[List[Dict], int]:
        return await self.client.sum_supports(claim_hash, include_channel_content, exclude_own_supports)


class FilterManager:
    """
    Efficient on-demand address filter access.
    Stores and retrieves from local db what it previously downloaded and
    downloads on-demand what it doesn't have from full node.
    """

    def __init__(self, db: Database, client: APIClient):
        self.db = db
        self.client = client
        self.cache = {}

    async def download_and_save_filters(self, needed_filters):
        for factor, filter_start, filter_end in needed_filters:
            if factor == 0:
                print(
                    f'=> address_filter(granularity={factor}, '
                    f'start_height={filter_start}, end_height={filter_end})'
                )
                filters = await self.client.first.address_filter(
                    granularity=factor, start_height=filter_start, end_height=filter_end
                )
                print(
                    f'<= address_filter(granularity={factor}, '
                    f'start_height={filter_start}, end_height={filter_end})'
                )
                print(f'  inserting {len(filters)} tx filters...')
                await self.db.insert_tx_filters((
                    unhexlify(tx_filter["txid"])[::-1],
                    tx_filter["height"],
                    unhexlify(tx_filter["filter"])
                ) for tx_filter in filters)
            elif factor <= 3:
                print(
                    f'=> address_filter(granularity={factor}, '
                    f'start_height={filter_start}, end_height={filter_end})'
                )
                filters = await self.client.first.address_filter(
                    granularity=factor, start_height=filter_start, end_height=filter_end
                )
                print(
                    f'<= address_filter(granularity={factor}, '
                    f'start_height={filter_start}, end_height={filter_end})'
                )
                await self.db.insert_block_filters(
                    (block_filter["height"], factor, unhexlify(block_filter["filter"]))
                    for block_filter in filters
                )
            else:
                for start in range(filter_start, filter_end+1, 10**factor):
                    print(f'=> address_filter(granularity={factor}, start_height={start})')
                    filters = await self.client.first.address_filter(
                        granularity=factor, start_height=start
                    )
                    print(f'<= address_filter(granularity={factor}, start_height={start})')
                    await self.db.insert_block_filters(
                        (block_filter["height"], factor, unhexlify(block_filter["filter"]))
                        for block_filter in filters
                    )

    async def download_and_save_txs(self, tx_hashes):
        if not tx_hashes:
            return
        txids = [hexlify(tx_hash[::-1]).decode() for tx_hash in tx_hashes]
        print(f'=> transaction_search(len(txids): {len(txids)})')
        txs = await self.client.first.transaction_search(txids=txids, raw=True)
        print(f' @ transaction_search(len(txids): {len(txids)})')
        for raw_tx in txs.values():
            await self.db.insert_transaction(None, Transaction(unhexlify(raw_tx)))
        print(f' # transaction_search(len(txids): {len(txids)})')

    async def download_initial_filters(self, best_height):
        missing = await self.db.get_missing_required_filters(best_height)
        await self.download_and_save_filters(missing)

    async def generate_addresses(self, best_height: int, wallets: WalletManager):
        for wallet in wallets:
            for account in wallet.accounts:
                for address_manager in account.address_managers.values():
                    print(
                        f"  matching addresses for account {account.id} "
                        f"address group {address_manager.chain_number}..."
                    )
                    missing = await self.db.generate_addresses_using_filters(
                        best_height, address_manager.gap, (
                            account.id,
                            address_manager.chain_number,
                            address_manager.public_key.pubkey_bytes,
                            address_manager.public_key.chain_code,
                            address_manager.public_key.depth
                        )
                    )
                    if missing:
                        print("downloading level 3 filters")
                        await self.download_and_save_filters(missing)

    async def download_sub_filters(self, granularity: int, wallets: WalletManager):
        for wallet in wallets:
            for account in wallet.accounts:
                for address_manager in account.address_managers.values():
                    missing = await self.db.get_missing_sub_filters_for_addresses(
                        granularity, (account.id, address_manager.chain_number)
                    )
                    await self.download_and_save_filters(missing)

    async def download_transactions(self, wallets: WalletManager):
        for wallet in wallets:
            for account in wallet.accounts:
                for address_manager in account.address_managers.values():
                    print(f'get_missing_tx_for_addresses({account.id})')
                    missing = await self.db.get_missing_tx_for_addresses(
                        (account.id, address_manager.chain_number)
                    )
                    print(f'  len(missing): {len(missing)}')
                    await self.download_and_save_txs(missing)

    async def download(self, best_height: int, wallets: WalletManager):
        print('downloading initial filters...')
        await self.download_initial_filters(best_height)
        print('generating addresses...')
        await self.generate_addresses(best_height, wallets)
        print("downloading level 2 filters...")
        await self.download_sub_filters(3, wallets)
        print("downloading level 1 filters...")
        await self.download_sub_filters(2, wallets)
        print("downloading tx filters...")
        await self.download_sub_filters(1, wallets)
        print("downloading transactions...")
        await self.download_transactions(wallets)
        print(f" = finished sync'ing up-to block {best_height} = ")

    @staticmethod
    def get_root_of_merkle_tree(branches, branch_positions, working_branch):
        for i, branch in enumerate(branches):
            other_branch = unhexlify(branch)[::-1]
            other_branch_on_left = bool((branch_positions >> i) & 1)
            if other_branch_on_left:
                combined = other_branch + working_branch
            else:
                combined = working_branch + other_branch
            working_branch = double_sha256(combined)
        return hexlify(working_branch[::-1])

#    async def maybe_verify_transaction(self, tx, remote_height, merkle=None):
#        tx.height = remote_height
#        cached = self._tx_cache.get(tx.hash)
#        if not cached:
#            # cache txs looked up by transaction_show too
#            cached = TransactionCacheItem()
#            cached.tx = tx
#            self._tx_cache[tx.hash] = cached
#        if 0 < remote_height < len(self.headers) and cached.pending_verifications <= 1:
#            # can't be tx.pending_verifications == 1 because we have to handle the transaction_show case
#            if not merkle:
#                merkle = await self.network.retriable_call(self.network.get_merkle, tx.hash, remote_height)
#            merkle_root = self.get_root_of_merkle_tree(merkle['merkle'], merkle['pos'], tx.hash)
#            header = await self.headers.get(remote_height)
#            tx.position = merkle['pos']
#            tx.is_verified = merkle_root == header['merkle_root']


class BlockHeaderManager:
    """
    Efficient on-demand block header access.
    Stores and retrieves from local db what it previously downloaded and
    downloads on-demand what it doesn't have from full node.
    """

    def __init__(self, db: Database, client: APIClient):
        self.db = db
        self.client = client
        self.cache = {}

    async def download(self, best_height):
        print('downloading blocks...')
        our_height = await self.db.get_best_block_height()
        for start in range(our_height+1, best_height, 50000):
            end = min(start+9999, best_height)
            print(f'=> block_list(start_height={start}, end_height={end})')
            blocks = await self.client.first.block_list(start_height=start, end_height=end)
            print(f'<= block_list(start_height={start}, end_height={end})')
            await self.db.insert_blocks([Block(
                height=block["height"],
                version=0,
                file_number=0,
                block_hash=unhexlify(block["block_hash"]),
                prev_block_hash=unhexlify(block["previous_hash"]),
                merkle_root=b'',  # block["merkle_root"],
                claim_trie_root=b'',  # block["claim_trie_root"],
                timestamp=block["timestamp"],
                bits=0,  # block["bits"],
                nonce=0,  # block["nonce"],
                txs=[]
            ) for block in blocks])

    async def get_header(self, height):
        blocks = await self.client.first.block_list(height=height)
        if blocks:
            return blocks[0]


class FastSync(Sync):

    def __init__(self, service: Service, client: APIClient):
        super().__init__(service.ledger, service.db)
        self.service = service
        self.client = client
        self.advance_loop_task: Optional[asyncio.Task] = None
        self.on_block = client.get_event_stream("blockchain.block")
        self.on_block_event = asyncio.Event()
        self.on_block_subscription: Optional[BroadcastSubscription] = None
        self._on_synced_controller = EventController()
        self.on_synced = self._on_synced_controller.stream
        self.conf.events.register("blockchain.block", self.on_synced)
        self.blocks = BlockHeaderManager(self.db, self.client)
        self.filters = FilterManager(self.db, self.client)
        self.best_height: Optional[int] = None

    async def get_block_headers(self, start_height: int, end_height: int = None):
        return await self.client.first.block_list(start_height, end_height)

    async def get_best_block_height(self) -> int:
        return await self.client.first.block_tip()

    async def start(self):
        self.on_block_subscription = self.on_block.listen(self.handle_on_block)
        self.advance_loop_task = asyncio.create_task(self.advance())
        await self.advance_loop_task
        self.advance_loop_task = asyncio.create_task(self.loop())

    async def stop(self):
        for task in (self.on_block_subscription, self.advance_loop_task):
            if task is not None:
                task.cancel()

    def handle_on_block(self, e):
        self.best_height = e[0]
        self.on_block_event.set()

    async def advance(self):
        height = self.best_height or await self.client.first.block_tip()
        await self.blocks.download(height)
        await self.filters.download(height, self.service.wallets)
        # await asyncio.wait([
        #     self.blocks.download(height),
        #     self.filters.download(height, self.service.wallets),
        # ])
        await self._on_synced_controller.add(height)

    async def loop(self):
        while True:
            try:
                await self.on_block_event.wait()
                self.on_block_event.clear()
                await self.advance()
            except asyncio.CancelledError:
                return
            except Exception as e:
                log.exception(e)
                await self.stop()
