import logging
import time
import hashlib
import binascii

import ecdsa
from lbry import utils
from lbry.crypto.hash import sha256
from lbry.wallet.transaction import Output

log = logging.getLogger(__name__)


def get_encoded_signature(signature):
    signature = signature.encode() if isinstance(signature, str) else signature
    r = int(signature[:int(len(signature) / 2)], 16)
    s = int(signature[int(len(signature) / 2):], 16)
    return ecdsa.util.sigencode_der(r, s, len(signature) * 4)


def cid2hash(claim_id: str) -> bytes:
    return binascii.unhexlify(claim_id.encode())[::-1]


def is_comment_signed_by_channel(comment: dict, channel: Output, sign_comment_id=False):
    if isinstance(channel, Output):
        try:
            signing_field = comment['comment_id'] if sign_comment_id else comment['comment']
            return verify(channel, signing_field.encode(), comment, cid2hash(comment['channel_id']))
        except KeyError:
            pass
    return False


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


def sign_comment(comment: dict, channel: Output, sign_comment_id=False):
    signing_field = comment['comment_id'] if sign_comment_id else comment['comment']
    comment.update(sign(channel, signing_field.encode()))


def sign(channel, data):
    timestamp = str(int(time.time()))
    pieces = [timestamp.encode(), channel.claim_hash, data]
    digest = sha256(b''.join(pieces))
    signature = channel.private_key.sign_digest_deterministic(digest, hashfunc=hashlib.sha256)
    return {
        'signature': binascii.hexlify(signature).decode(),
        'signing_ts': timestamp
    }


def sign_reaction(reaction: dict, channel: Output):
    signing_field = reaction['channel_name']
    reaction.update(sign(channel, signing_field.encode()))


async def jsonrpc_post(url: str, method: str, params: dict = None, **kwargs) -> any:
    params = params or {}
    params.update(kwargs)
    json_body = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}
    async with utils.aiohttp_request('POST', url, json=json_body) as response:
        try:
            result = await response.json()
            return result['result'] if 'result' in result else result
        except Exception as cte:
            log.exception('Unable to decode response from server: %s', cte)
            return await response.text()
