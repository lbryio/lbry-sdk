import asyncio
import logging
from typing import List, Optional, NamedTuple, Dict, Tuple

from lbry.db import Database, Result
from lbry.db.constants import TXO_TYPES
from lbry.blockchain.transaction import Transaction, Output
from lbry.blockchain.ledger import Ledger
from lbry.wallet import WalletManager
from lbry.event import EventController, EventStream

log = logging.getLogger(__name__)


class BlockEvent(NamedTuple):
    height: int


class Sync:
    """
    Maintains local state in sync with some upstream source of truth.
    Client stays synced with wallet server
    Server stays synced with lbrycrd
    """

    on_block: EventStream
    on_mempool: EventStream

    def __init__(self, ledger: Ledger, db: Database):
        self.ledger = ledger
        self.conf = ledger.conf
        self.db = db

        self._on_progress_controller = db._on_progress_controller
        self.on_progress = db.on_progress

        self._on_ready_controller = EventController()
        self.on_ready = self._on_ready_controller.stream

    def on_bulk_started(self):
        return self.on_progress.where()  # filter for bulk started event

    def on_bulk_finished(self):
        return self.on_progress.where()  # filter for bulk finished event

    async def start(self):
        raise NotImplementedError

    async def stop(self):
        raise NotImplementedError

    async def get_block_headers(self, start_height: int, end_height: int = None):
        raise NotImplementedError

    async def get_best_block_height(self) -> int:
        raise NotImplementedError


class Service:
    """
    Base class for light client and full node LBRY service implementations.
    This is the programmatic api (as compared to API)
    """

    sync: Sync

    def __init__(self, ledger: Ledger):
        self.ledger, self.conf = ledger, ledger.conf
        self.db = Database(ledger)
        self.wallets = WalletManager(self.db)

        # sync has established connection with a source from which it can synchronize
        # for full service this is lbrycrd (or sync service) and for light this is full node
        self._on_connected_controller = EventController()
        self.on_connected = self._on_connected_controller.stream

    async def start(self):
        await self.db.open()
        await self.wallets.open()
        await self.sync.start()

    async def stop(self):
        await self.sync.stop()
        await self.wallets.close()
        await self.db.close()

    async def get_status(self):
        pass

    def get_version(self):
        pass

    async def find_ffmpeg(self):
        pass

    async def get_file(self, uri, **kwargs):
        pass

    def create_wallet(self, wallet_id):
        return self.wallets.create(wallet_id)

    async def get_addresses(self, **constraints):
        return await self.db.get_addresses(**constraints)

    async def get_address_filters(self, start_height: int, end_height: int=None, granularity: int=0):
        raise NotImplementedError

    def reserve_outputs(self, txos):
        return self.db.reserve_outputs(txos)

    def release_outputs(self, txos):
        return self.db.release_outputs(txos)

    def release_tx(self, tx):
        return self.release_outputs([txi.txo_ref.txo for txi in tx.inputs])

    def get_utxos(self, **constraints):
        self.constraint_spending_utxos(constraints)
        return self.db.get_utxos(**constraints)

    async def get_txos(self, resolve=False, **constraints) -> Result[Output]:
        txos = await self.db.get_txos(**constraints)
        if resolve:
            return await self._resolve_for_local_results(constraints.get('accounts', []), txos)
        return txos

    def get_txo_sum(self, **constraints):
        return self.db.get_txo_sum(**constraints)

    def get_txo_plot(self, **constraints):
        return self.db.get_txo_plot(**constraints)

    def get_transactions(self, **constraints):
        return self.db.get_transactions(**constraints)

    async def get_transaction(self, tx_hash: bytes):
        tx = await self.db.get_transaction(tx_hash=tx_hash)
        if tx:
            return tx
        # try:
        #     raw, merkle = await self.ledger.network.get_transaction_and_merkle(tx_hash)
        # except CodeMessageError as e:
        #     if 'No such mempool or blockchain transaction.' in e.message:
        #         return {'success': False, 'code': 404, 'message': 'transaction not found'}
        #     return {'success': False, 'code': e.code, 'message': e.message}
        # height = merkle.get('block_height')
        # tx = Transaction(unhexlify(raw), height=height)
        # if height and height > 0:
        #     await self.ledger.maybe_verify_transaction(tx, height, merkle)
        # return tx

    async def search_transactions(self, txids):
        raise NotImplementedError

    async def sum_supports(
        self, claim_hash: bytes, include_channel_content=False, exclude_own_supports=False
    ) -> Tuple[List[Dict], int]:
        raise NotImplementedError

    async def announce_addresses(self, address_manager, addresses: List[str]):
        await self.ledger.announce_addresses(address_manager, addresses)

    async def get_address_manager_for_address(self, address):
        details = await self.db.get_address(address=address)
        for wallet in self.wallets:
            for account in wallet.accounts:
                if account.id == details['account']:
                    return account.address_managers[details['chain']]
        return None

    async def reset(self):
        self.ledger.conf = {
            'auto_connect': True,
            'default_servers': self.conf.lbryum_servers,
            'data_path': self.conf.wallet_dir,
        }
        await self.ledger.stop()
        await self.ledger.start()

    async def get_best_blockhash(self):
        if len(self.ledger.headers) <= 0:
            return self.ledger.genesis_hash
        return (await self.ledger.headers.hash(self.ledger.headers.height)).decode()

    async def maybe_broadcast_or_release(self, tx, preview=False, no_wait=False):
        if preview:
            return await self.release_tx(tx)
        try:
            await self.broadcast(tx)
            if not no_wait:
                await self.wait(tx)
        except Exception:
            await self.release_tx(tx)
            raise

    async def broadcast(self, tx):
        raise NotImplementedError

    async def wait(self, tx: Transaction, height=-1, timeout=1):
        raise NotImplementedError

    async def resolve(self, urls, **kwargs):
        raise NotImplementedError

    async def search_claims(self, accounts, **kwargs) -> Result[Output]:
        raise NotImplementedError

    async def search_supports(self, accounts, **kwargs) -> Result[Output]:
        raise NotImplementedError

    async def get_claim_by_claim_id(self, accounts, claim_id, **kwargs) -> Optional[Output]:
        for claim in await self.search_claims(accounts, claim_id=claim_id, **kwargs):
            return claim

    @staticmethod
    def constraint_spending_utxos(constraints):
        constraints['txo_type__in'] = (0, TXO_TYPES['purchase'])

    async def get_purchases(self, wallet, resolve=False, **constraints):
        purchases = await wallet.get_purchases(**constraints)
        if resolve:
            claim_ids = [p.purchased_claim_id for p in purchases]
            try:
                resolved, _, _ = await self.search_claims([], claim_ids=claim_ids)
            except Exception as err:
                if isinstance(err, asyncio.CancelledError):  # TODO: remove when updated to 3.8
                    raise
                log.exception("Resolve failed while looking up purchased claim ids:")
                resolved = []
            lookup = {claim.claim_id: claim for claim in resolved}
            for purchase in purchases:
                purchase.purchased_claim = lookup.get(purchase.purchased_claim_id)
        return purchases

    async def _resolve_for_local_results(self, accounts, txos: Result) -> Result:
        results = []
        response = await self.resolve(
            [txo.permanent_url for txo in txos if txo.can_decode_claim], accounts=accounts
        )
        for txo in txos:
            resolved = response.get(txo.permanent_url) if txo.can_decode_claim else None
            if isinstance(resolved, Output):
                resolved.update_annotations(txo)
                results.append(resolved)
            else:
                if isinstance(resolved, dict) and 'error' in resolved:
                    txo.meta['error'] = resolved['error']
                results.append(txo)
        txos.rows = results
        return txos

    async def resolve_collection(self, collection, offset=0, page_size=1):
        claim_ids = collection.claim.collection.claims.ids[offset:page_size+offset]
        try:
            resolve_results, _, _ = await self.search_claims([], claim_ids=claim_ids)
        except Exception as err:
            if isinstance(err, asyncio.CancelledError):  # TODO: remove when updated to 3.8
                raise
            log.exception("Resolve failed while looking up collection claim ids:")
            return []
        claims = []
        for claim_id in claim_ids:
            found = False
            for txo in resolve_results:
                if txo.claim_id == claim_id:
                    claims.append(txo)
                    found = True
                    break
            if not found:
                claims.append(None)
        return claims
