import logging
from binascii import hexlify, unhexlify

from lbry.blockchain.lbrycrd import Lbrycrd
from lbry.blockchain.sync import BlockchainSync
from lbry.blockchain.ledger import Ledger
from lbry.blockchain.transaction import Transaction

from .base import Service


log = logging.getLogger(__name__)


class FullNode(Service):

    sync: BlockchainSync

    def __init__(self, ledger: Ledger, chain: Lbrycrd = None):
        super().__init__(ledger)
        self.chain = chain or Lbrycrd(ledger)
        self.sync = BlockchainSync(self.chain, self.db)

    async def start(self):
        await self.chain.open()
        await super().start()

    async def stop(self):
        await super().stop()
        await self.chain.close()

    async def get_status(self):
        return 'everything is wonderful'

    async def get_block_address_filters(self):
        return {
            hexlify(f['block_hash']).decode(): hexlify(f['block_filter']).decode()
            for f in await self.db.get_block_address_filters()
        }

    async def search_transactions(self, txids):
        tx_hashes = [unhexlify(txid)[::-1] for txid in txids]
        return {
            hexlify(tx['tx_hash'][::-1]).decode(): hexlify(tx['raw']).decode()
            for tx in await self.db.get_transactions(tx_hashes=tx_hashes)
        }

    async def search_claims(self, accounts, **kwargs):
        return await self.db.search_claims(**kwargs)

    async def get_transaction_address_filters(self, block_hash):
        return {
            hexlify(f['tx_hash'][::-1]).decode(): hexlify(f['tx_filter']).decode()
            for f in await self.db.get_transaction_address_filters(unhexlify(block_hash))
        }

    async def broadcast(self, tx):
        return await self.chain.send_raw_transaction(hexlify(tx.raw).decode())

    async def wait(self, tx: Transaction, height=-1, timeout=1):
        pass

    async def resolve(self, urls, **kwargs):
        return await self.db.resolve(*urls)
