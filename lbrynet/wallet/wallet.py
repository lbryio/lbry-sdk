import stat
import json
import os

from lbrynet.wallet.account import Account
from lbrynet.wallet.constants import MAIN_CHAIN


class Wallet:

    def __init__(self, **kwargs):
        self.name = kwargs.get('name', 'Wallet')
        self.chain = kwargs.get('chain', MAIN_CHAIN)
        self.accounts = kwargs.get('accounts') or {0: Account.generate()}

    @classmethod
    def from_json(cls, json_data):
        if 'accounts' in json_data:
            json_data = json_data.copy()
            json_data['accounts'] = {
                a_id: Account.from_json(a) for
                a_id, a in json_data['accounts'].items()
            }
        return cls(**json_data)

    def to_json(self):
        return {
            'name': self.name,
            'chain': self.chain,
            'accounts': {
                a_id: a.to_json() for
                a_id, a in self.accounts.items()
            }
        }

    @property
    def default_account(self):
        return self.accounts.get(0, None)

    @property
    def addresses(self):
        for account in self.accounts.values():
            for address in account.addresses:
                yield address

    def ensure_enough_addresses(self):
        return [
            address
            for account in self.accounts.values()
            for address in account.ensure_enough_addresses()
        ]

    def get_private_key_for_address(self, address):
        for account in self.accounts.values():
            private_key = account.get_private_key_for_address(address)
            if private_key is not None:
                return private_key


class EphemeralWalletStorage(dict):

    LATEST_VERSION = 2

    def save(self):
        return json.dumps(self, indent=4, sort_keys=True)

    def upgrade(self):

        def _rename_property(old, new):
            if old in self:
                old_value = self[old]
                del self[old]
                if new not in self:
                    self[new] = old_value

        if self.get('version', 1) == 1:  # upgrade from version 1 to version 2
            # TODO: `addr_history` should actually be imported into SQLStorage and removed from wallet.
            _rename_property('addr_history', 'history')
            _rename_property('use_encryption', 'encrypted')
            _rename_property('gap_limit', 'gap_limit_for_receiving')
            self['version'] = 2

        self.save()


class PermanentWalletStorage(EphemeralWalletStorage):

    def __init__(self, *args, **kwargs):
        super(PermanentWalletStorage, self).__init__(*args, **kwargs)
        self.path = None

    @classmethod
    def from_path(cls, path):
        if os.path.exists(path):
            with open(path, "r") as f:
                json_data = f.read()
                json_dict = json.loads(json_data)
                storage = cls(**json_dict)
                if 'version' in storage and storage['version'] != storage.LATEST_VERSION:
                    storage.upgrade()
        else:
            storage = cls()
        storage.path = path
        return storage

    def save(self):
        json_data = super(PermanentWalletStorage, self).save()

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

        return json_data
