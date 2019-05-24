import logging

import aiohttp
import hashlib
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric import utils
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key

log = logging.getLogger(__name__)


def sign_comment(**kwargs):
    private_key = generate_private_key(
        public_exponent=65537,
        key_size=4096,
        backend=default_backend()
    )
    chosen_hash = hashes.SHA256()
    hasher = hashes.Hash(chosen_hash, default_backend())
    value_to_hash = b':'.join(bytes(v, 'utf-8') for v in kwargs.values() if type(v) is str)
    hasher.update(value_to_hash)
    digest = hasher.finalize()
    signature = private_key.sign(
        digest,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        utils.Prehashed(chosen_hash)
    )
    m = hashlib.sha3_256()
    m.update(signature)
    return m.hexdigest()


def rpc_body(method: str, rpc_id: any, **params) -> dict:
    return {'jsonrpc': '2.0', 'id': rpc_id, 'method': method, 'params': {**params}}


async def jsonrpc_post(url: str, method: str, **params) -> any:
    json_body = {'jsonrpc': '2.0', 'id': None, 'method': method, 'params': params}
    headers = {'Content-Type': 'application/json'}
    async with aiohttp.request('POST', url, json=json_body, headers=headers) as response:
        try:
            result = await response.json()
            return result['result'] if 'result' in result else result
        except aiohttp.client.ContentTypeError as cte:
            log.exception('Unable to decode respose from server: %s', cte)
            return await response.text()
