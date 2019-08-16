import asyncio
import logging
from binascii import unhexlify
from typing import Tuple, List
from datetime import datetime

from torba.client.baseledger import BaseLedger
from torba.client.baseaccount import SingleKey
from lbry.schema.result import Outputs
from lbry.schema.url import URL
from lbry.wallet.dewies import dewies_to_lbc
from lbry.wallet.account import Account
from lbry.wallet.network import Network
from lbry.wallet.database import WalletDatabase
from lbry.wallet.transaction import Transaction, Output
from lbry.wallet.header import Headers, UnvalidatedHeaders


log = logging.getLogger(__name__)


class MainNetLedger(BaseLedger):
    name = 'LBRY Credits'
    symbol = 'LBC'
    network_name = 'mainnet'

    headers: Headers

    account_class = Account
    database_class = WalletDatabase
    headers_class = Headers
    network_class = Network
    transaction_class = Transaction

    db: WalletDatabase

    secret_prefix = bytes((0x1c,))
    pubkey_address_prefix = bytes((0x55,))
    script_address_prefix = bytes((0x7a,))
    extended_public_key_prefix = unhexlify('0488b21e')
    extended_private_key_prefix = unhexlify('0488ade4')

    max_target = 0x0000ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = '9c89283ba0f3227f6c03b70216b9f665f0118d5e0fa729cedf4fb34d6a34f463'
    genesis_bits = 0x1f00ffff
    target_timespan = 150

    default_fee_per_byte = 50
    default_fee_per_name_char = 200000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fee_per_name_char = self.config.get('fee_per_name_char', self.default_fee_per_name_char)

    async def _inflate_outputs(self, query):
        outputs = Outputs.from_base64(await query)
        txs = []
        if len(outputs.txs) > 0:
            txs = await asyncio.gather(*(self.cache_transaction(*tx) for tx in outputs.txs))
        return outputs.inflate(txs), outputs.offset, outputs.total

    async def resolve(self, urls):
        txos = (await self._inflate_outputs(self.network.resolve(urls)))[0]
        assert len(urls) == len(txos), "Mismatch between urls requested for resolve and responses received."
        result = {}
        for url, txo in zip(urls, txos):
            if txo and URL.parse(url).has_stream_in_channel:
                if not txo.channel or not txo.is_signed_by(txo.channel, self):
                    txo = None
            if txo:
                result[url] = txo
            else:
                result[url] = {'error': f'{url} did not resolve to a claim'}
        return result

    async def claim_search(self, **kwargs) -> Tuple[List[Output], int, int]:
        return await self._inflate_outputs(self.network.claim_search(**kwargs))

    async def get_claim_by_claim_id(self, claim_id) -> Output:
        for claim in (await self.claim_search(claim_id=claim_id))[0]:
            return claim

    async def start(self):
        await super().start()
        await asyncio.gather(*(a.maybe_migrate_certificates() for a in self.accounts))
        await asyncio.gather(*(a.save_max_gap() for a in self.accounts))
        await self._report_state()

    async def _report_state(self):
        try:
            for account in self.accounts:
                balance = dewies_to_lbc(await account.get_balance())
                channel_count = await account.get_channel_count()
                claim_count = await account.get_claim_count()
                if isinstance(account.receiving, SingleKey):
                    log.info("Loaded single key account %s with %s LBC. "
                             "%d channels, %d certificates and %d claims",
                             account.id, balance, channel_count, len(account.channel_keys), claim_count)
                else:
                    total_receiving = len((await account.receiving.get_addresses()))
                    total_change = len((await account.change.get_addresses()))
                    log.info("Loaded account %s with %s LBC, %d receiving addresses (gap: %d), "
                             "%d change addresses (gap: %d), %d channels, %d certificates and %d claims. ",
                             account.id, balance, total_receiving, account.receiving.gap, total_change,
                             account.change.gap, channel_count, len(account.channel_keys), claim_count)
        except:
            log.exception(
                'Failed to display wallet state, please file issue '
                'for this bug along with the traceback you see below:')

    @staticmethod
    def constraint_spending_utxos(constraints):
        constraints.update({'is_claim': 0, 'is_update': 0, 'is_support': 0})

    def get_utxos(self, **constraints):
        self.constraint_spending_utxos(constraints)
        return super().get_utxos(**constraints)

    def get_utxo_count(self, **constraints):
        self.constraint_spending_utxos(constraints)
        return super().get_utxo_count(**constraints)

    def get_claims(self, **constraints):
        self.constraint_account_or_all(constraints)
        return self.db.get_claims(**constraints)

    def get_claim_count(self, **constraints):
        self.constraint_account_or_all(constraints)
        return self.db.get_claim_count(**constraints)

    def get_streams(self, **constraints):
        self.constraint_account_or_all(constraints)
        return self.db.get_streams(**constraints)

    def get_stream_count(self, **constraints):
        self.constraint_account_or_all(constraints)
        return self.db.get_stream_count(**constraints)

    def get_channels(self, **constraints):
        self.constraint_account_or_all(constraints)
        return self.db.get_channels(**constraints)

    def get_channel_count(self, **constraints):
        self.constraint_account_or_all(constraints)
        return self.db.get_channel_count(**constraints)

    def get_supports(self, **constraints):
        self.constraint_account_or_all(constraints)
        return self.db.get_supports(**constraints)

    def get_support_count(self, **constraints):
        self.constraint_account_or_all(constraints)
        return self.db.get_support_count(**constraints)

    async def get_transaction_history(self, **constraints):
        self.constraint_account_or_all(constraints)
        txs = await self.db.get_transactions(**constraints)
        headers = self.headers
        history = []
        for tx in txs:
            ts = headers[tx.height]['timestamp'] if tx.height > 0 else None
            item = {
                'txid': tx.id,
                'timestamp': ts,
                'date': datetime.fromtimestamp(ts).isoformat(' ')[:-3] if tx.height > 0 else None,
                'confirmations': (headers.height+1) - tx.height if tx.height > 0 else 0,
                'claim_info': [],
                'update_info': [],
                'support_info': [],
                'abandon_info': []
            }
            is_my_inputs = all([txi.is_my_account for txi in tx.inputs])
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
                    'address': txo.get_address(self),
                    'balance_delta': dewies_to_lbc(-txo.amount),
                    'amount': dewies_to_lbc(txo.amount),
                    'claim_id': txo.claim_id,
                    'claim_name': txo.claim_name,
                    'nout': txo.position
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
                            'nout': txo.position
                        })
                else:  # someone sent us their claim
                    item['update_info'].append({
                        'address': txo.get_address(self),
                        'balance_delta': dewies_to_lbc(0),
                        'amount': dewies_to_lbc(txo.amount),
                        'claim_id': txo.claim_id,
                        'claim_name': txo.claim_name,
                        'nout': txo.position
                    })
            for txo in tx.my_support_outputs:
                item['support_info'].append({
                    'address': txo.get_address(self),
                    'balance_delta': dewies_to_lbc(txo.amount if not is_my_inputs else -txo.amount),
                    'amount': dewies_to_lbc(txo.amount),
                    'claim_id': txo.claim_id,
                    'claim_name': txo.claim_name,
                    'is_tip': not is_my_inputs,
                    'nout': txo.position
                })
            if is_my_inputs:
                for txo in tx.other_support_outputs:
                    item['support_info'].append({
                        'address': txo.get_address(self),
                        'balance_delta': dewies_to_lbc(-txo.amount),
                        'amount': dewies_to_lbc(txo.amount),
                        'claim_id': txo.claim_id,
                        'claim_name': txo.claim_name,
                        'is_tip': is_my_inputs,
                        'nout': txo.position
                    })
            for txo in tx.my_abandon_outputs:
                item['abandon_info'].append({
                    'address': txo.get_address(self),
                    'balance_delta': dewies_to_lbc(txo.amount),
                    'amount': dewies_to_lbc(txo.amount),
                    'claim_id': txo.claim_id,
                    'claim_name': txo.claim_name,
                    'nout': txo.position
                })
            history.append(item)
        return history

    def get_transaction_history_count(self, **constraints):
        self.constraint_account_or_all(constraints)
        return self.db.get_transaction_count(**constraints)


class TestNetLedger(MainNetLedger):
    network_name = 'testnet'
    pubkey_address_prefix = bytes((111,))
    script_address_prefix = bytes((196,))
    extended_public_key_prefix = unhexlify('043587cf')
    extended_private_key_prefix = unhexlify('04358394')


class RegTestLedger(MainNetLedger):
    network_name = 'regtest'
    headers_class = UnvalidatedHeaders
    pubkey_address_prefix = bytes((111,))
    script_address_prefix = bytes((196,))
    extended_public_key_prefix = unhexlify('043587cf')
    extended_private_key_prefix = unhexlify('04358394')

    max_target = 0x7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = '6e3fcf1299d4ec5d79c3a4c91d624a4acf9e2e173d95a1a0504f677669687556'
    genesis_bits = 0x207fffff
    target_timespan = 1
