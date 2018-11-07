import six
import hashlib


def sha256(x):
    if isinstance(x, six.text_type):
        x = x.encode('utf-8')
    return hashlib.sha256(x).digest()


def double_sha256(x):
    return sha256(sha256(x))


def ripemd160(x):
    if isinstance(x, six.text_type):
        x = x.encode('utf-8')
    md = hashlib.new('ripemd160')
    md.update(x)
    return md.digest()


def hash160(x):
    return ripemd160(sha256(x))
