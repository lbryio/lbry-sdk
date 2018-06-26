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
