import logging
import time
import hashlib
import binascii

from lbry import utils
import ecdsa
from torba.client.hash import sha256
from lbry.wallet.transaction import Output

log = logging.getLogger(__name__)


def get_encoded_signature(signature):
    signature = signature.encode() if type(signature) is str else signature
    r = int(signature[:int(len(signature) / 2)], 16)
    s = int(signature[int(len(signature) / 2):], 16)
    return ecdsa.util.sigencode_der(r, s, len(signature) * 4)


def is_comment_signed_by_channel(comment: dict, channel: Output):
    if type(channel) is Output:
        try:
            pieces = [
                comment['signing_ts'].encode(),
                channel.claim_hash,
                comment['comment'].encode()
            ]
            return Output.is_signature_valid(
                get_encoded_signature(comment['signature']),
                sha256(b''.join(pieces)),
                channel.claim.channel.public_key_bytes
            )
        except KeyError:
            pass
    return False


def sign_comment(comment: dict, channel: Output, signing_field='comment'):
    timestamp = str(int(time.time())).encode()
    pieces = [timestamp, channel.claim_hash, comment[signing_field].encode()]
    digest = sha256(b''.join(pieces))
    signature = channel.private_key.sign_digest_deterministic(digest, hashfunc=hashlib.sha256)
    comment.update({
        'signature': binascii.hexlify(signature).decode(),
        'signing_ts': timestamp.decode()
    })


async def jsonrpc_post(url: str, method: str, params: dict = None, **kwargs) -> any:
    params = params or {}
    params.update(kwargs)
    json_body = {'jsonrpc': '2.0', 'id': None, 'method': method, 'params': params}
    headers = {'Content-Type': 'application/json'}
    async with utils.aiohttp_request('POST', url, json=json_body, headers=headers) as response:
        try:
            result = await response.json()
            return result['result'] if 'result' in result else result
        except Exception as cte:
            log.exception('Unable to decode response from server: %s', cte)
            return await response.text()
