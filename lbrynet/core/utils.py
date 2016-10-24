import base64
import datetime
import distutils.version
import logging
import json
import random
import os
import socket
import yaml

from lbrynet.core.cryptoutils import get_lbry_hash_obj


# digest_size is in bytes, and blob hashes are hex encoded
blobhash_length = get_lbry_hash_obj().digest_size * 2


log = logging.getLogger(__name__)


# defining these time functions here allows for easier overriding in testing
def now():
    return datetime.datetime.now()


def utcnow():
    return datetime.datetime.utcnow()


def isonow():
    """Return utc now in isoformat with timezone"""
    return utcnow().isoformat() + 'Z'

def today():
    return datetime.datetime.today()


def generate_id(num=None):
    h = get_lbry_hash_obj()
    if num is not None:
        h.update(str(num))
    else:
        h.update(str(random.getrandbits(512)))
    return h.digest()


def is_valid_hashcharacter(char):
    return char in "0123456789abcdef"


def is_valid_blobhash(blobhash):
    """Checks whether the blobhash is the correct length and contains only
    valid characters (0-9, a-f)

    @param blobhash: string, the blobhash to check

    @return: True/False
    """
    return len(blobhash) == blobhash_length and all(is_valid_hashcharacter(l) for l in blobhash)


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


def check_connection(server="www.lbry.io", port=80):
    """Attempts to open a socket to server:port and returns True if successful."""
    try:
        host = socket.gethostbyname(server)
        s = socket.create_connection((host, port), 2)
        return True
    except Exception as ex:
        log.info(
            "Failed to connect to %s:%s. Maybe the internet connection is not working",
            server, port, exc_info=True)
        return False
