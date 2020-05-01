import os
import asyncio
import logging
from datetime import datetime
from typing import Iterable, List, Optional, NamedTuple

from lbry.db import Database
from lbry.db.constants import TXO_TYPES
from lbry.blockchain.dewies import dewies_to_lbc
from lbry.blockchain.transaction import Transaction, Output
from lbry.blockchain.ledger import Ledger
from lbry.crypto.bip32 import PubKey, PrivateKey
from lbry.wallet.account import Account, AddressManager, SingleKey
from lbry.wallet.manager import WalletManager
from lbry.event import EventController

log = logging.getLogger(__name__)


class BlockEvent(NamedTuple):
    height: int


class Sync:

    def __init__(self, service: 'Service'):
        self.service = service

        self._on_block_controller = EventController()
        self.on_block = self._on_block_controller.stream

        self._on_progress_controller = EventController()
        self.on_progress = self._on_progress_controller.stream

        self._on_ready_controller = EventController()
        self.on_ready = self._on_ready_controller.stream

    def on_bulk_started(self):
        return self.on_progress.where()  # filter for bulk started event

    def on_bulk_started(self):
        return self.on_progress.where()  # filter for bulk started event

    def on_bulk_finished(self):
        return self.on_progress.where()  # filter for bulk finished event

    async def start(self):
        raise NotImplementedError

    async def stop(self):
        raise NotImplementedError


class Service:
    """
    Base class for light client and full node LBRY service implementations.
    """

    sync: Sync

    def __init__(self, ledger: Ledger, db_url: str):
        self.ledger, self.conf = ledger, ledger.conf
        self.db = Database(ledger, db_url)
        self.wallet_manager = WalletManager(ledger, self.db)

        #self.on_address = sync.on_address
        #self.accounts = sync.accounts
        #self.on_header = sync.on_header
        #self.on_ready = sync.on_ready
        #self.on_transaction = sync.on_transaction

        # sync has established connection with a source from which it can synchronize
        # for full service this is lbrycrd (or sync service) and for light this is full node
        self._on_connected_controller = EventController()
        self.on_connected = self._on_connected_controller.stream

    async def start(self):
        await self.db.open()
        await self.wallet_manager.open()
        await self.sync.start()

    async def stop(self):
        await self.sync.stop()
        await self.db.close()

    def get_status(self):
        pass

    def get_version(self):
        pass

    async def find_ffmpeg(self):
        pass

    async def get(self, uri, **kwargs):
        pass

    async def get_block_address_filters(self):
        raise NotImplementedError

    async def get_transaction_address_filters(self, block_hash):
        raise NotImplementedError

    def create_wallet(self, file_name):
        path = os.path.join(self.conf.wallet_dir, file_name)
        return self.wallet_manager.import_wallet(path)

    def add_account(self, account: Account):
        self.ledger.add_account(account)

    async def get_private_key_for_address(self, wallet, address) -> Optional[PrivateKey]:
        return await self.ledger.get_private_key_for_address(wallet, address)

    async def get_public_key_for_address(self, wallet, address) -> Optional[PubKey]:
        return await self.ledger.get_public_key_for_address(wallet, address)

    async def get_account_for_address(self, wallet, address):
        return await self.ledger.get_account_for_address(wallet, address)

    async def get_effective_amount_estimators(self, funding_accounts: Iterable[Account]):
        return await self.ledger.get_effective_amount_estimators(funding_accounts)

    async def get_addresses(self, **constraints):
        return await self.db.get_addresses(**constraints)

    def get_address_count(self, **constraints):
        return self.db.get_address_count(**constraints)

    async def get_spendable_utxos(self, amount: int, funding_accounts):
        return await self.ledger.get_spendable_utxos(amount, funding_accounts)

    def reserve_outputs(self, txos):
        return self.db.reserve_outputs(txos)

    def release_outputs(self, txos):
        return self.db.release_outputs(txos)

    def release_tx(self, tx):
        return self.release_outputs([txi.txo_ref.txo for txi in tx.inputs])

    def get_utxos(self, **constraints):
        self.constraint_spending_utxos(constraints)
        return self.db.get_utxos(**constraints)

    def get_utxo_count(self, **constraints):
        self.constraint_spending_utxos(constraints)
        return self.db.get_utxo_count(**constraints)

    async def get_txos(self, resolve=False, **constraints) -> List[Output]:
        txos = await self.db.get_txos(**constraints)
        if resolve:
            return await self._resolve_for_local_results(constraints.get('accounts', []), txos)
        return txos

    def get_txo_count(self, **constraints):
        return self.db.get_txo_count(**constraints)

    def get_txo_sum(self, **constraints):
        return self.db.get_txo_sum(**constraints)

    def get_txo_plot(self, **constraints):
        return self.db.get_txo_plot(**constraints)

    def get_transactions(self, **constraints):
        return self.db.get_transactions(**constraints)

    def get_transaction_count(self, **constraints):
        return self.db.get_transaction_count(**constraints)

    async def search_transactions(self, txids):
        raise NotImplementedError

    async def announce_addresses(self, address_manager: AddressManager, addresses: List[str]):
        await self.ledger.announce_addresses(address_manager, addresses)

    async def get_address_manager_for_address(self, address) -> Optional[AddressManager]:
        details = await self.db.get_address(address=address)
        for account in self.accounts:
            if account.id == details['account']:
                return account.address_managers[details['chain']]
        return None

    async def broadcast_or_release(self, tx, blocking=False):
        try:
            await self.broadcast(tx)
            if blocking:
                await self.wait(tx, timeout=None)
        except:
            await self.release_tx(tx)
            raise

    async def broadcast(self, tx):
        raise NotImplementedError

    async def wait(self, tx: Transaction, height=-1, timeout=1):
        raise NotImplementedError

    async def resolve(self, accounts, urls, **kwargs):
        raise NotImplementedError

    async def search_claims(
            self, accounts, include_purchase_receipt=False, include_is_my_output=False, **kwargs):
        raise NotImplementedError

    async def get_claim_by_claim_id(self, accounts, claim_id, **kwargs) -> Output:
        for claim in (await self.search_claims(accounts, claim_id=claim_id, **kwargs))[0]:
            return claim

    async def _report_state(self):
        try:
            for account in self.accounts:
                balance = dewies_to_lbc(await account.get_balance(include_claims=True))
                channel_count = await account.get_channel_count()
                claim_count = await account.get_claim_count()
                if isinstance(account.receiving, SingleKey):
                    log.info("Loaded single key account %s with %s LBC. "
                             "%d channels, %d certificates and %d claims",
                             account.id, balance, channel_count, len(account.channel_keys), claim_count)
                else:
                    total_receiving = len(await account.receiving.get_addresses())
                    total_change = len(await account.change.get_addresses())
                    log.info("Loaded account %s with %s LBC, %d receiving addresses (gap: %d), "
                             "%d change addresses (gap: %d), %d channels, %d certificates and %d claims. ",
                             account.id, balance, total_receiving, account.receiving.gap, total_change,
                             account.change.gap, channel_count, len(account.channel_keys), claim_count)
        except Exception as err:
            if isinstance(err, asyncio.CancelledError):  # TODO: remove when updated to 3.8
                raise
            log.exception(
                'Failed to display wallet state, please file issue '
                'for this bug along with the traceback you see below:')

    async def _reset_balance_cache(self, e):
        return await self.ledger._reset_balance_cache(e)

    @staticmethod
    def constraint_spending_utxos(constraints):
        constraints['txo_type__in'] = (0, TXO_TYPES['purchase'])

    async def get_purchases(self, resolve=False, **constraints):
        purchases = await self.db.get_purchases(**constraints)
        if resolve:
            claim_ids = [p.purchased_claim_id for p in purchases]
            try:
                resolved, _, _, _ = await self.claim_search([], claim_ids=claim_ids)
            except Exception as err:
                if isinstance(err, asyncio.CancelledError):  # TODO: remove when updated to 3.8
                    raise
                log.exception("Resolve failed while looking up purchased claim ids:")
                resolved = []
            lookup = {claim.claim_id: claim for claim in resolved}
            for purchase in purchases:
                purchase.purchased_claim = lookup.get(purchase.purchased_claim_id)
        return purchases

    def get_purchase_count(self, resolve=False, **constraints):
        return self.db.get_purchase_count(**constraints)

    async def _resolve_for_local_results(self, accounts, txos):
        results = []
        response = await self.resolve(
            accounts, [txo.permanent_url for txo in txos if txo.can_decode_claim]
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
        return results

    async def get_claims(self, resolve=False, **constraints):
        claims = await self.db.get_claims(**constraints)
        if resolve:
            return await self._resolve_for_local_results(constraints.get('accounts', []), claims)
        return claims

    def get_claim_count(self, **constraints):
        return self.db.get_claim_count(**constraints)

    async def get_streams(self, resolve=False, **constraints):
        streams = await self.db.get_streams(**constraints)
        if resolve:
            return await self._resolve_for_local_results(constraints.get('accounts', []), streams)
        return streams

    def get_stream_count(self, **constraints):
        return self.db.get_stream_count(**constraints)

    async def get_channels(self, resolve=False, **constraints):
        channels = await self.db.get_channels(**constraints)
        if resolve:
            return await self._resolve_for_local_results(constraints.get('accounts', []), channels)
        return channels

    def get_channel_count(self, **constraints):
        return self.db.get_channel_count(**constraints)

    async def resolve_collection(self, collection, offset=0, page_size=1):
        claim_ids = collection.claim.collection.claims.ids[offset:page_size+offset]
        try:
            resolve_results, _, _, _ = await self.claim_search([], claim_ids=claim_ids)
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

    async def get_collections(self, resolve_claims=0, **constraints):
        collections = await self.db.get_collections(**constraints)
        if resolve_claims > 0:
            for collection in collections:
                collection.claims = await self.resolve_collection(collection, page_size=resolve_claims)
        return collections

    def get_collection_count(self, resolve_claims=0, **constraints):
        return self.db.get_collection_count(**constraints)

    def get_supports(self, **constraints):
        return self.db.get_supports(**constraints)

    def get_support_count(self, **constraints):
        return self.db.get_support_count(**constraints)

    async def get_transaction_history(self, **constraints):
        txs: List[Transaction] = await self.db.get_transactions(
            include_is_my_output=True, include_is_spent=True,
            **constraints
        )
        headers = self.headers
        history = []
        for tx in txs:  # pylint: disable=too-many-nested-blocks
            ts = headers.estimated_timestamp(tx.height)
            item = {
                'txid': tx.id,
                'timestamp': ts,
                'date': datetime.fromtimestamp(ts).isoformat(' ')[:-3] if tx.height > 0 else None,
                'confirmations': (headers.height+1) - tx.height if tx.height > 0 else 0,
                'claim_info': [],
                'update_info': [],
                'support_info': [],
                'abandon_info': [],
                'purchase_info': []
            }
            is_my_inputs = all([txi.is_my_input for txi in tx.inputs])
            if is_my_inputs:
                # fees only matter if we are the ones paying them
                item['value'] = dewies_to_lbc(tx.net_account_balance+tx.fee)
                item['fee'] = dewies_to_lbc(-tx.fee)
            else:
                # someone else paid the fees
                item['value'] = dewies_to_lbc(tx.net_account_balance)
                item['fee'] = '0.0'
            for txo in tx.my_claim_outputs:
                item['claim_info'].append({
                    'address': txo.get_address(self.ledger),
                    'balance_delta': dewies_to_lbc(-txo.amount),
                    'amount': dewies_to_lbc(txo.amount),
                    'claim_id': txo.claim_id,
                    'claim_name': txo.claim_name,
                    'nout': txo.position,
                    'is_spent': txo.is_spent,
                })
            for txo in tx.my_update_outputs:
                if is_my_inputs:  # updating my own claim
                    previous = None
                    for txi in tx.inputs:
                        if txi.txo_ref.txo is not None:
                            other_txo = txi.txo_ref.txo
                            if (other_txo.is_claim or other_txo.script.is_support_claim) \
                                    and other_txo.claim_id == txo.claim_id:
                                previous = other_txo
                                break
                    if previous is not None:
                        item['update_info'].append({
                            'address': txo.get_address(self),
                            'balance_delta': dewies_to_lbc(previous.amount-txo.amount),
                            'amount': dewies_to_lbc(txo.amount),
                            'claim_id': txo.claim_id,
                            'claim_name': txo.claim_name,
                            'nout': txo.position,
                            'is_spent': txo.is_spent,
                        })
                else:  # someone sent us their claim
                    item['update_info'].append({
                        'address': txo.get_address(self),
                        'balance_delta': dewies_to_lbc(0),
                        'amount': dewies_to_lbc(txo.amount),
                        'claim_id': txo.claim_id,
                        'claim_name': txo.claim_name,
                        'nout': txo.position,
                        'is_spent': txo.is_spent,
                    })
            for txo in tx.my_support_outputs:
                item['support_info'].append({
                    'address': txo.get_address(self.ledger),
                    'balance_delta': dewies_to_lbc(txo.amount if not is_my_inputs else -txo.amount),
                    'amount': dewies_to_lbc(txo.amount),
                    'claim_id': txo.claim_id,
                    'claim_name': txo.claim_name,
                    'is_tip': not is_my_inputs,
                    'nout': txo.position,
                    'is_spent': txo.is_spent,
                })
            if is_my_inputs:
                for txo in tx.other_support_outputs:
                    item['support_info'].append({
                        'address': txo.get_address(self.ledger),
                        'balance_delta': dewies_to_lbc(-txo.amount),
                        'amount': dewies_to_lbc(txo.amount),
                        'claim_id': txo.claim_id,
                        'claim_name': txo.claim_name,
                        'is_tip': is_my_inputs,
                        'nout': txo.position,
                        'is_spent': txo.is_spent,
                    })
            for txo in tx.my_abandon_outputs:
                item['abandon_info'].append({
                    'address': txo.get_address(self.ledger),
                    'balance_delta': dewies_to_lbc(txo.amount),
                    'amount': dewies_to_lbc(txo.amount),
                    'claim_id': txo.claim_id,
                    'claim_name': txo.claim_name,
                    'nout': txo.position
                })
            for txo in tx.any_purchase_outputs:
                item['purchase_info'].append({
                    'address': txo.get_address(self.ledger),
                    'balance_delta': dewies_to_lbc(txo.amount if not is_my_inputs else -txo.amount),
                    'amount': dewies_to_lbc(txo.amount),
                    'claim_id': txo.purchased_claim_id,
                    'nout': txo.position,
                    'is_spent': txo.is_spent,
                })
            history.append(item)
        return history

    def get_transaction_history_count(self, **constraints):
        return self.db.get_transaction_count(**constraints)

    async def get_detailed_balance(self, accounts, confirmations=0):
        return self.ledger.get_detailed_balance(accounts, confirmations)
