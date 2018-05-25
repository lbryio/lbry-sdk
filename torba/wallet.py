import stat
import json
import os
from typing import List, Dict

from torba.account import Account
from torba.basecoin import CoinRegistry, BaseCoin
from torba.baseledger import BaseLedger


def inflate_coin(manager, coin_id, coin_dict):
    # type: ('WalletManager', str, Dict) -> BaseCoin
    coin_class = CoinRegistry.get_coin_class(coin_id)
    ledger = manager.get_or_create_ledger(coin_id)
    return coin_class(ledger, **coin_dict)


class Wallet:
    """ The primary role of Wallet is to encapsulate a collection
        of accounts (seed/private keys) and the spending rules / settings
        for the coins attached to those accounts. Wallets are represented
        by physical files on the filesystem.
    """

    def __init__(self, name='Wallet', coins=None, accounts=None, storage=None):
        self.name = name
        self.coins = coins or []  # type: List[BaseCoin]
        self.accounts = accounts or []  # type: List[Account]
        self.storage = storage or WalletStorage()

    def get_or_create_coin(self, ledger, coin_dict=None):  # type: (BaseLedger, Dict) -> BaseCoin
        for coin in self.coins:
            if coin.__class__ is ledger.coin_class:
                return coin
        coin = ledger.coin_class(ledger, **(coin_dict or {}))
        self.coins.append(coin)
        return coin

    def generate_account(self, ledger):  # type: (BaseLedger) -> Account
        coin = self.get_or_create_coin(ledger)
        account = Account.generate(coin, u'torba')
        self.accounts.append(account)
        return account

    @classmethod
    def from_storage(cls, storage, manager):  # type: (WalletStorage, 'WalletManager') -> Wallet
        json_dict = storage.read()

        coins = {}
        for coin_id, coin_dict in json_dict.get('coins', {}).items():
            coins[coin_id] = inflate_coin(manager, coin_id, coin_dict)

        accounts = []
        for account_dict in json_dict.get('accounts', []):
            coin_id = account_dict['coin']
            coin = coins.get(coin_id)
            if coin is None:
                coin = coins[coin_id] = inflate_coin(manager, coin_id, {})
            account = Account.from_dict(coin, account_dict)
            accounts.append(account)

        return cls(
            name=json_dict.get('name', 'Wallet'),
            coins=list(coins.values()),
            accounts=accounts,
            storage=storage
        )

    def to_dict(self):
        return {
            'name': self.name,
            'coins': {c.get_id(): c.to_dict() for c in self.coins},
            'accounts': [a.to_dict() for a in self.accounts]
        }

    def save(self):
        self.storage.write(self.to_dict())

    @property
    def default_account(self):
        for account in self.accounts:
            return account

    def get_account_private_key_for_address(self, address):
        for account in self.accounts:
            private_key = account.get_private_key_for_address(address)
            if private_key is not None:
                return account, private_key


class WalletStorage:

    LATEST_VERSION = 2

    DEFAULT = {
        'version': LATEST_VERSION,
        'name': 'Wallet',
        'coins': {},
        'accounts': []
    }

    def __init__(self, path=None, default=None):
        self.path = path
        self._default = default or self.DEFAULT.copy()

    @property
    def default(self):
        return self._default.copy()

    def read(self):
        if self.path and os.path.exists(self.path):
            with open(self.path, "r") as f:
                json_data = f.read()
                json_dict = json.loads(json_data)
                if json_dict.get('version') == self.LATEST_VERSION and \
                        set(json_dict) == set(self._default):
                    return json_dict
                else:
                    return self.upgrade(json_dict)
        else:
            return self.default

    @classmethod
    def upgrade(cls, json_dict):
        json_dict = json_dict.copy()

        def _rename_property(old, new):
            if old in json_dict:
                json_dict[new] = json_dict[old]
                del json_dict[old]

        version = json_dict.pop('version', -1)

        if version == 1:  # upgrade from version 1 to version 2
            _rename_property('addr_history', 'history')
            _rename_property('use_encryption', 'encrypted')
            _rename_property('gap_limit', 'gap_limit_for_receiving')

        upgraded = cls.DEFAULT
        upgraded.update(json_dict)
        return json_dict

    def write(self, json_dict):

        json_data = json.dumps(json_dict, indent=4, sort_keys=True)
        if self.path is None:
            return json_data

        temp_path = "%s.tmp.%s" % (self.path, os.getpid())
        with open(temp_path, "w") as f:
            f.write(json_data)
            f.flush()
            os.fsync(f.fileno())

        if os.path.exists(self.path):
            mode = os.stat(self.path).st_mode
        else:
            mode = stat.S_IREAD | stat.S_IWRITE
        try:
            os.rename(temp_path, self.path)
        except:
            os.remove(self.path)
            os.rename(temp_path, self.path)
        os.chmod(self.path, mode)
