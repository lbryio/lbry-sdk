import copy
import stat
import json
import os
import logging

from .constants import NEW_SEED_VERSION
from .account import Account
from .mnemonic import Mnemonic
from .lbrycrd import pw_encode, bip32_private_derivation, bip32_root
from .blockchain import BlockchainTransactions

log = logging.getLogger(__name__)


class WalletStorage:

    def __init__(self, path):
        self.data = {}
        self.path = path
        self.file_exists = False
        self.modified = False
        self.path and self.read()

    def read(self):
        try:
            with open(self.path, "r") as f:
                data = f.read()
        except IOError:
            return
        try:
            self.data = json.loads(data)
        except Exception:
            self.data = {}
            raise IOError("Cannot read wallet file '%s'" % self.path)
        self.file_exists = True

    def get(self, key, default=None):
        v = self.data.get(key)
        if v is None:
            v = default
        else:
            v = copy.deepcopy(v)
        return v

    def put(self, key, value):
        try:
            json.dumps(key)
            json.dumps(value)
        except:
            return
        if value is not None:
            if self.data.get(key) != value:
                self.modified = True
                self.data[key] = copy.deepcopy(value)
        elif key in self.data:
            self.modified = True
            self.data.pop(key)

    def write(self):
        self._write()

    def _write(self):
        if not self.modified:
            return
        s = json.dumps(self.data, indent=4, sort_keys=True)
        temp_path = "%s.tmp.%s" % (self.path, os.getpid())
        with open(temp_path, "w") as f:
            f.write(s)
            f.flush()
            os.fsync(f.fileno())

        if os.path.exists(self.path):
            mode = os.stat(self.path).st_mode
        else:
            mode = stat.S_IREAD | stat.S_IWRITE
        # perform atomic write on POSIX systems
        try:
            os.rename(temp_path, self.path)
        except:
            os.remove(self.path)
            os.rename(temp_path, self.path)
        os.chmod(self.path, mode)
        self.modified = False

    def upgrade(self):

        def _rename_property(old, new):
            if old in self.data:
                old_value = self.data[old]
                del self.data[old]
                if new not in self.data:
                    self.data[new] = old_value

        _rename_property('addr_history', 'history')
        _rename_property('use_encryption', 'encrypted')


class Wallet:

    root_name = 'x/'
    root_derivation = 'm/'
    gap_limit_for_change = 6

    def __init__(self, path, headers):
        self.storage = storage = WalletStorage(path)
        storage.upgrade()
        self.headers = headers
        self.accounts = self._instantiate_accounts(storage.get('accounts', {}))
        self.history = BlockchainTransactions(storage.get('history', {}))
        self.master_public_keys = storage.get('master_public_keys', {})
        self.master_private_keys = storage.get('master_private_keys', {})
        self.gap_limit = storage.get('gap_limit', 20)
        self.seed = storage.get('seed', '')
        self.seed_version = storage.get('seed_version', NEW_SEED_VERSION)
        self.encrypted = storage.get('encrypted', storage.get('use_encryption', False))
        self.claim_certificates = storage.get('claim_certificates', {})
        self.default_certificate_claim = storage.get('default_certificate_claim', None)

    def _instantiate_accounts(self, accounts):
        instances = {}
        for index, details in accounts.items():
            if 'xpub' in details:
                instances[index] = Account(
                    details, self.gap_limit, self.gap_limit_for_change, self.is_address_old
                )
            else:
                log.error("cannot load account: {}".format(details))
        return instances

    @property
    def exists(self):
        return self.storage.file_exists

    @property
    def default_account(self):
        return self.accounts['0']

    @property
    def sequences(self):
        for account in self.accounts.values():
            for sequence in account.sequences:
                yield sequence

    @property
    def addresses(self):
        for sequence in self.sequences:
            for address in sequence.addresses:
                yield address

    @property
    def receiving_addresses(self):
        for account in self.accounts.values():
            for address in account.receiving.addresses:
                yield address

    @property
    def change_addresses(self):
        for account in self.accounts.values():
            for address in account.receiving.addresses:
                yield address

    @property
    def addresses_without_history(self):
        for address in self.addresses:
            if not self.history.has_address(address):
                yield address

    def ensure_enough_addresses(self):
        return [
            address
            for sequence in self.sequences
            for address in sequence.ensure_enough_addresses()
        ]

    def create(self):
        mnemonic = Mnemonic(self.storage.get('lang', 'eng'))
        seed = mnemonic.make_seed()
        self.add_seed(seed, None)
        self.add_xprv_from_seed(seed, self.root_name, None)
        account = Account(
            {'xpub': self.master_public_keys.get("x/")},
            self.gap_limit,
            self.gap_limit_for_change,
            self.is_address_old
        )
        self.add_account('0', account)

    def add_seed(self, seed, password):
        if self.seed:
            raise Exception("a seed exists")
        self.seed_version, self.seed = self.format_seed(seed)
        if password:
            self.seed = pw_encode(self.seed, password)
        self.storage.put('seed', self.seed)
        self.storage.put('seed_version', self.seed_version)
        self.set_use_encryption(password is not None)

    @staticmethod
    def format_seed(seed):
        return NEW_SEED_VERSION, ' '.join(seed.split())

    def add_xprv_from_seed(self, seed, name, password, passphrase=''):
        xprv, xpub = bip32_root(Mnemonic.mnemonic_to_seed(seed, passphrase))
        xprv, xpub = bip32_private_derivation(xprv, "m/", self.root_derivation)
        self.add_master_public_key(name, xpub)
        self.add_master_private_key(name, xprv, password)

    def add_master_public_key(self, name, xpub):
        if xpub in self.master_public_keys.values():
            raise BaseException('Duplicate master public key')
        self.master_public_keys[name] = xpub
        self.storage.put('master_public_keys', self.master_public_keys)

    def add_master_private_key(self, name, xpriv, password):
        self.master_private_keys[name] = pw_encode(xpriv, password)
        self.storage.put('master_private_keys', self.master_private_keys)

    def add_account(self, account_id, account):
        self.accounts[account_id] = account
        self.save_accounts()

    def set_use_encryption(self, use_encryption):
        self.use_encryption = use_encryption
        self.storage.put('use_encryption', use_encryption)

    def save_accounts(self):
        d = {}
        for k, v in self.accounts.items():
            d[k] = v.as_dict()
        self.storage.put('accounts', d)

    def is_address_old(self, address, age_limit=2):
        age = -1
        for tx in self.history.get_transactions(address, []):
            if tx.height == 0:
                tx_age = 0
            else:
                tx_age = self.headers.height - tx.height + 1
            if tx_age > age:
                age = tx_age
        return age > age_limit
