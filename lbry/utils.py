import base64
import codecs
import datetime
import random
import socket
import time
import string
import sys
import json
import typing
import asyncio
import ssl
import logging
import ipaddress
import contextlib
import functools
import collections
import hashlib
import pkg_resources

import certifi
import aiohttp
from prometheus_client import Counter
from lbry.schema.claim import Claim


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


def get_lbry_hash_obj():
    return hashlib.sha384()


def generate_id(num=None):
    h = get_lbry_hash_obj()
    if num is not None:
        h.update(str(num).encode())
    else:
        h.update(str(random.getrandbits(512)).encode())
    return h.digest()


def version_is_greater_than(version_a, version_b):
    """Returns True if version a is more recent than version b"""
    return pkg_resources.parse_version(version_a) > pkg_resources.parse_version(version_b)


def rot13(some_str):
    return codecs.encode(some_str, 'rot_13')


def deobfuscate(obfustacated):
    return base64.b64decode(rot13(obfustacated)).decode()


def obfuscate(plain):
    return rot13(base64.b64encode(plain).decode())


def check_connection(server="lbry.com", port=80, timeout=5) -> bool:
    """Attempts to open a socket to server:port and returns True if successful."""
    log.debug('Checking connection to %s:%s', server, port)
    try:
        server = socket.gethostbyname(server)
        socket.create_connection((server, port), timeout).close()
        return True
    except (socket.gaierror, socket.herror):
        log.debug("Failed to connect to %s:%s. Unable to resolve domain. Trying to bypass DNS",
                  server, port)
        try:
            server = "8.8.8.8"
            port = 53
            socket.create_connection((server, port), timeout).close()
            return True
        except OSError:
            return False
    except OSError:
        return False


def random_string(length=10, chars=string.ascii_lowercase):
    return ''.join([random.choice(chars) for _ in range(length)])


def short_hash(hash_str):
    return hash_str[:6]


def get_sd_hash(stream_info):
    if not stream_info:
        return None
    if isinstance(stream_info, Claim):
        return stream_info.stream.source.sd_hash
    result = stream_info.get('claim', {}).\
        get('value', {}).\
        get('stream', {}).\
        get('source', {}).\
        get('source')
    if not result:
        log.warning("Unable to get sd_hash")
    return result


def json_dumps_pretty(obj, **kwargs):
    return json.dumps(obj, sort_keys=True, indent=2, separators=(',', ': '), **kwargs)

try:
    # the standard contextlib.aclosing() is available in 3.10+
    from contextlib import aclosing  # pylint: disable=unused-import
except ImportError:
    @contextlib.asynccontextmanager
    async def aclosing(thing):
        try:
            yield thing
        finally:
            await thing.aclose()

def async_timed_cache(duration: int):
    def wrapper(func):
        cache: typing.Dict[typing.Tuple,
                           typing.Tuple[typing.Any, float]] = {}

        @functools.wraps(func)
        async def _inner(*args, **kwargs) -> typing.Any:
            loop = asyncio.get_running_loop()
            time_now = loop.time()
            key = (args, tuple(kwargs.items()))
            if key in cache and (time_now - cache[key][1] < duration):
                return cache[key][0]
            to_cache = await func(*args, **kwargs)
            cache[key] = to_cache, time_now
            return to_cache
        return _inner
    return wrapper


def cache_concurrent(async_fn):
    """
    When the decorated function has concurrent calls made to it with the same arguments, only run it once
    """
    cache: typing.Dict = {}

    @functools.wraps(async_fn)
    async def wrapper(*args, **kwargs):
        key = (args, tuple(kwargs.items()))
        cache[key] = cache.get(key) or asyncio.create_task(async_fn(*args, **kwargs))
        try:
            return await cache[key]
        finally:
            cache.pop(key, None)

    return wrapper


@async_timed_cache(300)
async def resolve_host(url: str, port: int, proto: str) -> str:
    if proto not in ['udp', 'tcp']:
        raise Exception("invalid protocol")
    if url.lower() == 'localhost':
        return '127.0.0.1'
    try:
        if ipaddress.ip_address(url):
            return url
    except ValueError:
        pass
    loop = asyncio.get_running_loop()
    return (await loop.getaddrinfo(
        url, port,
        proto=socket.IPPROTO_TCP if proto == 'tcp' else socket.IPPROTO_UDP,
        type=socket.SOCK_STREAM if proto == 'tcp' else socket.SOCK_DGRAM,
        family=socket.AF_INET
    ))[0][4][0]


class LRUCacheWithMetrics:
    __slots__ = [
        'capacity',
        'cache',
        '_track_metrics',
        'hits',
        'misses'
    ]

    def __init__(self, capacity: int, metric_name: typing.Optional[str] = None, namespace: str = "daemon_cache"):
        self.capacity = capacity
        self.cache = collections.OrderedDict()
        if metric_name is None:
            self._track_metrics = False
            self.hits = self.misses = None
        else:
            self._track_metrics = True
            try:
                self.hits = Counter(
                    f"{metric_name}_cache_hit_count", "Number of cache hits", namespace=namespace
                )
                self.misses = Counter(
                    f"{metric_name}_cache_miss_count", "Number of cache misses", namespace=namespace
                )
            except ValueError as err:
                log.debug("failed to set up prometheus %s_cache_miss_count metric: %s", metric_name, err)
                self._track_metrics = False
                self.hits = self.misses = None

    def get(self, key, default=None):
        try:
            value = self.cache.pop(key)
            if self._track_metrics:
                self.hits.inc()
        except KeyError:
            if self._track_metrics:
                self.misses.inc()
            return default
        self.cache[key] = value
        return value

    def set(self, key, value):
        try:
            self.cache.pop(key)
        except KeyError:
            if len(self.cache) >= self.capacity:
                self.cache.popitem(last=False)
        self.cache[key] = value

    def clear(self):
        self.cache.clear()

    def pop(self, key):
        return self.cache.pop(key)

    def __setitem__(self, key, value):
        return self.set(key, value)

    def __getitem__(self, item):
        return self.get(item)

    def __contains__(self, item) -> bool:
        return item in self.cache

    def __len__(self):
        return len(self.cache)

    def __delitem__(self, key):
        self.cache.pop(key)

    def __del__(self):
        self.clear()


class LRUCache:
    __slots__ = [
        'capacity',
        'cache'
    ]

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.cache = collections.OrderedDict()

    def get(self, key, default=None):
        try:
            value = self.cache.pop(key)
        except KeyError:
            return default
        self.cache[key] = value
        return value

    def set(self, key, value):
        try:
            self.cache.pop(key)
        except KeyError:
            if len(self.cache) >= self.capacity:
                self.cache.popitem(last=False)
        self.cache[key] = value

    def items(self):
        return self.cache.items()

    def clear(self):
        self.cache.clear()

    def pop(self, key, default=None):
        return self.cache.pop(key, default)

    def __setitem__(self, key, value):
        return self.set(key, value)

    def __getitem__(self, item):
        return self.get(item)

    def __contains__(self, item) -> bool:
        return item in self.cache

    def __len__(self):
        return len(self.cache)

    def __delitem__(self, key):
        self.cache.pop(key)

    def __del__(self):
        self.clear()


def lru_cache_concurrent(cache_size: typing.Optional[int] = None,
                         override_lru_cache: typing.Optional[LRUCacheWithMetrics] = None):
    if not cache_size and override_lru_cache is None:
        raise ValueError("invalid cache size")
    concurrent_cache = {}
    lru_cache = override_lru_cache if override_lru_cache is not None else LRUCacheWithMetrics(cache_size)

    def wrapper(async_fn):

        @functools.wraps(async_fn)
        async def _inner(*args, **kwargs):
            key = (args, tuple(kwargs.items()))
            if key in lru_cache:
                return lru_cache.get(key)

            concurrent_cache[key] = concurrent_cache.get(key) or asyncio.create_task(async_fn(*args, **kwargs))

            try:
                result = await concurrent_cache[key]
                lru_cache.set(key, result)
                return result
            finally:
                concurrent_cache.pop(key, None)
        return _inner
    return wrapper


def get_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(
        purpose=ssl.Purpose.CLIENT_AUTH, capath=certifi.where()
    )


@contextlib.asynccontextmanager
async def aiohttp_request(method, url, **kwargs) -> typing.AsyncContextManager[aiohttp.ClientResponse]:
    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, **kwargs) as response:
            yield response


# the ipaddress module does not show these subnets as reserved
CARRIER_GRADE_NAT_SUBNET = ipaddress.ip_network('100.64.0.0/10')
IPV4_TO_6_RELAY_SUBNET = ipaddress.ip_network('192.88.99.0/24')


def is_valid_public_ipv4(address, allow_localhost: bool = False, allow_lan: bool = False):
    try:
        parsed_ip = ipaddress.ip_address(address)
        if parsed_ip.is_loopback and allow_localhost:
            return True
        if allow_lan and parsed_ip.is_private:
            return True
        if any((parsed_ip.version != 4, parsed_ip.is_unspecified, parsed_ip.is_link_local, parsed_ip.is_loopback,
                parsed_ip.is_multicast, parsed_ip.is_reserved, parsed_ip.is_private)):
            return False
        else:
            return not any((CARRIER_GRADE_NAT_SUBNET.supernet_of(ipaddress.ip_network(f"{address}/32")),
                            IPV4_TO_6_RELAY_SUBNET.supernet_of(ipaddress.ip_network(f"{address}/32"))))
    except (ipaddress.AddressValueError, ValueError):
        return False


async def fallback_get_external_ip():  # used if spv servers can't be used for ip detection
    try:
        async with aiohttp_request("get", "https://api.lbry.com/ip") as resp:
            response = await resp.json()
            if response['success']:
                return response['data']['ip'], None
    except Exception:
        return None, None


async def _get_external_ip(default_servers) -> typing.Tuple[typing.Optional[str], typing.Optional[str]]:
    # used if upnp is disabled or non-functioning
    from lbry.wallet.udp import SPVStatusClientProtocol  # pylint: disable=C0415

    hostname_to_ip = {}
    ip_to_hostnames = collections.defaultdict(list)

    async def resolve_spv(server, port):
        try:
            server_addr = await resolve_host(server, port, 'udp')
            hostname_to_ip[server] = (server_addr, port)
            ip_to_hostnames[(server_addr, port)].append(server)
        except Exception:
            log.exception("error looking up dns for spv servers")

    # accumulate the dns results
    await asyncio.gather(*(resolve_spv(server, port) for (server, port) in default_servers))

    loop = asyncio.get_event_loop()
    pong_responses = asyncio.Queue()
    connection = SPVStatusClientProtocol(pong_responses)
    try:
        await loop.create_datagram_endpoint(lambda: connection, ('0.0.0.0', 0))
        # could raise OSError if it cant bind
        randomized_servers = list(ip_to_hostnames.keys())
        random.shuffle(randomized_servers)
        for server in randomized_servers:
            connection.ping(server)
            try:
                _, pong = await asyncio.wait_for(pong_responses.get(), 1)
                if is_valid_public_ipv4(pong.ip_address):
                    return pong.ip_address, ip_to_hostnames[server][0]
            except asyncio.TimeoutError:
                pass
        return None, None
    finally:
        connection.close()


async def get_external_ip(default_servers) -> typing.Tuple[typing.Optional[str], typing.Optional[str]]:
    ip_from_spv_servers = await _get_external_ip(default_servers)
    if not ip_from_spv_servers[1]:
        return await fallback_get_external_ip()
    return ip_from_spv_servers


def is_running_from_bundle():
    # see https://pyinstaller.readthedocs.io/en/stable/runtime-information.html
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


class LockWithMetrics(asyncio.Lock):
    def __init__(self, acquire_metric, held_time_metric):
        super().__init__()
        self._acquire_metric = acquire_metric
        self._lock_held_time_metric = held_time_metric
        self._lock_acquired_time = None

    async def acquire(self):
        start = time.perf_counter()
        try:
            return await super().acquire()
        finally:
            self._lock_acquired_time = time.perf_counter()
            self._acquire_metric.observe(self._lock_acquired_time - start)

    def release(self):
        try:
            return super().release()
        finally:
            self._lock_held_time_metric.observe(time.perf_counter() - self._lock_acquired_time)


def get_colliding_prefix_bits(first_value: bytes, second_value: bytes):
    """
    Calculates the amount of colliding prefix bits between <first_value> and <second_value>.
    This is given by the amount of bits that are the same until the first different one (via XOR),
    starting from the most significant bit to the least significant bit.
    :param first_value: first value to compare, bigger than size.
    :param second_value: second value to compare, bigger than size.
    :return: amount of prefix colliding bits.
    """
    assert len(first_value) == len(second_value), "length should be the same"
    size = len(first_value) * 8
    first_value, second_value = int.from_bytes(first_value, "big"), int.from_bytes(second_value, "big")
    return size - (first_value ^ second_value).bit_length()
