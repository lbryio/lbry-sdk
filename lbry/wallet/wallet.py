import os
import time
import stat
import json
import zlib
import typing
import logging
from typing import List, Sequence, MutableSequence, Optional
from collections import UserDict
from hashlib import sha256
from operator import attrgetter
from lbry.crypto.crypt import better_aes_encrypt, better_aes_decrypt
from lbry.error import InvalidPasswordError
from .account import Account

if typing.TYPE_CHECKING:
    from lbry.wallet.manager import WalletManager
    from lbry.wallet.ledger import Ledger


log = logging.getLogger(__name__)

ENCRYPT_ON_DISK = 'encrypt-on-disk'


class TimestampedPreferences(UserDict):

    def __init__(self, d: dict = None):
        super().__init__()
        if d is not None:
            self.data = d.copy()

    def __getitem__(self, key):
        return self.data[key]['value']

    def __setitem__(self, key, value):
        self.data[key] = {
            'value': value,
            'ts': int(time.time())
        }

    def __repr__(self):
        return repr(self.to_dict_without_ts())

    def to_dict_without_ts(self):
        return {
            key: value['value'] for key, value in self.data.items()
        }

    @property
    def hash(self):
        return sha256(json.dumps(self.data).encode()).digest()

    def merge(self, other: dict):
        for key, value in other.items():
            if key in self.data and value['ts'] < self.data[key]['ts']:
                continue
            self.data[key] = value


class Wallet:
    """ The primary role of Wallet is to encapsulate a collection
        of accounts (seed/private keys) and the spending rules / settings
        for the coins attached to those accounts. Wallets are represented
        by physical files on the filesystem.
    """

    preferences: TimestampedPreferences
    encryption_password: Optional[str]

    def __init__(self, name: str = 'Wallet', accounts: MutableSequence['Account'] = None,
                 storage: 'WalletStorage' = None, preferences: dict = None) -> None:
        self.name = name
        self.accounts = accounts or []
        self.storage = storage or WalletStorage()
        self.preferences = TimestampedPreferences(preferences or {})
        self.encryption_password = None
        self.id = self.get_id()

    def get_id(self):
        return os.path.basename(self.storage.path) if self.storage.path else self.name

    def add_account(self, account: 'Account'):
        self.accounts.append(account)

    def generate_account(self, ledger: 'Ledger') -> 'Account':
        return Account.generate(ledger, self)

    @property
    def default_account(self) -> Optional['Account']:
        for account in self.accounts:
            return account
        return None

    def get_account_or_default(self, account_id: str) -> Optional['Account']:
        if account_id is None:
            return self.default_account
        return self.get_account_or_error(account_id)

    def get_account_or_error(self, account_id: str) -> 'Account':
        for account in self.accounts:
            if account.id == account_id:
                return account
        raise ValueError(f"Couldn't find account: {account_id}.")

    def get_accounts_or_all(self, account_ids: List[str]) -> Sequence['Account']:
        return [
            self.get_account_or_error(account_id)
            for account_id in account_ids
        ] if account_ids else self.accounts

    async def get_detailed_accounts(self, **kwargs):
        accounts = []
        for i, account in enumerate(self.accounts):
            details = await account.get_details(**kwargs)
            details['is_default'] = i == 0
            accounts.append(details)
        return accounts

    @classmethod
    def from_storage(cls, storage: 'WalletStorage', manager: 'WalletManager') -> 'Wallet':
        json_dict = storage.read()
        wallet = cls(
            name=json_dict.get('name', 'Wallet'),
            preferences=json_dict.get('preferences', {}),
            storage=storage
        )
        account_dicts: Sequence[dict] = json_dict.get('accounts', [])
        for account_dict in account_dicts:
            ledger = manager.get_or_create_ledger(account_dict['ledger'])
            Account.from_dict(ledger, wallet, account_dict)
        return wallet

    def to_dict(self, encrypt_password: str = None):
        return {
            'version': WalletStorage.LATEST_VERSION,
            'name': self.name,
            'preferences': self.preferences.data,
            'accounts': [a.to_dict(encrypt_password) for a in self.accounts]
        }

    def to_json(self):
        assert not self.is_locked, "Cannot serialize a wallet with locked/encrypted accounts."
        return json.dumps(self.to_dict())

    def save(self):
        if self.preferences.get(ENCRYPT_ON_DISK, False):
            if self.encryption_password is not None:
                return self.storage.write(self.to_dict(encrypt_password=self.encryption_password))
            elif not self.is_locked:
                log.warning(
                    "Disk encryption requested but no password available for encryption. "
                    "Resetting encryption preferences and saving wallet in an unencrypted state."
                )
                self.preferences[ENCRYPT_ON_DISK] = False
        return self.storage.write(self.to_dict())

    @property
    def hash(self) -> bytes:
        h = sha256()
        if self.is_encrypted:
            assert self.encryption_password is not None, \
                "Encryption is enabled but no password is available, cannot generate hash."
            h.update(self.encryption_password.encode())
        h.update(self.preferences.hash)
        for account in sorted(self.accounts, key=attrgetter('id')):
            h.update(account.hash)
        return h.digest()

    def pack(self, password):
        assert not self.is_locked, "Cannot pack a wallet with locked/encrypted accounts."
        new_data_compressed = zlib.compress(self.to_json().encode())
        return better_aes_encrypt(password, new_data_compressed)

    @classmethod
    def unpack(cls, password, encrypted):
        decrypted = better_aes_decrypt(password, encrypted)
        try:
            decompressed = zlib.decompress(decrypted)
        except zlib.error as e:
            if "incorrect header check" in e.args[0].lower():
                raise InvalidPasswordError()
            if "unknown compression method" in e.args[0].lower():
                raise InvalidPasswordError()
            raise
        return json.loads(decompressed)

    def merge(self, manager: 'WalletManager',
              password: str, data: str) -> (List['Account'], List['Account']):
        assert not self.is_locked, "Cannot sync apply on a locked wallet."
        added_accounts, merged_accounts = [], []
        if password is None:
            decrypted_data = json.loads(data)
        else:
            decrypted_data = self.unpack(password, data)
        self.preferences.merge(decrypted_data.get('preferences', {}))
        for account_dict in decrypted_data['accounts']:
            ledger = manager.get_or_create_ledger(account_dict['ledger'])
            _, _, pubkey = Account.keys_from_dict(ledger, account_dict)
            account_id = pubkey.address
            local_match = None
            for local_account in self.accounts:
                if account_id == local_account.id:
                    local_match = local_account
                    break
            if local_match is not None:
                local_match.merge(account_dict)
                merged_accounts.append(local_match)
            else:
                new_account = Account.from_dict(ledger, self, account_dict)
                added_accounts.append(new_account)
        return added_accounts, merged_accounts

    @property
    def is_locked(self) -> bool:
        for account in self.accounts:
            if account.encrypted:
                return True
        return False

    async def unlock(self, password):
        for account in self.accounts:
            if account.encrypted:
                if not account.decrypt(password):
                    return False
                await account.deterministic_channel_keys.ensure_cache_primed()
        self.encryption_password = password
        return True

    def lock(self):
        assert self.encryption_password is not None, "Cannot lock an unencrypted wallet, encrypt first."
        for account in self.accounts:
            if not account.encrypted:
                account.encrypt(self.encryption_password)
        return True

    @property
    def is_encrypted(self) -> bool:
        # either its locked or it was unlocked using a password.
        # if its set to encrypt on preferences but isnt encrypted and no password was given so far,
        # then its not encrypted
        return self.is_locked or (
            self.preferences.get(ENCRYPT_ON_DISK, False) and self.encryption_password is not None)

    def decrypt(self):
        assert not self.is_locked, "Cannot decrypt a locked wallet, unlock first."
        self.preferences[ENCRYPT_ON_DISK] = False
        self.save()
        return True

    def encrypt(self, password):
        assert not self.is_locked, "Cannot re-encrypt a locked wallet, unlock first."
        assert password, "Cannot encrypt with blank password."
        self.encryption_password = password
        self.preferences[ENCRYPT_ON_DISK] = True
        self.save()
        return True


class WalletStorage:

    LATEST_VERSION = 1

    def __init__(self, path=None, default=None):
        self.path = path
        self._default = default or {
            'version': self.LATEST_VERSION,
            'name': 'My Wallet',
            'preferences': {},
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

        temp_path = "{}.tmp.{}".format(self.path, os.getpid())
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
