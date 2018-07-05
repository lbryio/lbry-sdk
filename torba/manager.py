from typing import List, Dict, Type
from twisted.internet import defer

from torba.baseledger import BaseLedger, LedgerRegistry
from torba.wallet import Wallet, WalletStorage


class WalletManager(object):

    def __init__(self, wallets=None, ledgers=None):
        # type: (List[Wallet], Dict[Type[BaseLedger],BaseLedger]) -> None
        self.wallets = wallets or []
        self.ledgers = ledgers or {}
        self.running = False

    @classmethod
    def from_config(cls, config):  # type: (Dict) -> WalletManager
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

    @defer.inlineCallbacks
    def get_balance(self):
        balances = {}
        for ledger in self.ledgers.values():
            for account in ledger.accounts:
                balances.setdefault(ledger.get_id(), 0)
                balances[ledger.get_id()] += yield account.get_balance()
        defer.returnValue(balances)

    @property
    def default_wallet(self):
        for wallet in self.wallets:
            return wallet

    @property
    def default_account(self):
        for wallet in self.wallets:
            return wallet.default_account

    @defer.inlineCallbacks
    def start(self):
        self.running = True
        yield defer.DeferredList([
            l.start() for l in self.ledgers.values()
        ])

    @defer.inlineCallbacks
    def stop(self):
        yield defer.DeferredList([
            l.stop() for l in self.ledgers.values()
        ])
        self.running = False
