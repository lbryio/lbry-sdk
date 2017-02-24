import base64
import datetime
import logging
import random
import socket
import string
import json
import base58
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


def random_string(length=10, chars=string.ascii_lowercase):
    return ''.join([random.choice(chars) for _ in range(length)])


def short_hash(hash_str):
    return hash_str[:6]


def get_sd_hash(metadata_dict):
    sd_hash = metadata_dict['sources']['lbry_sd_hash']
    return sd_hash


def claim_hash(txid, nout):
    digest = get_lbry_hash_obj()
    decoded_txid = txid.decode('hex')
    digest.update(decoded_txid)
    digest.update(chr(int(nout)))
    return digest.hexdigest()


def metadata_to_b58(metadata):
    if isinstance(metadata, str):
        metadata_str = metadata
    elif isinstance(metadata, dict):
        metadata_str = json.dumps(metadata)
    else:
        raise Exception("Can't encode metadata type %s" % str(type(metadata)))
    return base58.b58encode(metadata_str)


def decode_b58_metadata(encoded_metadata):
    decoded = base58.b58decode(encoded_metadata)
    metadata = json.loads(decoded)
    return metadata


def rerun_callback_on(f, *exceptions):
    def rerun_on(err, *args, **kwargs):
        if err.check(*exceptions):
            log.warning("Caught %s, rerunning %s", err, f)
            return wrapper(*args, **kwargs)

    def wrapper(*args, **kwargs):
        d = f(*args, **kwargs)
        d.addErrback(lambda err: rerun_on(err, *args, **kwargs))
        return d

    return wrapper


def trap_errback(f, *exceptions):
    def trap(err):
        if err.check(*exceptions):
            log.warning("Trapped %s in %s", err, f)

    def wrapper(*args, **kwargs):
        d = f(*args, **kwargs)
        d.addErrback(trap)
        return d

    return wrapper


def InlineCallbackRerunOn(*rerun_on):
    from twisted.internet import defer

    def _rerun_cb(f):
        if not rerun_on:
            return defer.inlineCallbacks(f)
        else:
            return rerun_callback_on(defer.inlineCallbacks(f), *rerun_on)

    return _rerun_cb


def InlineCallbackCatch(*catch):
    from twisted.internet import defer

    def _trap_eb(f):
        if not catch:
            return defer.inlineCallbacks(f)
        else:
            return trap_errback(defer.inlineCallbacks(f), *catch)

    return _trap_eb
