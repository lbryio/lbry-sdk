import logging

from lbry.conf import Config
from lbry.blockchain import Ledger, Transaction
from lbry.wallet.sync import SPVSync

from .base import Service
from .api import Client

log = logging.getLogger(__name__)


class LightClient(Service):

    name = "client"

    sync: SPVSync

    def __init__(self, ledger: Ledger):
        super().__init__(ledger)
        self.client = Client(Config().api_connection_url)
        self.sync = SPVSync(self)

    async def search_transactions(self, txids):
        return await self.client.transaction_search(txids=txids)

    async def get_block_address_filters(self):
        return await self.client.address_block_filters()

    async def get_transaction_address_filters(self, block_hash):
        return await self.client.address_transaction_filters(block_hash=block_hash)

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
