import logging
from binascii import hexlify, unhexlify
from typing import List, Dict, Tuple

from lbry.blockchain.lbrycrd import Lbrycrd
from lbry.blockchain.sync import BlockchainSync
from lbry.blockchain.ledger import Ledger
from lbry.blockchain.transaction import Transaction

from .base import Service


log = logging.getLogger(__name__)


class FullNode(Service):

    name = "node"

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

#    async def get_block_address_filters(self):
#        return {
#            hexlify(f['block_hash']).decode(): hexlify(f['block_filter']).decode()
#            for f in await self.db.get_block_address_filters()
#        }

    async def search_transactions(self, txids):
        tx_hashes = [unhexlify(txid)[::-1] for txid in txids]
        return {
            hexlify(tx['tx_hash'][::-1]).decode(): hexlify(tx['raw']).decode()
            for tx in await self.db.get_transactions(tx_hashes=tx_hashes)
        }

    async def broadcast(self, tx):
        return await self.chain.send_raw_transaction(hexlify(tx.raw).decode())

    async def wait(self, tx: Transaction, height=-1, timeout=1):
        pass

    async def search_claims(self, accounts, **kwargs):
        return await self.db.search_claims(**kwargs)

    async def protobuf_search_claims(self, **kwargs):
        return await self.db.protobuf_search_claims(**kwargs)

    async def search_supports(self, accounts, **kwargs):
        return await self.db.search_supports(**kwargs)

    async def resolve(self, urls, **kwargs):
        return await self.db.resolve(urls, **kwargs)

    async def protobuf_resolve(self, urls, **kwargs):
        return await self.db.protobuf_resolve(urls, **kwargs)

    async def sum_supports(self, claim_hash: bytes, include_channel_content=False, exclude_own_supports=False) \
            -> Tuple[List[Dict], int]:
        return await self.db.sum_supports(claim_hash, include_channel_content, exclude_own_supports)
