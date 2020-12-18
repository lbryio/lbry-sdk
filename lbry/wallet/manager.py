import os
import stat
import json
import asyncio
import logging
from typing import Optional, Dict

from lbry.db import Database
from lbry.blockchain.dewies import dict_values_to_lbc

from .wallet import Wallet
from .account import SingleKey, HierarchicalDeterministic

log = logging.getLogger(__name__)


class WalletManager:

    def __init__(self, db: Database):
        self.db = db
        self.ledger = db.ledger
        self.wallets: Dict[str, Wallet] = {}
        if self.ledger.conf.wallet_storage == "file":
            self.storage = FileWallet(self.db, self.ledger.conf.wallet_dir)
        elif self.ledger.conf.wallet_storage == "database":
            self.storage = DatabaseWallet(self.db)
        else:
            raise Exception(f"Unknown wallet storage format: {self.ledger.conf.wallet_storage}")

    def __len__(self):
        return self.wallets.__len__()

    def __iter__(self):
        return self.wallets.values().__iter__()

    def __getitem__(self, wallet_id: str) -> Wallet:
        try:
            return self.wallets[wallet_id]
        except KeyError:
            raise ValueError(f"Couldn't find wallet: {wallet_id}.")

    async def generate_addresses(self):
        for wallet in self.wallets.values():
            await wallet.generate_addresses()

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

    async def open(self):
        await self.storage.prepare()
        await self.initialize()

    async def close(self):
        pass

    async def initialize(self):
        for wallet_id in self.ledger.conf.wallets:
            if wallet_id in self.wallets:
                log.warning("Ignoring duplicate wallet_id in config: %s", wallet_id)
                continue
            await self.load(wallet_id)
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

    async def load(self, wallet_id: str) -> Optional[Wallet]:
        wallet = await self.storage.get(wallet_id)
        if wallet is not None:
            return self.add(wallet)

    async def create(
        self, wallet_id: str, name: str = "",
        create_account=False, language="en", single_key=False
    ) -> Wallet:
        if wallet_id in self.wallets:
            raise Exception(f"Wallet with id '{wallet_id}' is already loaded and cannot be created.")
        if await self.storage.exists(wallet_id):
            raise Exception(f"Wallet '{wallet_id}' already exists, use 'wallet_add' to load wallet.")
        wallet = Wallet(wallet_id, self.db, name)
        if create_account:
            await wallet.accounts.generate(language=language, address_generator={
                'name': SingleKey.name if single_key else HierarchicalDeterministic.name
            })
        await self.storage.save(wallet)
        return self.add(wallet)

    def add(self, wallet: Wallet) -> Wallet:
        self.wallets[wallet.id] = wallet
        wallet.on_change.listen(lambda _: self.storage.save(wallet))
        return wallet

    def remove(self, wallet_id: str) -> Wallet:
        return self.wallets.pop(wallet_id)

    async def _report_state(self):
        try:
            for wallet in self.wallets.values():
                for account in wallet.accounts:
                    balance = dict_values_to_lbc(await account.get_balance(include_claims=True))
                    _, channel_count = await account.get_channels(limit=1)
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
                'for this bug along with the traceback you see below:'
            )


class WalletStorage:

    async def prepare(self):
        raise NotImplementedError

    async def exists(self, wallet_id: str) -> bool:
        raise NotImplementedError

    async def get(self, wallet_id: str) -> Wallet:
        raise NotImplementedError

    async def save(self, wallet: Wallet):
        raise NotImplementedError


class FileWallet(WalletStorage):

    def __init__(self, db, wallet_dir):
        self.db = db
        self.wallet_dir = wallet_dir

    def get_wallet_path(self, wallet_id: str):
        return os.path.join(self.wallet_dir, wallet_id)

    async def prepare(self):
        await asyncio.get_running_loop().run_in_executor(
            None, self.sync_ensure_wallets_directory_exists
        )

    def sync_ensure_wallets_directory_exists(self):
        if not os.path.exists(self.wallet_dir):
            os.mkdir(self.wallet_dir)

    async def exists(self, wallet_id: str) -> bool:
        return os.path.exists(self.get_wallet_path(wallet_id))

    async def get(self, wallet_id: str) -> Wallet:
        wallet_dict = await asyncio.get_running_loop().run_in_executor(
            None, self.sync_read, wallet_id
        )
        if wallet_dict is not None:
            return await Wallet.from_dict(wallet_id, wallet_dict, self.db)

    def sync_read(self, wallet_id):
        try:
            with open(self.get_wallet_path(wallet_id), 'r') as f:
                json_data = f.read()
                return json.loads(json_data)
        except FileNotFoundError:
            return None

    async def save(self, wallet: Wallet):
        return await asyncio.get_running_loop().run_in_executor(
            None, self.sync_write, wallet
        )

    def sync_write(self, wallet: Wallet):
        temp_path = os.path.join(self.wallet_dir, f".tmp.{os.path.basename(wallet.id)}")
        with open(temp_path, "w") as f:
            f.write(wallet.to_serialized())
            f.flush()
            os.fsync(f.fileno())

        wallet_path = self.get_wallet_path(wallet.id)
        if os.path.exists(wallet_path):
            mode = os.stat(wallet_path).st_mode
        else:
            mode = stat.S_IREAD | stat.S_IWRITE
        try:
            os.rename(temp_path, wallet_path)
        except Exception:  # pylint: disable=broad-except
            os.remove(wallet_path)
            os.rename(temp_path, wallet_path)
        os.chmod(wallet_path, mode)


class DatabaseWallet(WalletStorage):

    def __init__(self, db: 'Database'):
        self.db = db

    async def prepare(self):
        pass

    async def exists(self, wallet_id: str) -> bool:
        return await self.db.has_wallet(wallet_id)

    async def get(self, wallet_id: str) -> Wallet:
        data = await self.db.get_wallet(wallet_id)
        if data:
            wallet_dict = json.loads(data['data'])
            if wallet_dict is not None:
                return await Wallet.from_dict(wallet_id, wallet_dict, self.db)

    async def save(self, wallet: Wallet):
        await self.db.add_wallet(
            wallet.id, wallet.to_serialized()
        )
