import stat
import json
import os
from typing import List, Dict

from torba.baseaccount import BaseAccount
from torba.baseledger import LedgerRegistry, BaseLedger


def inflate_ledger(manager, ledger_id, ledger_dict):
    # type: ('WalletManager', str, Dict) -> BaseLedger
    ledger_class = LedgerRegistry.get_ledger_class(ledger_id)
    ledger = manager.get_or_create_ledger(ledger_id)
    return ledger_class(ledger, **ledger_dict)


class Wallet:
    """ The primary role of Wallet is to encapsulate a collection
        of accounts (seed/private keys) and the spending rules / settings
        for the coins attached to those accounts. Wallets are represented
        by physical files on the filesystem.
    """

    def __init__(self, name='Wallet', ledgers=None, accounts=None, storage=None):
        self.name = name
        self.ledgers = ledgers or []  # type: List[BaseLedger]
        self.accounts = accounts or []  # type: List[BaseAccount]
        self.storage = storage or WalletStorage()

    def generate_account(self, ledger):  # type: (BaseLedger) -> Account
        account = ledger.account_class.generate(ledger, u'torba')
        self.accounts.append(account)
        return account

    @classmethod
    def from_storage(cls, storage, manager):  # type: (WalletStorage, 'WalletManager') -> Wallet
        json_dict = storage.read()

        ledgers = {}
        for ledger_id, ledger_dict in json_dict.get('ledgers', {}).items():
            ledgers[ledger_id] = inflate_ledger(manager, ledger_id, ledger_dict)

        accounts = []
        for account_dict in json_dict.get('accounts', []):
            ledger_id = account_dict['ledger']
            ledger = ledgers.get(ledger_id)
            if ledger is None:
                ledger = ledgers[ledger_id] = inflate_ledger(manager, ledger_id, {})
            account = ledger.account_class.from_dict(ledger, account_dict)
            accounts.append(account)

        return cls(
            name=json_dict.get('name', 'Wallet'),
            ledgers=list(ledgers.values()),
            accounts=accounts,
            storage=storage
        )

    def to_dict(self):
        return {
            'name': self.name,
            'ledgers': {c.get_id(): {} for c in self.ledgers},
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
