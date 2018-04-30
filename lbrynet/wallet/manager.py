import functools
from typing import List, Dict, Type
from twisted.internet import defer

from lbrynet.wallet.account import AccountsView
from lbrynet.wallet.basecoin import CoinRegistry
from lbrynet.wallet.baseledger import BaseLedger
from lbrynet.wallet.wallet import Wallet, WalletStorage


class WalletManager:

    def __init__(self, wallets=None, ledgers=None):
        self.wallets = wallets or []  # type: List[Wallet]
        self.ledgers = ledgers or {}  # type: Dict[Type[BaseLedger],BaseLedger]
        self.running = False

    @classmethod
    def from_config(cls, config):
        wallets = []
        manager = cls(wallets)
        for coin_id, ledger_config in config.get('ledgers', {}).items():
            manager.get_or_create_ledger(coin_id, ledger_config)
        for wallet_path in config.get('wallets', []):
            wallet_storage = WalletStorage(wallet_path)
            wallet = Wallet.from_storage(wallet_storage, manager)
            wallets.append(wallet)
        return manager

    def get_or_create_ledger(self, coin_id, ledger_config=None):
        coin_class = CoinRegistry.get_coin_class(coin_id)
        ledger_class = coin_class.ledger_class
        ledger = self.ledgers.get(ledger_class)
        if ledger is None:
            ledger = ledger_class(self.get_accounts_view(coin_class), ledger_config or {})
            self.ledgers[ledger_class] = ledger
        return ledger

    @property
    def default_wallet(self):
        for wallet in self.wallets:
            return wallet

    @property
    def default_account(self):
        for wallet in self.wallets:
            return wallet.default_account

    def get_accounts(self, coin_class):
        for wallet in self.wallets:
            for account in wallet.accounts:
                if account.coin.__class__ is coin_class:
                    yield account

    def get_accounts_view(self, coin_class):
        return AccountsView(
            functools.partial(self.get_accounts, coin_class)
        )

    def create_wallet(self, path, coin_class):
        storage = WalletStorage(path)
        wallet = Wallet.from_storage(storage, self)
        self.wallets.append(wallet)
        self.create_account(wallet, coin_class)
        return wallet

    def create_account(self, wallet, coin_class):
        ledger = self.get_or_create_ledger(coin_class.get_id())
        return wallet.generate_account(ledger)

    @defer.inlineCallbacks
    def start_ledgers(self):
        self.running = True
        yield defer.DeferredList([
            l.start() for l in self.ledgers.values()
        ])

    @defer.inlineCallbacks
    def stop_ledgers(self):
        yield defer.DeferredList([
            l.stop() for l in self.ledgers.values()
        ])
        self.running = False
