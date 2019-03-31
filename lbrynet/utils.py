import base64
import codecs
import datetime
import random
import socket
import string
import json
import typing
import asyncio
import ssl
import logging
import ipaddress
import pkg_resources
import contextlib
import certifi
import aiohttp
import functools
from lbrynet.schema.claim import Claim
from lbrynet.cryptoutils import get_lbry_hash_obj


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


def generate_id(num=None):
    h = get_lbry_hash_obj()
    if num is not None:
        h.update(str(num).encode())
    else:
        h.update(str(random.getrandbits(512)).encode())
    return h.digest()


def version_is_greater_than(a, b):
    """Returns True if version a is more recent than version b"""
    return pkg_resources.parse_version(a) > pkg_resources.parse_version(b)


def rot13(some_str):
    return codecs.encode(some_str, 'rot_13')


def deobfuscate(obfustacated):
    return base64.b64decode(rot13(obfustacated)).decode()


def obfuscate(plain):
    return rot13(base64.b64encode(plain).decode())


def check_connection(server="lbry.io", port=80, timeout=5) -> bool:
    """Attempts to open a socket to server:port and returns True if successful."""
    log.debug('Checking connection to %s:%s', server, port)
    try:
        server = socket.gethostbyname(server)
        socket.create_connection((server, port), timeout).close()
        log.debug('Connection successful')
        return True
    except (socket.gaierror, socket.herror) as ex:
        log.warning("Failed to connect to %s:%s. Unable to resolve domain. Trying to bypass DNS",
                    server, port)
        try:
            server = "8.8.8.8"
            port = 53
            socket.create_connection((server, port), timeout).close()
            log.debug('Connection successful')
            return True
        except Exception:
            log.error("Failed to connect to %s:%s. Maybe the internet connection is not working",
                      server, port)
            return False
    except Exception:
        log.error("Failed to connect to %s:%s. Maybe the internet connection is not working",
                  server, port)
        return False


async def async_check_connection(server="lbry.io", port=80, timeout=5) -> bool:
    return await asyncio.get_event_loop().run_in_executor(None, check_connection, server, port, timeout)


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


def cancel_task(task: typing.Optional[asyncio.Task]):
    if task and not task.done():
        task.cancel()


def cancel_tasks(tasks: typing.List[typing.Optional[asyncio.Task]]):
    for task in tasks:
        cancel_task(task)


def drain_tasks(tasks: typing.List[typing.Optional[asyncio.Task]]):
    while tasks:
        cancel_task(tasks.pop())


def async_timed_cache(duration: int):
    def wrapper(fn):
        cache: typing.Dict[typing.Tuple,
                           typing.Tuple[typing.Any, float]] = {}

        @functools.wraps(fn)
        async def _inner(*args, **kwargs) -> typing.Any:
            loop = asyncio.get_running_loop()
            now = loop.time()
            key = tuple([args, tuple([tuple([k, kwargs[k]]) for k in kwargs])])
            if key in cache and (now - cache[key][1] < duration):
                return cache[key][0]
            to_cache = await fn(*args, **kwargs)
            cache[key] = to_cache, now
            return to_cache
        return _inner
    return wrapper


@async_timed_cache(300)
async def resolve_host(url: str, port: int, proto: str) -> str:
    if proto not in ['udp', 'tcp']:
        raise Exception("invalid protocol")
    try:
        if ipaddress.ip_address(url):
            return url
    except ValueError:
        pass
    loop = asyncio.get_running_loop()
    return (await loop.getaddrinfo(
        url, port,
        proto=socket.IPPROTO_TCP if proto == 'tcp' else socket.IPPROTO_UDP,
        type=socket.SOCK_STREAM if proto == 'tcp' else socket.SOCK_DGRAM
    ))[0][4][0]


def get_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(
        purpose=ssl.Purpose.CLIENT_AUTH, capath=certifi.where()
    )


@contextlib.asynccontextmanager
async def aiohttp_request(method, url, **kwargs) -> typing.AsyncContextManager[aiohttp.ClientResponse]:
    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, ssl=get_ssl_context(), **kwargs) as response:
            yield response


async def get_external_ip() -> typing.Optional[str]:  # used if upnp is disabled or non-functioning
    try:
        async with aiohttp_request("get", "https://api.lbry.io/ip") as resp:
            response = await resp.json()
            if response['success']:
                return response['data']['ip']
    except Exception as e:
        return
