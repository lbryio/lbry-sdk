from binascii import hexlify
from lbryschema.claim import ClaimDict
from lbryschema.signer import SECP256k1, get_signer

from torba.baseaccount import BaseAccount


def generate_certificate():
    secp256k1_private_key = get_signer(SECP256k1).generate().private_key.to_pem()
    return ClaimDict.generate_certificate(secp256k1_private_key, curve=SECP256k1), secp256k1_private_key


class Account(BaseAccount):

    def __init__(self, *args, **kwargs):
        super(BaseAccount, self).__init__(*args, **kwargs)
        self.certificates = {}


class SingleKeyAccount(BaseAccount):
    # What are sane default values for receiving_gap, change_gap,
    # receiving_maximum_use_per_address, change_maximum_use_per_address?
    def __init__(self, ledger, seed, encrypted, private_key,
                 public_key, receiving_gap=0, change_gap=0,
                 receiving_maximum_use_per_address=0,
                 change_maximum_use_per_address=0):
        self.ledger = ledger
        self.seed = seed
        self.encrypted = encrypted
        self.private_key = private_key
        self.public_key = public_key
        # What are sane defaults for gap, maximum_use_per_address?
        self.receiving, self.change = self.keychains = (
            # (account, parent_key, chain_number, gap, maximum_use_per_address)
            KeyChain(self, public_key, 0, 0, 0),
        )
        # We need this to happen here not in BaseAccount.__init__
        ledger.add_account(self)

    def get_addresses(self):
        return list(self.ledger.public_key_to_address(self.public_key))

    # def get_unused_addresses(self):
    #     return self.ledger.db.get_unused_addresses(self, None)

    # def ensure_address_gap(self):
    #     raise NotImplementedError

    def get_private_key(self, *args):
        assert not self.encrypted, "Cannot get private key on encrypted wallet account."
        return self.private_key
