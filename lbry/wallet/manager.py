import os
import json
import typing
import logging
import asyncio
from binascii import unhexlify
from decimal import Decimal
from typing import List, Type, MutableSequence, MutableMapping, Optional

from lbry.error import KeyFeeAboveMaxAllowedError
from lbry.conf import Config

from .account import Account
from lbry.blockchain.dewies import dewies_to_lbc
from lbry.blockchain.ledger import Ledger
from lbry.db import Database
from lbry.blockchain.ledger import Ledger
from lbry.blockchain.transaction import Transaction, Output

from .wallet import Wallet, WalletStorage, ENCRYPT_ON_DISK


log = logging.getLogger(__name__)


class WalletManager:

    def __init__(self, ledger: Ledger, db: Database,
                 wallets: MutableSequence[Wallet] = None,
                 ledgers: MutableMapping[Type[Ledger], Ledger] = None) -> None:
        self.ledger = ledger
        self.db = db
        self.wallets = wallets or []
        self.ledgers = ledgers or {}
        self.running = False
        self.config: Optional[Config] = None

    async def open(self):
        conf = self.ledger.conf

        wallets_directory = os.path.join(conf.wallet_dir, 'wallets')
        if not os.path.exists(wallets_directory):
            os.mkdir(wallets_directory)

        for wallet_file in conf.wallets:
            wallet_path = os.path.join(wallets_directory, wallet_file)
            wallet_storage = WalletStorage(wallet_path)
            wallet = Wallet.from_storage(self.ledger, self.db, wallet_storage)
            self.wallets.append(wallet)

        self.ledger.coin_selection_strategy = self.ledger.conf.coin_selection_strategy
        default_wallet = self.default_wallet
        if default_wallet.default_account is None:
            log.info('Wallet at %s is empty, generating a default account.', default_wallet.id)
            default_wallet.generate_account()
            default_wallet.save()
        if default_wallet.is_locked and default_wallet.preferences.get(ENCRYPT_ON_DISK) is None:
            default_wallet.preferences[ENCRYPT_ON_DISK] = True
            default_wallet.save()

    def import_wallet(self, path):
        storage = WalletStorage(path)
        wallet = Wallet.from_storage(self.ledger, self.db, storage)
        self.wallets.append(wallet)
        return wallet

    @property
    def default_wallet(self):
        for wallet in self.wallets:
            return wallet

    @property
    def default_account(self):
        for wallet in self.wallets:
            return wallet.default_account

    @property
    def accounts(self):
        for wallet in self.wallets:
            yield from wallet.accounts

    async def start(self):
        self.running = True
        await asyncio.gather(*(
            l.start() for l in self.ledgers.values()
        ))

    async def stop(self):
        await asyncio.gather(*(
            l.stop() for l in self.ledgers.values()
        ))
        self.running = False

    def get_wallet_or_default(self, wallet_id: Optional[str]) -> Wallet:
        if wallet_id is None:
            return self.default_wallet
        return self.get_wallet_or_error(wallet_id)

    def get_wallet_or_error(self, wallet_id: str) -> Wallet:
        for wallet in self.wallets:
            if wallet.id == wallet_id:
                return wallet
        raise ValueError(f"Couldn't find wallet: {wallet_id}.")

    @staticmethod
    def get_balance(wallet):
        accounts = wallet.accounts
        if not accounts:
            return 0
        return accounts[0].ledger.db.get_balance(wallet=wallet, accounts=accounts)

    def check_locked(self):
        return self.default_wallet.is_locked

    async def reset(self):
        self.ledger.config = {
            'auto_connect': True,
            'default_servers': self.config.lbryum_servers,
            'data_path': self.config.wallet_dir,
        }
        await self.ledger.stop()
        await self.ledger.start()

    async def get_best_blockhash(self):
        if len(self.ledger.headers) <= 0:
            return self.ledger.genesis_hash
        return (await self.ledger.headers.hash(self.ledger.headers.height)).decode()

    def get_unused_address(self):
        return self.default_account.receiving.get_or_create_usable_address()

    async def get_transaction(self, tx_hash: bytes):
        tx = await self.db.get_transaction(tx_hash=tx_hash)
        if tx:
            return tx
        try:
            raw, merkle = await self.ledger.network.get_transaction_and_merkle(tx_hash)
        except CodeMessageError as e:
            if 'No such mempool or blockchain transaction.' in e.message:
                return {'success': False, 'code': 404, 'message': 'transaction not found'}
            return {'success': False, 'code': e.code, 'message': e.message}
        height = merkle.get('block_height')
        tx = Transaction(unhexlify(raw), height=height)
        if height and height > 0:
            await self.ledger.maybe_verify_transaction(tx, height, merkle)
        return tx

