import base58
import hmac
import hashlib
import yaml
import os
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


class APIKey(dict):
    def __init__(self, key, name=None):
        self.key = key if isinstance(key, str) else key['token']
        self.name = name if name else hashlib.sha256(self.key).hexdigest()
        self.expiration = None if isinstance(key, str) else key.get('expiration', None)
        self.update({self.name: {'token': self.key, 'expiration': self.expiration}})

    @classmethod
    def new(cls, expiration=None, seed=None, name=None):
        key_val = generate_key(seed)
        key = {'token': key_val, 'expiration': expiration}
        return APIKey(key, name)

    def token(self):
        return self[self.name]['token']

    def _raw_key(self):
        return base58.b58decode(self.token())

    def get_hmac(self, message):
        decoded_key = self._raw_key()
        signature = hmac.new(decoded_key, message, hashlib.sha256)
        return base58.b58encode(signature.digest())

    def compare_hmac(self, message, token):
        decoded_token = base58.b58decode(token)
        target = base58.b58decode(self.get_hmac(message))
        try:
            assert len(decoded_token) == len(target), "Length mismatch"
            r = hmac.compare_digest(decoded_token, target)
        except:
            return False
        return r

    def rename(self, name):
        old = self.keys()[0]
        t = self.pop(old)
        self.update({name: t})


def load_api_keys(path):
    if not os.path.isfile(path):
        raise Exception("Invalid api key path")

    f = open(path, "r")
    data = yaml.load(f.read())
    f.close()

    keys = {key: APIKey(data[key], name=key)[key] for key in data}

    return keys


def save_api_keys(keys, path):
    data = yaml.safe_dump(dict(keys))
    f = open(path, "w")
    f.write(data)
    f.close()
