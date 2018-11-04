import asyncio
import logging
from typing import Type, MutableSequence, MutableMapping

from torba.client.baseledger import BaseLedger, LedgerRegistry
from torba.client.wallet import Wallet, WalletStorage

log = logging.getLogger(__name__)


class BaseWalletManager:

    def __init__(self, wallets: MutableSequence[Wallet] = None,
                 ledgers: MutableMapping[Type[BaseLedger], BaseLedger] = None) -> None:
        self.wallets = wallets or []
        self.ledgers = ledgers or {}
        self.running = False

    @classmethod
    def from_config(cls, config: dict) -> 'BaseWalletManager':
        manager = cls()
        for ledger_id, ledger_config in config.get('ledgers', {}).items():
            manager.get_or_create_ledger(ledger_id, ledger_config)
        for wallet_path in config.get('wallets', []):
            wallet_storage = WalletStorage(wallet_path)
            wallet = Wallet.from_storage(wallet_storage, manager)
            manager.wallets.append(wallet)
        return manager

    def get_or_create_ledger(self, ledger_id, ledger_config=None):
        ledger_class = LedgerRegistry.get_ledger_class(ledger_id)
        ledger = self.ledgers.get(ledger_class)
        if ledger is None:
            ledger = ledger_class(ledger_config or {})
            self.ledgers[ledger_class] = ledger
        return ledger

    def import_wallet(self, path):
        storage = WalletStorage(path)
        wallet = Wallet.from_storage(storage, self)
        self.wallets.append(wallet)
        return wallet

    async def get_detailed_accounts(self, **kwargs):
        ledgers = {}
        for i, account in enumerate(self.accounts):
            details = await account.get_details(**kwargs)
            details['is_default_account'] = i == 0
            ledger_id = account.ledger.get_id()
            ledgers.setdefault(ledger_id, [])
            ledgers[ledger_id].append(details)
        return ledgers

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
            for account in wallet.accounts:
                yield account

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
