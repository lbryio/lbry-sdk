import base64
import datetime
import random
import socket
import string
import json
import traceback
import functools
import logging
import pkg_resources
from twisted.python.failure import Failure
from twisted.internet import defer
from lbryschema.claim import ClaimDict
from lbrynet.core.cryptoutils import get_lbry_hash_obj

log = logging.getLogger(__name__)

# digest_size is in bytes, and blob hashes are hex encoded
blobhash_length = get_lbry_hash_obj().digest_size * 2


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
    # Import here to ensure that it gets called after installing a reactor
    # see: http://twistedmatrix.com/documents/current/core/howto/choosing-reactor.html
    from twisted.internet import reactor
    return reactor.callLater(delay, func, *args, **kwargs)

def safe_start_looping_call(looping_call, interval_sec):
    if not looping_call.running:
        looping_call.start(interval_sec)

def safe_stop_looping_call(looping_call):
    if looping_call.running:
        looping_call.stop()

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


def check_connection(server="lbry.io", port=80, timeout=2):
    """Attempts to open a socket to server:port and returns True if successful."""
    log.debug('Checking connection to %s:%s', server, port)
    try:
        server = socket.gethostbyname(server)
        socket.create_connection((server, port), timeout)
        log.debug('Connection successful')
        return True
    except (socket.gaierror, socket.herror) as ex:
        log.warning("Failed to connect to %s:%s. Unable to resolve domain. Trying to bypass DNS",
                    server, port)
        try:
            server = "8.8.8.8"
            port = 53
            socket.create_connection((server, port), timeout)
            log.debug('Connection successful')
            return True
        except Exception as ex:
            log.error("Failed to connect to %s:%s. Maybe the internet connection is not working",
                      server, port)
            return False
    except Exception as ex:
        log.error("Failed to connect to %s:%s. Maybe the internet connection is not working",
                      server, port)
        return False


def random_string(length=10, chars=string.ascii_lowercase):
    return ''.join([random.choice(chars) for _ in range(length)])


def short_hash(hash_str):
    return hash_str[:6]


def get_sd_hash(stream_info):
    if not stream_info:
        return None
    if isinstance(stream_info, ClaimDict):
        return stream_info.source_hash
    result = stream_info.get('claim', {}).\
        get('value', {}).\
        get('stream', {}).\
        get('source', {}).\
        get('source')
    if not result:
        log.warn("Unable to get sd_hash")
    return result


def json_dumps_pretty(obj, **kwargs):
    return json.dumps(obj, sort_keys=True, indent=2, separators=(',', ': '), **kwargs)


class DeferredLockContextManager(object):
    def __init__(self, lock):
        self._lock = lock

    def __enter__(self):
        yield self._lock.aquire()

    def __exit__(self, exc_type, exc_val, exc_tb):
        yield self._lock.release()


@defer.inlineCallbacks
def DeferredDict(d, consumeErrors=False):
    keys = []
    dl = []
    response = {}
    for k, v in d.iteritems():
        keys.append(k)
        dl.append(v)
    results = yield defer.DeferredList(dl, consumeErrors=consumeErrors)
    for k, (success, result) in zip(keys, results):
        if success:
            response[k] = result
    defer.returnValue(response)


class DeferredProfiler(object):
    def __init__(self):
        self.profile_results = {}

    def add_result(self, fn, start_time, finished_time, stack, success):
        self.profile_results[fn].append((start_time, finished_time, stack, success))

    def show_profile_results(self, fn):
        profile_results = list(self.profile_results[fn])
        call_counts = {
            caller: [(start, finished, finished - start, success)
                     for (start, finished, _caller, success) in profile_results
                     if _caller == caller]
            for caller in set(result[2] for result in profile_results)
        }

        log.info("called %s %i times from %i sources\n", fn.__name__, len(profile_results), len(call_counts))
        for caller in sorted(list(call_counts.keys()), key=lambda c: len(call_counts[c]), reverse=True):
            call_info = call_counts[caller]
            times = [r[2] for r in call_info]
            own_time = sum(times)
            times.sort()
            longest = 0 if not times else times[-1]
            shortest = 0 if not times else times[0]
            log.info(
                "%i successes and %i failures\nlongest %f, shortest %f, avg %f\ncaller:\n%s",
                len([r for r in call_info if r[3]]),
                len([r for r in call_info if not r[3]]),
                longest, shortest, own_time / float(len(call_info)), caller
            )

    def profiled_deferred(self, reactor=None):
        if not reactor:
            from twisted.internet import reactor

        def _cb(result, fn, start, caller_info):
            if isinstance(result, (Failure, Exception)):
                error = result
                result = None
            else:
                error = None
            self.add_result(fn, start, reactor.seconds(), caller_info, error is None)
            if error is None:
                return result
            raise error

        def _profiled_deferred(fn):
            reactor.addSystemEventTrigger("after", "shutdown", self.show_profile_results, fn)
            self.profile_results[fn] = []

            @functools.wraps(fn)
            def _wrapper(*args, **kwargs):
                caller_info = "".join(traceback.format_list(traceback.extract_stack()[-3:-1]))
                start = reactor.seconds()
                d = defer.maybeDeferred(fn, *args, **kwargs)
                d.addBoth(_cb, fn, start, caller_info)
                return d

            return _wrapper

        return _profiled_deferred


_profiler = DeferredProfiler()
profile_deferred = _profiler.profiled_deferred
