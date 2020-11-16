import logging
from typing import Optional, List, Dict
from binascii import hexlify, unhexlify

from lbry.blockchain import Ledger, Transaction
from lbry.event import BroadcastSubscription

from .base import Service, Sync
from .api import Client as APIClient


log = logging.getLogger(__name__)


class NoSync(Sync):

    def __init__(self, service: Service, client: APIClient):
        super().__init__(service.ledger, service.db)
        self.service = service
        self.client = client
        self.on_block = client.get_event_stream('blockchain.block')
        self.on_block_subscription: Optional[BroadcastSubscription] = None
        self.on_mempool = client.get_event_stream('blockchain.mempool')
        self.on_mempool_subscription: Optional[BroadcastSubscription] = None

    async def start(self):
        pass

    async def stop(self):
        pass

    async def get_block_headers(self, start_height: int, end_height: int = None):
        return await self.db.get_block_headers(start_height, end_height)

    async def get_best_block_height(self) -> int:
        return await self.db.get_best_block_height()


class FullEndpoint(Service):

    name = "endpoint"

    sync: 'NoSync'

    def __init__(self, ledger: Ledger):
        super().__init__(ledger)
        self.client = APIClient(
            f"http://{ledger.conf.full_nodes[0][0]}:{ledger.conf.full_nodes[0][1]}/api"
        )
        self.sync = NoSync(self, self.client)

    async def get_block_headers(self, first, last=None):
        return await self.db.get_block_headers(first, last)

    async def get_address_filters(self, start_height: int, end_height: int = None, granularity: int = 0):
        return await self.db.get_filters(
            start_height=start_height, end_height=end_height, granularity=granularity
        )

    async def search_transactions(self, txids):
        tx_hashes = [unhexlify(txid)[::-1] for txid in txids]
        return {
            hexlify(tx['tx_hash'][::-1]).decode(): hexlify(tx['raw']).decode()
            for tx in await self.db.get_transactions(tx_hashes=tx_hashes)
        }

    async def broadcast(self, tx):
        pass

    async def wait(self, tx: Transaction, height=-1, timeout=1):
        pass

    async def resolve(self, urls, **kwargs):
        pass

    async def search_claims(self, accounts, **kwargs):
        pass

    async def search_supports(self, accounts, **kwargs):
        pass

    async def sum_supports(self, claim_hash: bytes, include_channel_content=False) -> List[Dict]:
        return await self.db.sum_supports(claim_hash, include_channel_content)
