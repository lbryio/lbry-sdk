import base58
import hmac
import hashlib
import yaml
import os
import json
import logging

log = logging.getLogger(__name__)

API_KEY_NAME = "api"


def sha(x):
    h = hashlib.sha256(x).digest()
    return base58.b58encode(h)


def generate_key(x=None):
    if x is None:
        return sha(os.urandom(256))
    else:
        return sha(x)


class APIKey(object):
    def __init__(self, secret, name, expiration=None):
        self.secret = secret
        self.name = name
        self.expiration = expiration

    @classmethod
    def new(cls, seed=None, name=None, expiration=None):
        secret = generate_key(seed)
        key_name = name if name else sha(secret)
        return APIKey(secret, key_name, expiration)

    def _raw_key(self):
        return base58.b58decode(self.secret)

    def get_hmac(self, message):
        decoded_key = self._raw_key()
        signature = hmac.new(decoded_key, message, hashlib.sha256)
        return base58.b58encode(signature.digest())

    def compare_hmac(self, message, token):
        decoded_token = base58.b58decode(token)
        target = base58.b58decode(self.get_hmac(message))

        try:
            if len(decoded_token) != len(target):
                return False
            return hmac.compare_digest(decoded_token, target)
        except:
            return False


def load_api_keys(path):
    if not os.path.isfile(path):
        raise Exception("Invalid api key path")

    with open(path, "r") as f:
        data = yaml.load(f.read())

    keys_for_return = {}
    for key_name in data:
        key = data[key_name]
        secret = key['secret']
        expiration = key['expiration']
        keys_for_return.update({key_name: APIKey(secret, key_name, expiration)})
    return keys_for_return


def save_api_keys(keys, path):
    with open(path, "w") as f:
        key_dict = {keys[key_name].name: {'secret': keys[key_name].secret,
                                          'expiration': keys[key_name].expiration}
                    for key_name in keys}
        data = yaml.safe_dump(key_dict)
        f.write(data)


def initialize_api_key_file(key_path):
    keys = {}
    new_api_key = APIKey.new(name=API_KEY_NAME)
    keys.update({new_api_key.name: new_api_key})
    save_api_keys(keys, key_path)


def get_auth_message(message_dict):
    return json.dumps(message_dict, sort_keys=True)
