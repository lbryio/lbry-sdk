import stat
import json
import os
import typing
from typing import Sequence, MutableSequence

if typing.TYPE_CHECKING:
    from torba.client import basemanager, baseaccount, baseledger


class Wallet:
    """ The primary role of Wallet is to encapsulate a collection
        of accounts (seed/private keys) and the spending rules / settings
        for the coins attached to those accounts. Wallets are represented
        by physical files on the filesystem.
    """

    def __init__(self, name: str = 'Wallet', accounts: MutableSequence['baseaccount.BaseAccount'] = None,
                 storage: 'WalletStorage' = None) -> None:
        self.name = name
        self.accounts = accounts or []
        self.storage = storage or WalletStorage()

    def add_account(self, account):
        self.accounts.append(account)

    def generate_account(self, ledger: 'baseledger.BaseLedger') -> 'baseaccount.BaseAccount':
        return ledger.account_class.generate(ledger, self)

    @classmethod
    def from_storage(cls, storage: 'WalletStorage', manager: 'basemanager.BaseWalletManager') -> 'Wallet':
        json_dict = storage.read()
        wallet = cls(
            name=json_dict.get('name', 'Wallet'),
            storage=storage
        )
        account_dicts: Sequence[dict] = json_dict.get('accounts', [])
        for account_dict in account_dicts:
            ledger = manager.get_or_create_ledger(account_dict['ledger'])
            ledger.account_class.from_dict(ledger, wallet, account_dict)
        return wallet

    def to_dict(self):
        return {
            'version': WalletStorage.LATEST_VERSION,
            'name': self.name,
            'accounts': [a.to_dict() for a in self.accounts]
        }

    def save(self):
        self.storage.write(self.to_dict())

    @property
    def default_account(self):
        for account in self.accounts:
            return account


class WalletStorage:

    LATEST_VERSION = 1

    def __init__(self, path=None, default=None):
        self.path = path
        self._default = default or {
            'version': self.LATEST_VERSION,
            'name': 'My Wallet',
            'accounts': []
        }

    def read(self):
        if self.path and os.path.exists(self.path):
            with open(self.path, 'r') as f:
                json_data = f.read()
                json_dict = json.loads(json_data)
                if json_dict.get('version') == self.LATEST_VERSION and \
                        set(json_dict) == set(self._default):
                    return json_dict
                else:
                    return self.upgrade(json_dict)
        else:
            return self._default.copy()

    def upgrade(self, json_dict):
        json_dict = json_dict.copy()
        version = json_dict.pop('version', -1)
        if version == -1:
            pass
        upgraded = self._default.copy()
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
        except Exception:  # pylint: disable=broad-except
            os.remove(self.path)
            os.rename(temp_path, self.path)
        os.chmod(self.path, mode)
