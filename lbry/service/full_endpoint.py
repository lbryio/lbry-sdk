import logging
from binascii import hexlify, unhexlify

from lbry.blockchain.lbrycrd import Lbrycrd
from lbry.blockchain.sync import BlockchainSync
from lbry.blockchain.ledger import Ledger
from lbry.blockchain.transaction import Transaction

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

    async def wait_for_client_ready(self):
        await self.client.connect()

    async def start(self):
        self.db.stop_event.clear()
        await self.wait_for_client_ready()
        self.advance_loop_task = asyncio.create_task(self.advance())
        await self.advance_loop_task
        await self.client.subscribe()
        self.advance_loop_task = asyncio.create_task(self.advance_loop())
        self.on_block_subscription = self.on_block.listen(
            lambda e: self.on_block_event.set()
        )
        self.on_mempool_subscription = self.on_mempool.listen(
            lambda e: self.on_mempool_event.set()
        )
        await self.download_filters()
        await self.download_headers()

    async def stop(self):
        await self.client.disconnect()


class FullEndpoint(Service):

    name = "endpoint"

    sync: 'NoSync'

    def __init__(self, ledger: Ledger):
        super().__init__(ledger)
        self.client = APIClient(
            f"http://{ledger.conf.full_nodes[0][0]}:{ledger.conf.full_nodes[0][1]}/api"
        )
        self.sync = NoSync(self, self.client)
