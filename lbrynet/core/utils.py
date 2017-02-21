import base64
import datetime
import logging
import random
import os
import socket
import string
import sys

import pkg_resources

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


def timedelta(**kwargs):
    return datetime.timedelta(**kwargs)


def datetime_obj(*args, **kwargs):
    return datetime.datetime(*args, **kwargs)


def call_later(delay, func, *args, **kwargs):
    # Import here to ensure that it gets called after installing a reator
    # see: http://twistedmatrix.com/documents/current/core/howto/choosing-reactor.html
    from twisted.internet import reactor
    return reactor.callLater(delay, func, *args, **kwargs)


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
    return pkg_resources.parse_version(a) > pkg_resources.parse_version(b)


def deobfuscate(obfustacated):
    return base64.b64decode(obfustacated.decode('rot13'))


def obfuscate(plain):
    return base64.b64encode(plain).encode('rot13')


def check_connection(server="www.lbry.io", port=80):
    """Attempts to open a socket to server:port and returns True if successful."""
    try:
        log.debug('Checking connection to %s:%s', server, port)
        host = socket.gethostbyname(server)
        s = socket.create_connection((host, port), 2)
        log.debug('Connection successful')
        return True
    except Exception as ex:
        log.info(
            "Failed to connect to %s:%s. Maybe the internet connection is not working",
            server, port, exc_info=True)
        return False


def setup_certs_for_windows():
    if getattr(sys, 'frozen', False) and os.name == "nt":
        cert_path = os.path.join(os.path.dirname(sys.executable), "cacert.pem")
        os.environ["REQUESTS_CA_BUNDLE"] = cert_path


def random_string(length=10, chars=string.ascii_lowercase):
    return ''.join([random.choice(chars) for _ in range(length)])


def short_hash(hash_str):
    return hash_str[:6]
