from binascii import hexlify
from lbryschema.claim import ClaimDict
from lbryschema.signer import SECP256k1, get_signer

from torba.baseaccount import BaseAccount


def generate_certificate():
    secp256k1_private_key = get_signer(SECP256k1).generate().private_key.to_pem()
    return ClaimDict.generate_certificate(secp256k1_private_key, curve=SECP256k1), secp256k1_private_key


class Account(BaseAccount):

    def __init__(self, *args, **kwargs):
        super(Account, self).__init__(*args, **kwargs)
        self.certificates = {}

    def add_certificate(self, claim_id, key):
        assert claim_id not in self.certificates, 'Trying to add a duplicate certificate.'
        self.certificates[claim_id] = key

    def get_certificate(self, claim_id):
        return self.certificates[claim_id]
