import logging

from lbry.conf import Config
from lbry.service.api import Client
from lbry.blockchain.ledger import Ledger
from lbry.db import Database
from lbry.wallet.sync import SPVSync

from .base import Service

log = logging.getLogger(__name__)


class LightClient(Service):

    def __init__(self, ledger: Ledger, db_url: str):
        super().__init__(ledger, db_url)
        self.client = Client(self, Config().api_connection_url)#ledger.conf)
        self.sync = SPVSync(self)

    async def search_transactions(self, txids):
        return await self.client.transaction_search(txids=txids)

    async def get_block_address_filters(self):
        return await self.client.address_block_filters()

    async def get_transaction_address_filters(self, block_hash):
        return await self.client.address_transaction_filters(block_hash=block_hash)
