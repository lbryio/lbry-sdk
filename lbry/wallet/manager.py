import os
import asyncio
import logging
from typing import Optional, Dict

from lbry.db import Database
from lbry.blockchain.ledger import Ledger

from .wallet import Wallet

log = logging.getLogger(__name__)


class WalletManager:

    def __init__(self, ledger: Ledger, db: Database):
        self.ledger = ledger
        self.db = db
        self.wallets: Dict[str, Wallet] = {}

    def __getitem__(self, wallet_id: str) -> Wallet:
        try:
            return self.wallets[wallet_id]
        except KeyError:
            raise ValueError(f"Couldn't find wallet: {wallet_id}.")

    @property
    def default(self) -> Optional[Wallet]:
        for wallet in self.wallets.values():
            return wallet

    def get_or_default(self, wallet_id: Optional[str]) -> Wallet:
        if wallet_id:
            return self[wallet_id]
        wallet = self.default
        if not wallet:
            raise ValueError("No wallets available.")
        return wallet

    def get_or_default_for_spending(self, wallet_id: Optional[str]) -> Wallet:
        wallet = self.get_or_default(wallet_id)
        if wallet.is_locked:
            raise ValueError("Cannot spend funds with locked wallet, unlock first.")
        return wallet

    @property
    def path(self):
        return os.path.join(self.ledger.conf.wallet_dir, 'wallets')

    def sync_ensure_path_exists(self):
        if not os.path.exists(self.path):
            os.mkdir(self.path)

    async def ensure_path_exists(self):
        await asyncio.get_running_loop().run_in_executor(
            None, self.sync_ensure_path_exists
        )

    async def load(self):
        wallets_directory = self.path
        for wallet_id in self.ledger.conf.wallets:
            if wallet_id in self.wallets:
                log.warning(f"Ignoring duplicate wallet_id in config: {wallet_id}")
                continue
            wallet_path = os.path.join(wallets_directory, wallet_id)
            if not os.path.exists(wallet_path):
                if not wallet_id == "default_wallet":  # we'll probably generate this wallet, don't show error
                    log.error(f"Could not load wallet, file does not exist: {wallet_path}")
                continue
            wallet = await Wallet.from_path(self.ledger, self.db, wallet_path)
            self.add(wallet)
        default_wallet = self.default
        if default_wallet is None:
            if self.ledger.conf.create_default_wallet:
                assert self.ledger.conf.wallets[0] == "default_wallet", (
                    "Requesting to generate the default wallet but the 'wallets' "
                    "config setting does not include 'default_wallet' as the first wallet."
                )
                await self.create(
                    self.ledger.conf.wallets[0], 'Wallet',
                    create_account=self.ledger.conf.create_default_account
                )
        elif not default_wallet.has_accounts and self.ledger.conf.create_default_account:
            await default_wallet.accounts.generate()

    def add(self, wallet: Wallet) -> Wallet:
        self.wallets[wallet.id] = wallet
        return wallet

    async def add_from_path(self, wallet_path) -> Wallet:
        wallet_id = os.path.basename(wallet_path)
        if wallet_id in self.wallets:
            existing = self.wallets.get(wallet_id)
            if existing.storage.path == wallet_path:
                raise Exception(f"Wallet '{wallet_id}' is already loaded.")
            raise Exception(
                f"Wallet '{wallet_id}' is already loaded from '{existing.storage.path}'"
                f" and cannot be loaded from '{wallet_path}'. Consider changing the wallet"
                f" filename to be unique in order to avoid conflicts."
            )
        wallet = await Wallet.from_path(self.ledger, self.db, wallet_path)
        return self.add(wallet)

    async def create(
            self, wallet_id: str, name: str,
            create_account=False, language='en', single_key=False) -> Wallet:
        if wallet_id in self.wallets:
            raise Exception(f"Wallet with id '{wallet_id}' is already loaded and cannot be created.")
        wallet_path = os.path.join(self.path, wallet_id)
        if os.path.exists(wallet_path):
            raise Exception(f"Wallet at path '{wallet_path}' already exists, use 'wallet_add' to load wallet.")
        wallet = await Wallet.create(
            self.ledger, self.db, wallet_path, name,
            create_account, language, single_key
        )
        return self.add(wallet)
