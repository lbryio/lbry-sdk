import base64
import distutils.version
import random
import os
import json
import yaml
import datetime

from lbrynet.core.cryptoutils import get_lbry_hash_obj

blobhash_length = get_lbry_hash_obj().digest_size * 2  # digest_size is in bytes, and blob hashes are hex encoded


def generate_id(num=None):
    h = get_lbry_hash_obj()
    if num is not None:
        h.update(str(num))
    else:
        h.update(str(random.getrandbits(512)))
    return h.digest()


def is_valid_blobhash(blobhash):
    """
    @param blobhash: string, the blobhash to check

    @return: Whether the blobhash is the correct length and contains only valid characters (0-9, a-f)
    """
    if len(blobhash) != blobhash_length:
        return False
    for l in blobhash:
        if l not in "0123456789abcdef":
            return False
    return True


def version_is_greater_than(a, b):
    """Returns True if version a is more recent than version b"""
    try:
        return distutils.version.StrictVersion(a) > distutils.version.StrictVersion(b)
    except ValueError:
        return distutils.version.LooseVersion(a) > distutils.version.LooseVersion(b)


def deobfuscate(obfustacated):
    return base64.b64decode(obfustacated.decode('rot13'))


def obfuscate(plain):
    return base64.b64encode(plain).encode('rot13')


settings_decoders = {
    '.json': json.loads,
    '.yml': yaml.load
}

settings_encoders = {
    '.json': json.dumps,
    '.yml': yaml.safe_dump
}


def load_settings(path):
    ext = os.path.splitext(path)[1]
    f = open(path, 'r')
    data = f.read()
    f.close()
    decoder = settings_decoders.get(ext, False)
    assert decoder is not False, "Unknown settings format .%s" % ext
    return decoder(data)


def save_settings(path, settings):
    ext = os.path.splitext(path)[1]
    encoder = settings_encoders.get(ext, False)
    assert encoder is not False, "Unknown settings format .%s" % ext
    f = open(path, 'w')
    f.write(encoder(settings))
    f.close()


def today():
    return datetime.datetime.today()