from decimal import Decimal
from typing import List, Dict, Type
from twisted.internet import defer

from torba.baseledger import BaseLedger, LedgerRegistry
from torba.wallet import Wallet, WalletStorage
from torba.constants import COIN


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
    def get_balances(self, confirmations=6):
        balances = {}
        for i, ledger in enumerate(self.ledgers.values()):
            ledger_balances = balances[ledger.get_id()] = []
            for j, account in enumerate(ledger.accounts):
                satoshis = yield account.get_balance(confirmations)
                ledger_balances.append({
                    'account': account.name,
                    'coins': round(Decimal(satoshis) / COIN, 2),
                    'satoshis': satoshis,
                    'is_default_account': i == 0 and j == 0
                })
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
