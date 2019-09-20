import os
import stat
import json
import zlib
import typing
from typing import List, Sequence, MutableSequence, Optional
from hashlib import sha256
from operator import attrgetter
from torba.client.hash import better_aes_encrypt, better_aes_decrypt

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

    @property
    def id(self):
        if self.storage.path:
            return os.path.basename(self.storage.path)
        return self.name

    def add_account(self, account: 'baseaccount.BaseAccount'):
        self.accounts.append(account)

    def generate_account(self, ledger: 'baseledger.BaseLedger') -> 'baseaccount.BaseAccount':
        return ledger.account_class.generate(ledger, self)

    @property
    def default_account(self) -> Optional['baseaccount.BaseAccount']:
        for account in self.accounts:
            return account
        return None

    def get_account_or_default(self, account_id: str) -> Optional['baseaccount.BaseAccount']:
        if account_id is None:
            return self.default_account
        return self.get_account_or_error(account_id)

    def get_account_or_error(self, account_id: str) -> 'baseaccount.BaseAccount':
        for account in self.accounts:
            if account.id == account_id:
                return account
        raise ValueError(f"Couldn't find account: {account_id}.")

    def get_accounts_or_all(self, account_ids: List[str]) -> Sequence['baseaccount.BaseAccount']:
        return [
            self.get_account_or_error(account_id)
            for account_id in account_ids
        ] if account_ids else self.accounts

    async def get_detailed_accounts(self, **kwargs):
        ledgers = {}
        for i, account in enumerate(self.accounts):
            details = await account.get_details(**kwargs)
            details['is_default'] = i == 0
            ledger_id = account.ledger.get_id()
            ledgers.setdefault(ledger_id, [])
            ledgers[ledger_id].append(details)
        return ledgers

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
    def hash(self) -> bytes:
        h = sha256()
        for account in sorted(self.accounts, key=attrgetter('id')):
            h.update(account.hash)
        return h.digest()

    def pack(self, password):
        new_data = json.dumps(self.to_dict())
        new_data_compressed = zlib.compress(new_data.encode())
        return better_aes_encrypt(password, new_data_compressed)

    @classmethod
    def unpack(cls, password, encrypted):
        decrypted = better_aes_decrypt(password, encrypted)
        decompressed = zlib.decompress(decrypted)
        return json.loads(decompressed)


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
