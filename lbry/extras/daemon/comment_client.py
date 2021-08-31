import logging
import time
import hashlib
import binascii

import ecdsa
from lbry.crypto.hash import sha256
from lbry.wallet.transaction import Output

log = logging.getLogger(__name__)


def get_encoded_signature(signature):
    signature = signature.encode() if isinstance(signature, str) else signature
    r = int(signature[:int(len(signature) / 2)], 16)
    s = int(signature[int(len(signature) / 2):], 16)
    return ecdsa.util.sigencode_der(r, s, len(signature) * 4)


def verify(channel, data, signature, channel_hash=None):
    pieces = [
        signature['signing_ts'].encode(),
        channel_hash or channel.claim_hash,
        data
    ]
    return Output.is_signature_valid(
        get_encoded_signature(signature['signature']),
        sha256(b''.join(pieces)),
        channel.claim.channel.public_key_bytes
    )


def sign(channel, data):
    timestamp = str(int(time.time()))
    pieces = [timestamp.encode(), channel.claim_hash, data]
    digest = sha256(b''.join(pieces))
    signature = channel.private_key.sign_digest_deterministic(digest, hashfunc=hashlib.sha256)
    return {
        'signature': binascii.hexlify(signature).decode(),
        'signing_ts': timestamp
    }
