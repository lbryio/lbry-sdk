import functools
from typing import List, Dict, Type
from twisted.internet import defer

from torba.account import AccountsView
from torba.basecoin import CoinRegistry
from torba.baseledger import BaseLedger
from torba.basetransaction import BaseTransaction, NULL_HASH
from torba.coinselection import CoinSelector
from torba.constants import COIN
from torba.wallet import Wallet, WalletStorage


class BaseWalletManager(object):

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
            ledger = self.create_ledger(ledger_class, self.get_accounts_view(coin_class), ledger_config or {})
            self.ledgers[ledger_class] = ledger
        return ledger

    def create_ledger(self, ledger_class, accounts, config):
        return ledger_class(accounts, config)

    @defer.inlineCallbacks
    def get_balance(self):
        balances = {}
        for ledger in self.ledgers:
            for account in self.get_accounts(ledger.coin_class):
                balances.setdefault(ledger.coin_class.name, 0)
                balances[ledger.coin_class.name] += yield account.get_balance()
        defer.returnValue(balances)

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

    def send_amount_to_address(self, amount, address):
        amount = int(amount * COIN)

        account = self.default_account
        coin = account.coin
        ledger = coin.ledger
        tx_class = ledger.transaction_class  # type: BaseTransaction
        in_class, out_class = tx_class.input_class, tx_class.output_class

        estimators = [
            txo.get_estimator(coin) for txo in account.get_unspent_utxos()
        ]
        tx_class.create()

        cost_of_output = coin.get_input_output_fee(
            out_class.pay_pubkey_hash(COIN, NULL_HASH)
        )

        selector = CoinSelector(estimators, amount, cost_of_output)
        spendables = selector.select()
        if not spendables:
            raise ValueError('Not enough funds to cover this transaction.')

        outputs = [
            out_class.pay_pubkey_hash(amount, coin.address_to_hash160(address))
        ]

        spent_sum = sum(s.effective_amount for s in spendables)
        if spent_sum > amount:
            change_address = account.get_least_used_change_address()
            change_hash160 = coin.address_to_hash160(change_address)
            outputs.append(out_class.pay_pubkey_hash(spent_sum - amount, change_hash160))

        tx = tx_class() \
            .add_inputs([s.txi for s in spendables]) \
            .add_outputs(outputs) \
            .sign(account)

        return tx
