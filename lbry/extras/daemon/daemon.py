import linecache
import os
import re
import asyncio
import logging
import json
import time
import inspect
import typing
import random
import tracemalloc
from decimal import Decimal
from urllib.parse import urlencode, quote
from typing import Callable, Optional, List
from binascii import hexlify, unhexlify
from traceback import format_exc
from functools import wraps, partial

import base58
from aiohttp import web
from prometheus_client import generate_latest as prom_generate_latest, Gauge, Histogram, Counter
from google.protobuf.message import DecodeError

from lbry.wallet import (
    Wallet, ENCRYPT_ON_DISK, SingleKey, HierarchicalDeterministic,
    Transaction, Output, Input, Account, database
)
from lbry.wallet.dewies import dewies_to_lbc, lbc_to_dewies, dict_values_to_lbc
from lbry.wallet.constants import TXO_TYPES, CLAIM_TYPE_NAMES
from lbry.wallet.bip32 import PrivateKey
from lbry.crypto.base58 import Base58

from lbry import utils
from lbry.conf import Config, Setting, NOT_SET
from lbry.blob.blob_file import is_valid_blobhash, BlobBuffer
from lbry.blob_exchange.downloader import download_blob
from lbry.dht.peer import make_kademlia_peer
from lbry.error import (
    DownloadSDTimeoutError, ComponentsNotStartedError, ComponentStartConditionNotMetError,
    CommandDoesNotExistError, BaseError, WalletNotFoundError, WalletAlreadyLoadedError, WalletAlreadyExistsError,
    ConflictingInputValueError, AlreadyPurchasedError, PrivateKeyNotFoundError, InputStringIsBlankError,
    InputValueError
)
from lbry.extras import system_info
from lbry.extras.daemon import analytics
from lbry.extras.daemon.components import WALLET_COMPONENT, DATABASE_COMPONENT, DHT_COMPONENT, BLOB_COMPONENT
from lbry.extras.daemon.components import FILE_MANAGER_COMPONENT, DISK_SPACE_COMPONENT, TRACKER_ANNOUNCER_COMPONENT
from lbry.extras.daemon.components import EXCHANGE_RATE_MANAGER_COMPONENT, UPNP_COMPONENT
from lbry.extras.daemon.componentmanager import RequiredCondition
from lbry.extras.daemon.componentmanager import ComponentManager
from lbry.extras.daemon.json_response_encoder import JSONResponseEncoder
from lbry.extras.daemon.undecorated import undecorated
from lbry.extras.daemon.security import ensure_request_allowed
from lbry.file_analysis import VideoFileAnalyzer
from lbry.schema.claim import Claim
from lbry.schema.url import URL, normalize_name


if typing.TYPE_CHECKING:
    from lbry.blob.blob_manager import BlobManager
    from lbry.dht.node import Node
    from lbry.extras.daemon.components import UPnPComponent, DiskSpaceManager
    from lbry.extras.daemon.exchange_rate_manager import ExchangeRateManager
    from lbry.extras.daemon.storage import SQLiteStorage
    from lbry.wallet import WalletManager, Ledger
    from lbry.file.file_manager import FileManager

log = logging.getLogger(__name__)

RANGE_FIELDS = {
    'height', 'creation_height', 'activation_height', 'expiration_height',
    'timestamp', 'creation_timestamp', 'duration', 'release_time', 'fee_amount',
    'tx_position', 'repost_count', 'limit_claims_per_channel',
    'amount', 'effective_amount', 'support_amount',
    'trending_score', 'censor_type', 'tx_num'
}
MY_RANGE_FIELDS = RANGE_FIELDS - {"limit_claims_per_channel"}
REPLACEMENTS = {
    'claim_name': 'normalized_name',
    'name': 'normalized_name',
    'txid': 'tx_id',
    'nout': 'tx_nout',
    'trending_group': 'trending_score',
    'trending_mixed': 'trending_score',
    'trending_global': 'trending_score',
    'trending_local': 'trending_score',
    'reposted': 'repost_count',
    'stream_types': 'stream_type',
    'media_types': 'media_type',
    'valid_channel_signature': 'is_signature_valid'
}


def is_transactional_function(name):
    for action in ('create', 'update', 'abandon', 'send', 'fund'):
        if action in name:
            return True


def requires(*components, **conditions):
    if conditions and ["conditions"] != list(conditions.keys()):
        raise SyntaxError("invalid conditions argument")
    condition_names = conditions.get("conditions", [])

    def _wrap(method):
        @wraps(method)
        def _inner(*args, **kwargs):
            component_manager = args[0].component_manager
            for condition_name in condition_names:
                condition_result, err_msg = component_manager.evaluate_condition(condition_name)
                if not condition_result:
                    raise ComponentStartConditionNotMetError(err_msg)
            if not component_manager.all_components_running(*components):
                raise ComponentsNotStartedError(
                    f"the following required components have not yet started: {json.dumps(components)}"
                )
            return method(*args, **kwargs)

        return _inner

    return _wrap


def deprecated(new_command=None):
    def _deprecated_wrapper(f):
        f.new_command = new_command
        f._deprecated = True
        return f

    return _deprecated_wrapper


INITIALIZING_CODE = 'initializing'

# TODO: make this consistent with the stages in Downloader.py
DOWNLOAD_METADATA_CODE = 'downloading_metadata'
DOWNLOAD_TIMEOUT_CODE = 'timeout'
DOWNLOAD_RUNNING_CODE = 'running'
DOWNLOAD_STOPPED_CODE = 'stopped'
STREAM_STAGES = [
    (INITIALIZING_CODE, 'Initializing'),
    (DOWNLOAD_METADATA_CODE, 'Downloading metadata'),
    (DOWNLOAD_RUNNING_CODE, 'Started %s, got %s/%s blobs, stream status: %s'),
    (DOWNLOAD_STOPPED_CODE, 'Paused stream'),
    (DOWNLOAD_TIMEOUT_CODE, 'Stream timed out')
]

SHORT_ID_LEN = 20
MAX_UPDATE_FEE_ESTIMATE = 0.3
DEFAULT_PAGE_SIZE = 20

VALID_FULL_CLAIM_ID = re.compile('[0-9a-fA-F]{40}')


def encode_pagination_doc(items):
    return {
        "page": "Page number of the current items.",
        "page_size": "Number of items to show on a page.",
        "total_pages": "Total number of pages.",
        "total_items": "Total number of items.",
        "items": [items],
    }


async def paginate_rows(get_records: Callable, get_record_count: Optional[Callable],
                        page: Optional[int], page_size: Optional[int], **constraints):
    page = max(1, page or 1)
    page_size = max(1, page_size or DEFAULT_PAGE_SIZE)
    constraints.update({
        "offset": page_size * (page - 1),
        "limit": page_size
    })
    items = await get_records(**constraints)
    result = {"items": items, "page": page, "page_size": page_size}
    if get_record_count is not None:
        total_items = await get_record_count(**constraints)
        result["total_pages"] = int((total_items + (page_size - 1)) / page_size)
        result["total_items"] = total_items
    return result


def paginate_list(items: List, page: Optional[int], page_size: Optional[int]):
    page = max(1, page or 1)
    page_size = max(1, page_size or DEFAULT_PAGE_SIZE)
    total_items = len(items)
    offset = page_size * (page - 1)
    subitems = []
    if offset <= total_items:
        subitems = items[offset:offset+page_size]
    return {
        "items": subitems,
        "total_pages": int((total_items + (page_size - 1)) / page_size),
        "total_items": total_items,
        "page": page, "page_size": page_size
    }


def fix_kwargs_for_hub(**kwargs):
    repeated_fields = {"media_type", "stream_type", "claim_type"}
    value_fields = {"tx_nout", "has_source", "is_signature_valid"}
    opcodes = {'=': 0, '<=': 1, '>=': 2, '<': 3, '>': 4}
    for key, value in list(kwargs.items()):
        if value in (None, [], False):
            kwargs.pop(key)
            continue
        if key in REPLACEMENTS:
            kwargs[REPLACEMENTS[key]] = kwargs.pop(key)
            key = REPLACEMENTS[key]

        if key == "normalized_name":
            kwargs[key] = normalize_name(value)
        if key == "limit_claims_per_channel":
            value = kwargs.pop("limit_claims_per_channel") or 0
            if value > 0:
                kwargs["limit_claims_per_channel"] = value
        elif key == "invalid_channel_signature":
            kwargs["is_signature_valid"] = {"value": not kwargs.pop("invalid_channel_signature")}
        elif key == "has_no_source":
            kwargs["has_source"] = {"value": not kwargs.pop("has_no_source")}
        elif key in value_fields:
            kwargs[key] = {"value": value} if not isinstance(value, dict) else value
        elif key in repeated_fields and isinstance(value, str):
            kwargs[key] = [value]
        elif key in ("claim_id", "channel_id"):
            kwargs[key] = {"invert": False, "value": [kwargs[key]]}
        elif key in ("claim_ids", "channel_ids"):
            kwargs[key[:-1]] = {"invert": False, "value": kwargs.pop(key)}
        elif key == "not_channel_ids":
            kwargs["channel_id"] = {"invert": True, "value": kwargs.pop("not_channel_ids")}
        elif key in MY_RANGE_FIELDS:
            constraints = []
            for val in value if isinstance(value, list) else [value]:
                operator = '='
                if isinstance(val, str) and val[0] in opcodes:
                    operator_length = 2 if val[:2] in opcodes else 1
                    operator, val = val[:operator_length], val[operator_length:]
                val = [int(val if key != 'fee_amount' else Decimal(val)*1000)]
                constraints.append({"op": opcodes[operator], "value": val})
            kwargs[key] = constraints
        elif key == 'order_by':  # TODO: remove this after removing support for old trending args from the api
            value = value if isinstance(value, list) else [value]
            new_value = []
            for new_v in value:
                migrated = new_v if new_v not in (
                    'trending_mixed', 'trending_local', 'trending_global', 'trending_group'
                ) else 'trending_score'
                if migrated not in new_value:
                    new_value.append(migrated)
            kwargs[key] = new_value
    return kwargs


DHT_HAS_CONTACTS = "dht_has_contacts"


class DHTHasContacts(RequiredCondition):
    name = DHT_HAS_CONTACTS
    component = DHT_COMPONENT
    message = "your node is not connected to the dht"

    @staticmethod
    def evaluate(component):
        return len(component.contacts) > 0


class JSONRPCError:
    # http://www.jsonrpc.org/specification#error_object
    CODE_PARSE_ERROR = -32700  # Invalid JSON. Error while parsing the JSON text.
    CODE_INVALID_REQUEST = -32600  # The JSON sent is not a valid Request object.
    CODE_METHOD_NOT_FOUND = -32601  # The method does not exist / is not available.
    CODE_INVALID_PARAMS = -32602  # Invalid method parameter(s).
    CODE_INTERNAL_ERROR = -32603  # Internal JSON-RPC error (I think this is like a 500?)
    CODE_APPLICATION_ERROR = -32500  # Generic error with our app??
    CODE_AUTHENTICATION_ERROR = -32501  # Authentication failed

    MESSAGES = {
        CODE_PARSE_ERROR: "Parse Error. Data is not valid JSON.",
        CODE_INVALID_REQUEST: "JSON data is not a valid Request",
        CODE_METHOD_NOT_FOUND: "Method Not Found",
        CODE_INVALID_PARAMS: "Invalid Params",
        CODE_INTERNAL_ERROR: "Internal Error",
        CODE_AUTHENTICATION_ERROR: "Authentication Failed",
    }

    HTTP_CODES = {
        CODE_INVALID_REQUEST: 400,
        CODE_PARSE_ERROR: 400,
        CODE_INVALID_PARAMS: 400,
        CODE_METHOD_NOT_FOUND: 404,
        CODE_INTERNAL_ERROR: 500,
        CODE_APPLICATION_ERROR: 500,
        CODE_AUTHENTICATION_ERROR: 401,
    }

    def __init__(self, code: int, message: str, data: dict = None):
        assert code and isinstance(code, int), "'code' must be an int"
        assert message and isinstance(message, str), "'message' must be a string"
        assert data is None or isinstance(data, dict), "'data' must be None or a dict"
        self.code = code
        self.message = message
        self.data = data or {}

    def to_dict(self):
        return {
            'code': self.code,
            'message': self.message,
            'data': self.data,
        }

    @staticmethod
    def filter_traceback(traceback):
        result = []
        if traceback is not None:
            result = trace_lines = traceback.split("\n")
            for i, t in enumerate(trace_lines):
                if "--- <exception caught here> ---" in t:
                    if len(trace_lines) > i + 1:
                        result = [j for j in trace_lines[i + 1:] if j]
                        break
        return result

    @classmethod
    def create_command_exception(cls, command, args, kwargs, exception, traceback):
        if 'password' in kwargs and isinstance(kwargs['password'], str):
            kwargs['password'] = '*'*len(kwargs['password'])
        return cls(
            cls.CODE_APPLICATION_ERROR, str(exception), {
                'name': exception.__class__.__name__,
                'traceback': cls.filter_traceback(traceback),
                'command': command,
                'args': args,
                'kwargs': kwargs,
            }
        )


class UnknownAPIMethodError(Exception):
    pass


def jsonrpc_dumps_pretty(obj, **kwargs):
    if isinstance(obj, JSONRPCError):
        data = {"jsonrpc": "2.0", "error": obj.to_dict()}
    else:
        data = {"jsonrpc": "2.0", "result": obj}
    return json.dumps(data, cls=JSONResponseEncoder, sort_keys=True, indent=2, **kwargs) + "\n"


def trap(err, *to_trap):
    err.trap(*to_trap)


class JSONRPCServerType(type):
    def __new__(mcs, name, bases, newattrs):
        klass = type.__new__(mcs, name, bases, newattrs)
        klass.callable_methods = {}
        klass.deprecated_methods = {}

        for methodname in dir(klass):
            if methodname.startswith("jsonrpc_"):
                method = getattr(klass, methodname)
                if not hasattr(method, '_deprecated'):
                    klass.callable_methods.update({methodname.split("jsonrpc_")[1]: method})
                else:
                    klass.deprecated_methods.update({methodname.split("jsonrpc_")[1]: method})
        return klass


HISTOGRAM_BUCKETS = (
    .005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0, 15.0, 20.0, 30.0, 60.0, float('inf')
)


class Daemon(metaclass=JSONRPCServerType):
    """
    LBRYnet daemon, a jsonrpc interface to lbry functions
    """
    callable_methods: dict
    deprecated_methods: dict

    pending_requests_metric = Gauge(
        "pending_requests", "Number of running api requests", namespace="daemon_api",
        labelnames=("method",)
    )

    requests_count_metric = Counter(
        "requests_count", "Number of requests received", namespace="daemon_api",
        labelnames=("method",)
    )
    failed_request_metric = Counter(
        "failed_request_count", "Number of failed requests", namespace="daemon_api",
        labelnames=("method",)
    )
    cancelled_request_metric = Counter(
        "cancelled_request_count", "Number of cancelled requests", namespace="daemon_api",
        labelnames=("method",)
    )
    response_time_metric = Histogram(
        "response_time", "Response times", namespace="daemon_api", buckets=HISTOGRAM_BUCKETS,
        labelnames=("method",)
    )

    def __init__(self, conf: Config, component_manager: typing.Optional[ComponentManager] = None):
        self.conf = conf
        self.platform_info = system_info.get_platform()
        self._video_file_analyzer = VideoFileAnalyzer(conf)
        self._node_id = None
        self._installation_id = None
        self.session_id = base58.b58encode(utils.generate_id()).decode()
        self.analytics_manager = analytics.AnalyticsManager(conf, self.installation_id, self.session_id)
        self.component_manager = component_manager or ComponentManager(
            conf, analytics_manager=self.analytics_manager,
            skip_components=conf.components_to_skip or []
        )
        self.component_startup_task = None

        logging.getLogger('aiohttp.access').setLevel(logging.WARN)
        rpc_app = web.Application()
        rpc_app.router.add_get('/lbryapi', self.handle_old_jsonrpc)
        rpc_app.router.add_post('/lbryapi', self.handle_old_jsonrpc)
        rpc_app.router.add_post('/', self.handle_old_jsonrpc)
        rpc_app.router.add_options('/', self.add_cors_headers)
        self.rpc_runner = web.AppRunner(rpc_app)

        streaming_app = web.Application()
        streaming_app.router.add_get('/get/{claim_name}', self.handle_stream_get_request)
        streaming_app.router.add_get('/get/{claim_name}/{claim_id}', self.handle_stream_get_request)
        streaming_app.router.add_get('/stream/{sd_hash}', self.handle_stream_range_request)
        self.streaming_runner = web.AppRunner(streaming_app)

        prom_app = web.Application()
        prom_app.router.add_get('/metrics', self.handle_metrics_get_request)
        self.metrics_runner = web.AppRunner(prom_app)

    @property
    def dht_node(self) -> typing.Optional['Node']:
        return self.component_manager.get_component(DHT_COMPONENT)

    @property
    def wallet_manager(self) -> typing.Optional['WalletManager']:
        return self.component_manager.get_component(WALLET_COMPONENT)

    @property
    def storage(self) -> typing.Optional['SQLiteStorage']:
        return self.component_manager.get_component(DATABASE_COMPONENT)

    @property
    def file_manager(self) -> typing.Optional['FileManager']:
        return self.component_manager.get_component(FILE_MANAGER_COMPONENT)

    @property
    def exchange_rate_manager(self) -> typing.Optional['ExchangeRateManager']:
        return self.component_manager.get_component(EXCHANGE_RATE_MANAGER_COMPONENT)

    @property
    def blob_manager(self) -> typing.Optional['BlobManager']:
        return self.component_manager.get_component(BLOB_COMPONENT)

    @property
    def disk_space_manager(self) -> typing.Optional['DiskSpaceManager']:
        return self.component_manager.get_component(DISK_SPACE_COMPONENT)

    @property
    def upnp(self) -> typing.Optional['UPnPComponent']:
        return self.component_manager.get_component(UPNP_COMPONENT)

    @classmethod
    def get_api_definitions(cls):
        prefix = 'jsonrpc_'
        not_grouped = ['routing_table_get', 'ffmpeg_find']
        api = {
            'groups': {
                group_name[:-len('_DOC')].lower(): getattr(cls, group_name).strip()
                for group_name in dir(cls) if group_name.endswith('_DOC')
            },
            'commands': {}
        }
        for jsonrpc_method in dir(cls):
            if jsonrpc_method.startswith(prefix):
                full_name = jsonrpc_method[len(prefix):]
                method = getattr(cls, jsonrpc_method)
                if full_name in not_grouped:
                    name_parts = [full_name]
                else:
                    name_parts = full_name.split('_', 1)
                if len(name_parts) == 1:
                    group = None
                    name, = name_parts
                elif len(name_parts) == 2:
                    group, name = name_parts
                    assert group in api['groups'], \
                        f"Group {group} does not have doc string for command {full_name}."
                else:
                    raise NameError(f'Could not parse method name: {jsonrpc_method}')
                api['commands'][full_name] = {
                    'api_method_name': full_name,
                    'name': name,
                    'group': group,
                    'doc': method.__doc__,
                    'method': method,
                }
                if hasattr(method, '_deprecated'):
                    api['commands'][full_name]['replaced_by'] = method.new_command

        for command in api['commands'].values():
            if 'replaced_by' in command:
                command['replaced_by'] = api['commands'][command['replaced_by']]

        return api

    @property
    def db_revision_file_path(self):
        return os.path.join(self.conf.data_dir, 'db_revision')

    @property
    def installation_id(self):
        install_id_filename = os.path.join(self.conf.data_dir, "install_id")
        if not self._installation_id:
            if os.path.isfile(install_id_filename):
                with open(install_id_filename, "r") as install_id_file:
                    self._installation_id = str(install_id_file.read()).strip()
        if not self._installation_id:
            self._installation_id = base58.b58encode(utils.generate_id()).decode()
            with open(install_id_filename, "w") as install_id_file:
                install_id_file.write(self._installation_id)
        return self._installation_id

    def ensure_data_dir(self):
        if not os.path.isdir(self.conf.data_dir):
            os.makedirs(self.conf.data_dir)
        if not os.path.isdir(os.path.join(self.conf.data_dir, "blobfiles")):
            os.makedirs(os.path.join(self.conf.data_dir, "blobfiles"))
        return self.conf.data_dir

    def ensure_wallet_dir(self):
        if not os.path.isdir(self.conf.wallet_dir):
            os.makedirs(self.conf.wallet_dir)

    def ensure_download_dir(self):
        if not os.path.isdir(self.conf.download_dir):
            os.makedirs(self.conf.download_dir)

    async def start(self):
        log.info("Starting LBRYNet Daemon")
        log.debug("Settings: %s", json.dumps(self.conf.settings_dict, indent=2))
        log.info("Platform: %s", json.dumps(self.platform_info, indent=2))

        await self.analytics_manager.send_server_startup()
        await self.rpc_runner.setup()
        await self.streaming_runner.setup()
        await self.metrics_runner.setup()

        try:
            rpc_site = web.TCPSite(self.rpc_runner, self.conf.api_host, self.conf.api_port, shutdown_timeout=.5)
            await rpc_site.start()
            log.info('RPC server listening on TCP %s:%i', *rpc_site._server.sockets[0].getsockname()[:2])
        except OSError as e:
            log.error('RPC server failed to bind TCP %s:%i', self.conf.api_host, self.conf.api_port)
            await self.analytics_manager.send_server_startup_error(str(e))
            raise SystemExit()

        try:
            streaming_site = web.TCPSite(self.streaming_runner, self.conf.streaming_host, self.conf.streaming_port,
                                         shutdown_timeout=.5)
            await streaming_site.start()
            log.info('media server listening on TCP %s:%i', *streaming_site._server.sockets[0].getsockname()[:2])

        except OSError as e:
            log.error('media server failed to bind TCP %s:%i', self.conf.streaming_host, self.conf.streaming_port)
            await self.analytics_manager.send_server_startup_error(str(e))
            raise SystemExit()

        if self.conf.prometheus_port:
            try:
                prom_site = web.TCPSite(self.metrics_runner, "0.0.0.0", self.conf.prometheus_port, shutdown_timeout=.5)
                await prom_site.start()
                log.info('metrics server listening on TCP %s:%i', *prom_site._server.sockets[0].getsockname()[:2])
            except OSError as e:
                log.error('metrics server failed to bind TCP :%i', self.conf.prometheus_port)
                await self.analytics_manager.send_server_startup_error(str(e))
                raise SystemExit()

        try:
            await self.initialize()
        except asyncio.CancelledError:
            log.info("shutting down before finished starting")
            await self.analytics_manager.send_server_startup_error("shutting down before finished starting")
            raise
        except Exception as e:
            await self.analytics_manager.send_server_startup_error(str(e))
            log.exception('Failed to start lbrynet')
            raise SystemExit()

        await self.analytics_manager.send_server_startup_success()

    async def initialize(self):
        self.ensure_data_dir()
        self.ensure_wallet_dir()
        self.ensure_download_dir()
        if not self.analytics_manager.is_started:
            await self.analytics_manager.start()
        self.component_startup_task = asyncio.create_task(self.component_manager.start())
        await self.component_startup_task

    async def stop(self):
        if self.component_startup_task is not None:
            if self.component_startup_task.done():
                await self.component_manager.stop()
            else:
                self.component_startup_task.cancel()
                # the wallet component might have not started
                try:
                    wallet_component = self.component_manager.get_actual_component('wallet')
                except NameError:
                    pass
                else:
                    await wallet_component.stop()
                await self.component_manager.stop()
        log.info("stopped api components")
        await self.rpc_runner.cleanup()
        await self.streaming_runner.cleanup()
        await self.metrics_runner.cleanup()
        log.info("stopped api server")
        if self.analytics_manager.is_started:
            self.analytics_manager.stop()
        log.info("finished shutting down")

    async def add_cors_headers(self, request):
        if self.conf.allowed_origin:
            return web.Response(
                headers={
                    'Access-Control-Allow-Origin': self.conf.allowed_origin,
                    'Access-Control-Allow-Methods': self.conf.allowed_origin,
                    'Access-Control-Allow-Headers': self.conf.allowed_origin,
                }
            )
        return None

    async def handle_old_jsonrpc(self, request):
        ensure_request_allowed(request, self.conf)
        data = await request.json()
        params = data.get('params', {})
        include_protobuf = params.pop('include_protobuf', False) if isinstance(params, dict) else False
        result = await self._process_rpc_call(data)
        ledger = None
        if 'wallet' in self.component_manager.get_components_status():
            # self.ledger only available if wallet component is not skipped
            ledger = self.ledger
        try:
            encoded_result = jsonrpc_dumps_pretty(
                result, ledger=ledger, include_protobuf=include_protobuf)
        except Exception:
            log.exception('Failed to encode JSON RPC result:')
            encoded_result = jsonrpc_dumps_pretty(JSONRPCError(
                JSONRPCError.CODE_APPLICATION_ERROR,
                'After successfully executing the command, failed to encode result for JSON RPC response.',
                {'traceback': format_exc()}
            ), ledger=ledger)
        headers = {}
        if self.conf.allowed_origin:
            headers.update({
                'Access-Control-Allow-Origin': self.conf.allowed_origin,
                'Access-Control-Allow-Methods': self.conf.allowed_origin,
                'Access-Control-Allow-Headers': self.conf.allowed_origin,
            })
        return web.Response(
            text=encoded_result,
            headers=headers,
            content_type='application/json'
        )

    async def handle_metrics_get_request(self, request: web.Request):
        try:
            return web.Response(
                text=prom_generate_latest().decode(),
                content_type='text/plain; version=0.0.4'
            )
        except Exception:
            log.exception('could not generate prometheus data')
            raise

    async def handle_stream_get_request(self, request: web.Request):
        if not self.conf.streaming_get:
            log.warning("streaming_get is disabled, rejecting request")
            raise web.HTTPForbidden()
        name_and_claim_id = request.path.split("/get/")[1]
        if "/" not in name_and_claim_id:
            uri = f"lbry://{name_and_claim_id}"
        else:
            name, claim_id = name_and_claim_id.split("/")
            uri = f"lbry://{name}#{claim_id}"
        if not self.file_manager.started.is_set():
            await self.file_manager.started.wait()
        stream = await self.jsonrpc_get(uri)
        if isinstance(stream, dict):
            raise web.HTTPServerError(text=stream['error'])
        raise web.HTTPFound(f"/stream/{stream.sd_hash}")

    async def handle_stream_range_request(self, request: web.Request):
        try:
            return await self._handle_stream_range_request(request)
        except web.HTTPException as err:
            log.warning("http code during /stream range request: %s", err)
            raise err
        except asyncio.CancelledError:
            # if not excepted here, it would bubble up the error to the console. every time you closed
            # a running tab, you'd get this error in the console
            log.debug("/stream range request cancelled")
        except Exception:
            log.exception("error handling /stream range request")
            raise
        finally:
            log.debug("finished handling /stream range request")

    async def _handle_stream_range_request(self, request: web.Request):
        sd_hash = request.path.split("/stream/")[1]
        if not self.file_manager.started.is_set():
            await self.file_manager.started.wait()
        if sd_hash not in self.file_manager.streams:
            return web.HTTPNotFound()
        return await self.file_manager.stream_partial_content(request, sd_hash)

    async def _process_rpc_call(self, data):
        args = data.get('params', {})

        try:
            function_name = data['method']
        except KeyError:
            return JSONRPCError(
                JSONRPCError.CODE_METHOD_NOT_FOUND,
                "Missing 'method' value in request."
            )

        try:
            method = self._get_jsonrpc_method(function_name)
        except UnknownAPIMethodError:
            return JSONRPCError(
                JSONRPCError.CODE_METHOD_NOT_FOUND,
                str(CommandDoesNotExistError(function_name))
            )

        if args in ([{}], []):
            _args, _kwargs = (), {}
        elif isinstance(args, dict):
            _args, _kwargs = (), args
        elif isinstance(args, list) and len(args) == 1 and isinstance(args[0], dict):
            # TODO: this is for backwards compatibility. Remove this once API and UI are updated
            # TODO: also delete EMPTY_PARAMS then
            _args, _kwargs = (), args[0]
        elif isinstance(args, list) and len(args) == 2 and \
                isinstance(args[0], list) and isinstance(args[1], dict):
            _args, _kwargs = args
        else:
            return JSONRPCError(
                JSONRPCError.CODE_INVALID_PARAMS,
                f"Invalid parameters format: {args}"
            )

        if is_transactional_function(function_name):
            log.info("%s %s %s", function_name, _args, _kwargs)

        params_error, erroneous_params = self._check_params(method, _args, _kwargs)
        if params_error is not None:
            params_error_message = '{} for {} command: {}'.format(
                params_error, function_name, ', '.join(erroneous_params)
            )
            log.warning(params_error_message)
            return JSONRPCError(
                JSONRPCError.CODE_INVALID_PARAMS,
                params_error_message,
            )
        self.pending_requests_metric.labels(method=function_name).inc()
        self.requests_count_metric.labels(method=function_name).inc()
        start = time.perf_counter()
        try:
            result = method(self, *_args, **_kwargs)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except asyncio.CancelledError:
            self.cancelled_request_metric.labels(method=function_name).inc()
            log.info("cancelled API call for: %s", function_name)
            raise
        except Exception as e:  # pylint: disable=broad-except
            self.failed_request_metric.labels(method=function_name).inc()
            if not isinstance(e, BaseError):
                log.exception("error handling api request")
            else:
                log.error("error handling api request: %s", e)
            return JSONRPCError.create_command_exception(
                command=function_name, args=_args, kwargs=_kwargs, exception=e, traceback=format_exc()
            )
        finally:
            self.pending_requests_metric.labels(method=function_name).dec()
            self.response_time_metric.labels(method=function_name).observe(time.perf_counter() - start)

    def _verify_method_is_callable(self, function_path):
        if function_path not in self.callable_methods:
            raise UnknownAPIMethodError(function_path)

    def _get_jsonrpc_method(self, function_path):
        if function_path in self.deprecated_methods:
            new_command = self.deprecated_methods[function_path].new_command
            log.warning('API function \"%s\" is deprecated, please update to use \"%s\"',
                        function_path, new_command)
            function_path = new_command
        self._verify_method_is_callable(function_path)
        return self.callable_methods.get(function_path)

    @staticmethod
    def _check_params(function, args_tup, args_dict):
        argspec = inspect.getfullargspec(undecorated(function))
        num_optional_params = 0 if argspec.defaults is None else len(argspec.defaults)

        duplicate_params = [
            duplicate_param
            for duplicate_param in argspec.args[1:len(args_tup) + 1]
            if duplicate_param in args_dict
        ]

        if duplicate_params:
            return 'Duplicate parameters', duplicate_params

        missing_required_params = [
            required_param
            for required_param in argspec.args[len(args_tup) + 1:-num_optional_params]
            if required_param not in args_dict
        ]
        if len(missing_required_params) > 0:
            return 'Missing required parameters', missing_required_params

        extraneous_params = [] if argspec.varkw is not None else [
            extra_param
            for extra_param in args_dict
            if extra_param not in argspec.args[1:]
        ]
        if len(extraneous_params) > 0:
            return 'Extraneous parameters', extraneous_params

        return None, None

    @property
    def ledger(self) -> Optional['Ledger']:
        try:
            return self.wallet_manager.default_account.ledger
        except AttributeError:
            return None

    async def get_est_cost_from_uri(self, uri: str) -> typing.Optional[float]:
        """
        Resolve a name and return the estimated stream cost
        """

        resolved = await self.resolve([], uri)
        if resolved:
            claim_response = resolved[uri]
        else:
            claim_response = None

        if claim_response and 'claim' in claim_response:
            if 'value' in claim_response['claim'] and claim_response['claim']['value'] is not None:
                claim_value = Claim.from_bytes(claim_response['claim']['value'])
                if not claim_value.stream.has_fee:
                    return 0.0
                return round(
                    self.exchange_rate_manager.convert_currency(
                        claim_value.stream.fee.currency, "LBC", claim_value.stream.fee.amount
                    ), 5
                )
            else:
                log.warning("Failed to estimate cost for %s", uri)

    ############################################################################
    #                                                                          #
    #                JSON-RPC API methods start here                           #
    #                                                                          #
    ############################################################################

    def jsonrpc_stop(self):  # pylint: disable=no-self-use
        """
        Stop lbrynet API server.

        Usage:
            stop

        Options:
            None

        Returns:
            (string) Shutdown message
        """

        def shutdown():
            raise web.GracefulExit()

        log.info("Shutting down lbrynet daemon")
        asyncio.get_event_loop().call_later(0, shutdown)
        return "Shutting down"

    async def jsonrpc_ffmpeg_find(self):
        """
        Get ffmpeg installation information

        Usage:
            ffmpeg_find

        Options:
            None

        Returns:
            (dict) Dictionary of ffmpeg information
            {
                'available': (bool) found ffmpeg,
                'which': (str) path to ffmpeg,
                'analyze_audio_volume': (bool) should ffmpeg analyze audio
            }
        """
        return await self._video_file_analyzer.status(reset=True, recheck=True)

    async def jsonrpc_status(self):
        """
        Get daemon status

        Usage:
            status

        Options:
            None

        Returns:
            (dict) lbrynet-daemon status
            {
                'installation_id': (str) installation id - base58,
                'is_running': (bool),
                'skipped_components': (list) [names of skipped components (str)],
                'startup_status': { Does not include components which have been skipped
                    'blob_manager': (bool),
                    'blockchain_headers': (bool),
                    'database': (bool),
                    'dht': (bool),
                    'exchange_rate_manager': (bool),
                    'hash_announcer': (bool),
                    'peer_protocol_server': (bool),
                    'file_manager': (bool),
                    'libtorrent_component': (bool),
                    'upnp': (bool),
                    'wallet': (bool),
                },
                'connection_status': {
                    'code': (str) connection status code,
                    'message': (str) connection status message
                },
                'blockchain_headers': {
                    'downloading_headers': (bool),
                    'download_progress': (float) 0-100.0
                },
                'wallet': {
                    'connected': (str) host and port of the connected spv server,
                    'blocks': (int) local blockchain height,
                    'blocks_behind': (int) remote_height - local_height,
                    'best_blockhash': (str) block hash of most recent block,
                    'is_encrypted': (bool),
                    'is_locked': (bool),
                    'connected_servers': (list) [
                        {
                            'host': (str) server hostname,
                            'port': (int) server port,
                            'latency': (int) milliseconds
                        }
                    ],
                },
                'libtorrent_component': {
                    'running': (bool) libtorrent was detected and started successfully,
                },
                'dht': {
                    'node_id': (str) lbry dht node id - hex encoded,
                    'peers_in_routing_table': (int) the number of peers in the routing table,
                },
                'blob_manager': {
                    'finished_blobs': (int) number of finished blobs in the blob manager,
                    'connections': {
                        'incoming_bps': {
                            <source ip and tcp port>: (int) bytes per second received,
                        },
                        'outgoing_bps': {
                            <destination ip and tcp port>: (int) bytes per second sent,
                        },
                        'total_outgoing_mps': (float) megabytes per second sent,
                        'total_incoming_mps': (float) megabytes per second received,
                        'max_outgoing_mbs': (float) maximum bandwidth (megabytes per second) sent, since the
                                            daemon was started
                        'max_incoming_mbs': (float) maximum bandwidth (megabytes per second) received, since the
                                            daemon was started
                        'total_sent' : (int) total number of bytes sent since the daemon was started
                        'total_received' : (int) total number of bytes received since the daemon was started
                    }
                },
                'hash_announcer': {
                    'announce_queue_size': (int) number of blobs currently queued to be announced
                },
                'file_manager': {
                    'managed_files': (int) count of files in the stream manager,
                },
                'upnp': {
                    'aioupnp_version': (str),
                    'redirects': {
                        <TCP | UDP>: (int) external_port,
                    },
                    'gateway': (str) manufacturer and model,
                    'dht_redirect_set': (bool),
                    'peer_redirect_set': (bool),
                    'external_ip': (str) external ip address,
                }
            }
        """
        ffmpeg_status = await self._video_file_analyzer.status()
        running_components = self.component_manager.get_components_status()
        response = {
            'installation_id': self.installation_id,
            'is_running': all(running_components.values()),
            'skipped_components': self.component_manager.skip_components,
            'startup_status': running_components,
            'ffmpeg_status': ffmpeg_status
        }
        for component in self.component_manager.components:
            status = await component.get_status()
            if status:
                response[component.component_name] = status
        return response

    def jsonrpc_version(self):  # pylint: disable=no-self-use
        """
        Get lbrynet API server version information

        Usage:
            version

        Options:
            None

        Returns:
            (dict) Dictionary of lbry version information
            {
                'processor': (str) processor type,
                'python_version': (str) python version,
                'platform': (str) platform string,
                'os_release': (str) os release string,
                'os_system': (str) os name,
                'version': (str) lbrynet version,
                'build': (str) "dev" | "qa" | "rc" | "release",
            }
        """
        return self.platform_info

    @requires(WALLET_COMPONENT)
    async def jsonrpc_resolve(self, urls: typing.Union[str, list], wallet_id=None, **kwargs):
        """
        Get the claim that a URL refers to.

        Usage:
            resolve <urls>... [--wallet_id=<wallet_id>]
                    [--include_purchase_receipt]
                    [--include_is_my_output]
                    [--include_sent_supports]
                    [--include_sent_tips]
                    [--include_received_tips]
                    [--new_sdk_server=<new_sdk_server>]

        Options:
            --urls=<urls>              : (str, list) one or more urls to resolve
            --wallet_id=<wallet_id>    : (str) wallet to check for claim purchase receipts
           --new_sdk_server=<new_sdk_server> : (str) URL of the new SDK server (EXPERIMENTAL)
           --include_purchase_receipt  : (bool) lookup and include a receipt if this wallet
                                                has purchased the claim being resolved
            --include_is_my_output     : (bool) lookup and include a boolean indicating
                                                if claim being resolved is yours
            --include_sent_supports    : (bool) lookup and sum the total amount
                                                of supports you've made to this claim
            --include_sent_tips        : (bool) lookup and sum the total amount
                                                of tips you've made to this claim
                                                (only makes sense when claim is not yours)
            --include_received_tips    : (bool) lookup and sum the total amount
                                                of tips you've received to this claim
                                                (only makes sense when claim is yours)

        Returns:
            Dictionary of results, keyed by url
            '<url>': {
                    If a resolution error occurs:
                    'error': Error message

                    If the url resolves to a channel or a claim in a channel:
                    'certificate': {
                        'address': (str) claim address,
                        'amount': (float) claim amount,
                        'effective_amount': (float) claim amount including supports,
                        'claim_id': (str) claim id,
                        'claim_sequence': (int) claim sequence number (or -1 if unknown),
                        'decoded_claim': (bool) whether or not the claim value was decoded,
                        'height': (int) claim height,
                        'confirmations': (int) claim depth,
                        'timestamp': (int) timestamp of the block that included this claim tx,
                        'has_signature': (bool) included if decoded_claim
                        'name': (str) claim name,
                        'permanent_url': (str) permanent url of the certificate claim,
                        'supports: (list) list of supports [{'txid': (str) txid,
                                                             'nout': (int) nout,
                                                             'amount': (float) amount}],
                        'txid': (str) claim txid,
                        'nout': (str) claim nout,
                        'signature_is_valid': (bool), included if has_signature,
                        'value': ClaimDict if decoded, otherwise hex string
                    }

                    If the url resolves to a channel:
                    'claims_in_channel': (int) number of claims in the channel,

                    If the url resolves to a claim:
                    'claim': {
                        'address': (str) claim address,
                        'amount': (float) claim amount,
                        'effective_amount': (float) claim amount including supports,
                        'claim_id': (str) claim id,
                        'claim_sequence': (int) claim sequence number (or -1 if unknown),
                        'decoded_claim': (bool) whether or not the claim value was decoded,
                        'height': (int) claim height,
                        'depth': (int) claim depth,
                        'has_signature': (bool) included if decoded_claim
                        'name': (str) claim name,
                        'permanent_url': (str) permanent url of the claim,
                        'channel_name': (str) channel name if claim is in a channel
                        'supports: (list) list of supports [{'txid': (str) txid,
                                                             'nout': (int) nout,
                                                             'amount': (float) amount}]
                        'txid': (str) claim txid,
                        'nout': (str) claim nout,
                        'signature_is_valid': (bool), included if has_signature,
                        'value': ClaimDict if decoded, otherwise hex string
                    }
            }
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)

        if isinstance(urls, str):
            urls = [urls]

        results = {}

        valid_urls = set()
        for url in urls:
            try:
                URL.parse(url)
                valid_urls.add(url)
            except ValueError:
                results[url] = {"error": f"{url} is not a valid url"}

        resolved = await self.resolve(wallet.accounts, list(valid_urls), **kwargs)

        for resolved_uri in resolved:
            results[resolved_uri] = resolved[resolved_uri] if resolved[resolved_uri] is not None else \
                {"error": f"{resolved_uri} did not resolve to a claim"}

        return results

    @requires(WALLET_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT, BLOB_COMPONENT, DATABASE_COMPONENT,
              FILE_MANAGER_COMPONENT)
    async def jsonrpc_get(
            self, uri, file_name=None, download_directory=None, timeout=None, save_file=None, wallet_id=None):
        """
        Download stream from a LBRY name.

        Usage:
            get <uri> [<file_name> | --file_name=<file_name>]
             [<download_directory> | --download_directory=<download_directory>] [<timeout> | --timeout=<timeout>]
             [--save_file=<save_file>] [--wallet_id=<wallet_id>]


        Options:
            --uri=<uri>              : (str) uri of the content to download
            --file_name=<file_name>  : (str) specified name for the downloaded file, overrides the stream file name
            --download_directory=<download_directory>  : (str) full path to the directory to download into
            --timeout=<timeout>      : (int) download timeout in number of seconds
            --save_file=<save_file>  : (bool) save the file to the downloads directory
            --wallet_id=<wallet_id>  : (str) wallet to check for claim purchase receipts

        Returns: {File}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        if download_directory and not os.path.isdir(download_directory):
            return {"error": f"specified download directory \"{download_directory}\" does not exist"}
        try:
            stream = await self.file_manager.download_from_uri(
                uri, self.exchange_rate_manager, timeout, file_name, download_directory,
                save_file=save_file, wallet=wallet
            )
            if not stream:
                raise DownloadSDTimeoutError(uri)
        except Exception as e:
            # TODO: use error from lbry.error
            log.warning("Error downloading %s: %s", uri, str(e))
            return {"error": str(e)}
        return stream

    SETTINGS_DOC = """
    Settings management.
    """

    def jsonrpc_settings_get(self):
        """
        Get daemon settings

        Usage:
            settings_get

        Options:
            None

        Returns:
            (dict) Dictionary of daemon settings
            See ADJUSTABLE_SETTINGS in lbry/conf.py for full list of settings
        """
        return self.conf.settings_dict

    def jsonrpc_settings_set(self, key, value):
        """
        Set daemon settings

        Usage:
            settings_set (<key>) (<value>)

        Options:
            None

        Returns:
            (dict) Updated dictionary of daemon settings
        """
        with self.conf.update_config() as c:
            if value and isinstance(value, str) and value[0] in ('[', '{'):
                value = json.loads(value)
            attr: Setting = getattr(type(c), key)
            cleaned = attr.deserialize(value)
            setattr(c, key, cleaned)
        return {key: cleaned}

    def jsonrpc_settings_clear(self, key):
        """
        Clear daemon settings

        Usage:
            settings_clear (<key>)

        Options:
            None

        Returns:
            (dict) Updated dictionary of daemon settings
        """
        with self.conf.update_config() as c:
            setattr(c, key, NOT_SET)
        return {key: self.conf.settings_dict[key]}

    PREFERENCE_DOC = """
    Preferences management.
    """

    def jsonrpc_preference_get(self, key=None, wallet_id=None):
        """
        Get preference value for key or all values if not key is passed in.

        Usage:
            preference_get [<key>] [--wallet_id=<wallet_id>]

        Options:
            --key=<key> : (str) key associated with value
            --wallet_id=<wallet_id>   : (str) restrict operation to specific wallet

        Returns:
            (dict) Dictionary of preference(s)
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        if key:
            if key in wallet.preferences:
                return {key: wallet.preferences[key]}
            return
        return wallet.preferences.to_dict_without_ts()

    def jsonrpc_preference_set(self, key, value, wallet_id=None):
        """
        Set preferences

        Usage:
            preference_set (<key>) (<value>) [--wallet_id=<wallet_id>]

        Options:
            --key=<key> : (str) key associated with value
            --value=<key> : (str) key associated with value
            --wallet_id=<wallet_id>   : (str) restrict operation to specific wallet

        Returns:
            (dict) Dictionary with key/value of new preference
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        if value and isinstance(value, str) and value[0] in ('[', '{'):
            value = json.loads(value)
        wallet.preferences[key] = value
        wallet.save()
        return {key: value}

    WALLET_DOC = """
    Create, modify and inspect wallets.
    """

    @requires("wallet")
    def jsonrpc_wallet_list(self, wallet_id=None, page=None, page_size=None):
        """
        List wallets.

        Usage:
            wallet_list [--wallet_id=<wallet_id>] [--page=<page>] [--page_size=<page_size>]

        Options:
            --wallet_id=<wallet_id>  : (str) show specific wallet only
            --page=<page>            : (int) page to return during paginating
            --page_size=<page_size>  : (int) number of items on page during pagination

        Returns: {Paginated[Wallet]}
        """
        if wallet_id:
            return paginate_list([self.wallet_manager.get_wallet_or_error(wallet_id)], 1, 1)
        return paginate_list(self.wallet_manager.wallets, page, page_size)

    def jsonrpc_wallet_reconnect(self):
        """
        Reconnects ledger network client, applying new configurations.

        Usage:
            wallet_reconnect

        Options:

        Returns: None
        """
        return self.wallet_manager.reset()

    @requires("wallet")
    async def jsonrpc_wallet_create(
            self, wallet_id, skip_on_startup=False, create_account=False, single_key=False):
        """
        Create a new wallet.

        Usage:
            wallet_create (<wallet_id> | --wallet_id=<wallet_id>) [--skip_on_startup]
                          [--create_account] [--single_key]

        Options:
            --wallet_id=<wallet_id>  : (str) wallet file name
            --skip_on_startup        : (bool) don't add wallet to daemon_settings.yml
            --create_account         : (bool) generates the default account
            --single_key             : (bool) used with --create_account, creates single-key account

        Returns: {Wallet}
        """
        wallet_path = os.path.join(self.conf.wallet_dir, 'wallets', wallet_id)
        for wallet in self.wallet_manager.wallets:
            if wallet.id == wallet_id:
                raise WalletAlreadyLoadedError(wallet_path)
        if os.path.exists(wallet_path):
            raise WalletAlreadyExistsError(wallet_path)

        wallet = self.wallet_manager.import_wallet(wallet_path)
        if not wallet.accounts and create_account:
            account = Account.generate(
                self.ledger, wallet, address_generator={
                    'name': SingleKey.name if single_key else HierarchicalDeterministic.name
                }
            )
            if self.ledger.network.is_connected:
                await self.ledger.subscribe_account(account)
        wallet.save()
        if not skip_on_startup:
            with self.conf.update_config() as c:
                c.wallets += [wallet_id]
        return wallet

    @requires("wallet")
    async def jsonrpc_wallet_add(self, wallet_id):
        """
        Add existing wallet.

        Usage:
            wallet_add (<wallet_id> | --wallet_id=<wallet_id>)

        Options:
            --wallet_id=<wallet_id>  : (str) wallet file name

        Returns: {Wallet}
        """
        wallet_path = os.path.join(self.conf.wallet_dir, 'wallets', wallet_id)
        for wallet in self.wallet_manager.wallets:
            if wallet.id == wallet_id:
                raise WalletAlreadyLoadedError(wallet_path)
        if not os.path.exists(wallet_path):
            raise WalletNotFoundError(wallet_path)
        wallet = self.wallet_manager.import_wallet(wallet_path)
        if self.ledger.network.is_connected:
            for account in wallet.accounts:
                await self.ledger.subscribe_account(account)
        return wallet

    @requires("wallet")
    async def jsonrpc_wallet_remove(self, wallet_id):
        """
        Remove an existing wallet.

        Usage:
            wallet_remove (<wallet_id> | --wallet_id=<wallet_id>)

        Options:
            --wallet_id=<wallet_id>    : (str) name of wallet to remove

        Returns: {Wallet}
        """
        wallet = self.wallet_manager.get_wallet_or_error(wallet_id)
        self.wallet_manager.wallets.remove(wallet)
        for account in wallet.accounts:
            await self.ledger.unsubscribe_account(account)
        return wallet

    @requires("wallet")
    async def jsonrpc_wallet_balance(self, wallet_id=None, confirmations=0):
        """
        Return the balance of a wallet

        Usage:
            wallet_balance [--wallet_id=<wallet_id>] [--confirmations=<confirmations>]

        Options:
            --wallet_id=<wallet_id>         : (str) balance for specific wallet
            --confirmations=<confirmations> : (int) Only include transactions with this many
                                              confirmed blocks.

        Returns:
            (decimal) amount of lbry credits in wallet
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        balance = await self.ledger.get_detailed_balance(
            accounts=wallet.accounts, confirmations=confirmations
        )
        return dict_values_to_lbc(balance)

    def jsonrpc_wallet_status(self, wallet_id=None):
        """
        Status of wallet including encryption/lock state.

        Usage:
            wallet_status [<wallet_id> | --wallet_id=<wallet_id>]

        Options:
            --wallet_id=<wallet_id>    : (str) status of specific wallet

        Returns:
            Dictionary of wallet status information.
        """
        if self.wallet_manager is None:
            return {'is_encrypted': None, 'is_syncing': None, 'is_locked': None}
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        return {
            'is_encrypted': wallet.is_encrypted,
            'is_syncing': len(self.ledger._update_tasks) > 0,
            'is_locked': wallet.is_locked
        }

    @requires(WALLET_COMPONENT)
    def jsonrpc_wallet_unlock(self, password, wallet_id=None):
        """
        Unlock an encrypted wallet

        Usage:
            wallet_unlock (<password> | --password=<password>) [--wallet_id=<wallet_id>]

        Options:
            --password=<password>      : (str) password to use for unlocking
            --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet

        Returns:
            (bool) true if wallet is unlocked, otherwise false
        """
        return self.wallet_manager.get_wallet_or_default(wallet_id).unlock(password)

    @requires(WALLET_COMPONENT)
    def jsonrpc_wallet_lock(self, wallet_id=None):
        """
        Lock an unlocked wallet

        Usage:
            wallet_lock [--wallet_id=<wallet_id>]

        Options:
            --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet

        Returns:
            (bool) true if wallet is locked, otherwise false
        """
        return self.wallet_manager.get_wallet_or_default(wallet_id).lock()

    @requires(WALLET_COMPONENT)
    def jsonrpc_wallet_decrypt(self, wallet_id=None):
        """
        Decrypt an encrypted wallet, this will remove the wallet password. The wallet must be unlocked to decrypt it

        Usage:
            wallet_decrypt [--wallet_id=<wallet_id>]

        Options:
            --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet

        Returns:
            (bool) true if wallet is decrypted, otherwise false
        """
        return self.wallet_manager.get_wallet_or_default(wallet_id).decrypt()

    @requires(WALLET_COMPONENT)
    def jsonrpc_wallet_encrypt(self, new_password, wallet_id=None):
        """
        Encrypt an unencrypted wallet with a password

        Usage:
            wallet_encrypt (<new_password> | --new_password=<new_password>)
                            [--wallet_id=<wallet_id>]

        Options:
            --new_password=<new_password>  : (str) password to encrypt account
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet

        Returns:
            (bool) true if wallet is decrypted, otherwise false
        """
        return self.wallet_manager.get_wallet_or_default(wallet_id).encrypt(new_password)

    @requires(WALLET_COMPONENT)
    async def jsonrpc_wallet_send(
            self, amount, addresses, wallet_id=None,
            change_account_id=None, funding_account_ids=None, preview=False, blocking=True):
        """
        Send the same number of credits to multiple addresses using all accounts in wallet to
        fund the transaction and the default account to receive any change.

        Usage:
            wallet_send <amount> <addresses>... [--wallet_id=<wallet_id>] [--preview]
                        [--change_account_id=None] [--funding_account_ids=<funding_account_ids>...]
                        [--blocking]

        Options:
            --wallet_id=<wallet_id>         : (str) restrict operation to specific wallet
            --change_account_id=<wallet_id> : (str) account where change will go
            --funding_account_ids=<funding_account_ids> : (str) accounts to fund the transaction
            --preview                       : (bool) do not broadcast the transaction
            --blocking                      : (bool) wait until tx has synced

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        account = wallet.get_account_or_default(change_account_id)
        accounts = wallet.get_accounts_or_all(funding_account_ids)

        amount = self.get_dewies_or_error("amount", amount)

        if addresses and not isinstance(addresses, list):
            addresses = [addresses]

        outputs = []
        for address in addresses:
            self.valid_address_or_error(address, allow_script_address=True)
            if self.ledger.is_pubkey_address(address):
                outputs.append(
                    Output.pay_pubkey_hash(
                        amount, self.ledger.address_to_hash160(address)
                    )
                )
            elif self.ledger.is_script_address(address):
                outputs.append(
                    Output.pay_script_hash(
                        amount, self.ledger.address_to_hash160(address)
                    )
                )
            else:
                raise ValueError(f"Unsupported address: '{address}'")  # TODO: use error from lbry.error

        tx = await Transaction.create(
            [], outputs, accounts, account
        )
        if not preview:
            await self.broadcast_or_release(tx, blocking)
            self.component_manager.loop.create_task(self.analytics_manager.send_credits_sent())
        else:
            await self.ledger.release_tx(tx)
        return tx

    ACCOUNT_DOC = """
    Create, modify and inspect wallet accounts.
    """

    @requires("wallet")
    async def jsonrpc_account_list(
            self, account_id=None, wallet_id=None, confirmations=0,
            include_claims=False, show_seed=False, page=None, page_size=None):
        """
        List details of all of the accounts or a specific account.

        Usage:
            account_list [<account_id>] [--wallet_id=<wallet_id>]
                         [--confirmations=<confirmations>]
                         [--include_claims] [--show_seed]
                         [--page=<page>] [--page_size=<page_size>]

        Options:
            --account_id=<account_id>       : (str) If provided only the balance for this
                                                    account will be given
            --wallet_id=<wallet_id>         : (str) accounts in specific wallet
            --confirmations=<confirmations> : (int) required confirmations (default: 0)
            --include_claims                : (bool) include claims, requires than a
                                                     LBC account is specified (default: false)
            --show_seed                     : (bool) show the seed for the account
            --page=<page>                   : (int) page to return during paginating
            --page_size=<page_size>         : (int) number of items on page during pagination

        Returns: {Paginated[Account]}
        """
        kwargs = {
            'confirmations': confirmations,
            'show_seed': show_seed
        }
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        if account_id:
            return paginate_list([await wallet.get_account_or_error(account_id).get_details(**kwargs)], 1, 1)
        else:
            return paginate_list(await wallet.get_detailed_accounts(**kwargs), page, page_size)

    @requires("wallet")
    async def jsonrpc_account_balance(self, account_id=None, wallet_id=None, confirmations=0):
        """
        Return the balance of an account

        Usage:
            account_balance [<account_id>] [<address> | --address=<address>] [--wallet_id=<wallet_id>]
                            [<confirmations> | --confirmations=<confirmations>]

        Options:
            --account_id=<account_id>       : (str) If provided only the balance for this
                                              account will be given. Otherwise default account.
            --wallet_id=<wallet_id>         : (str) balance for specific wallet
            --confirmations=<confirmations> : (int) Only include transactions with this many
                                              confirmed blocks.

        Returns:
            (decimal) amount of lbry credits in wallet
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        account = wallet.get_account_or_default(account_id)
        balance = await account.get_detailed_balance(
            confirmations=confirmations, read_only=True
        )
        return dict_values_to_lbc(balance)

    @requires("wallet")
    async def jsonrpc_account_add(
            self, account_name, wallet_id=None, single_key=False,
            seed=None, private_key=None, public_key=None):
        """
        Add a previously created account from a seed, private key or public key (read-only).
        Specify --single_key for single address or vanity address accounts.

        Usage:
            account_add (<account_name> | --account_name=<account_name>)
                 (--seed=<seed> | --private_key=<private_key> | --public_key=<public_key>)
                 [--single_key] [--wallet_id=<wallet_id>]

        Options:
            --account_name=<account_name>  : (str) name of the account to add
            --seed=<seed>                  : (str) seed to generate new account from
            --private_key=<private_key>    : (str) private key for new account
            --public_key=<public_key>      : (str) public key for new account
            --single_key                   : (bool) create single key account, default is multi-key
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet

        Returns: {Account}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        account = Account.from_dict(
            self.ledger, wallet, {
                'name': account_name,
                'seed': seed,
                'private_key': private_key,
                'public_key': public_key,
                'address_generator': {
                    'name': SingleKey.name if single_key else HierarchicalDeterministic.name
                }
            }
        )
        wallet.save()
        if self.ledger.network.is_connected:
            await self.ledger.subscribe_account(account)
        return account

    @requires("wallet")
    async def jsonrpc_account_create(self, account_name, single_key=False, wallet_id=None):
        """
        Create a new account. Specify --single_key if you want to use
        the same address for all transactions (not recommended).

        Usage:
            account_create (<account_name> | --account_name=<account_name>)
                           [--single_key] [--wallet_id=<wallet_id>]

        Options:
            --account_name=<account_name>  : (str) name of the account to create
            --single_key                   : (bool) create single key account, default is multi-key
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet

        Returns: {Account}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        account = Account.generate(
            self.ledger, wallet, account_name, {
                'name': SingleKey.name if single_key else HierarchicalDeterministic.name
            }
        )
        wallet.save()
        if self.ledger.network.is_connected:
            await self.ledger.subscribe_account(account)
        return account

    @requires("wallet")
    def jsonrpc_account_remove(self, account_id, wallet_id=None):
        """
        Remove an existing account.

        Usage:
            account_remove (<account_id> | --account_id=<account_id>) [--wallet_id=<wallet_id>]

        Options:
            --account_id=<account_id>  : (str) id of the account to remove
            --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet

        Returns: {Account}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        account = wallet.get_account_or_error(account_id)
        wallet.accounts.remove(account)
        wallet.save()
        return account

    @requires("wallet")
    def jsonrpc_account_set(
            self, account_id, wallet_id=None, default=False, new_name=None,
            change_gap=None, change_max_uses=None, receiving_gap=None, receiving_max_uses=None):
        """
        Change various settings on an account.

        Usage:
            account_set (<account_id> | --account_id=<account_id>) [--wallet_id=<wallet_id>]
                [--default] [--new_name=<new_name>]
                [--change_gap=<change_gap>] [--change_max_uses=<change_max_uses>]
                [--receiving_gap=<receiving_gap>] [--receiving_max_uses=<receiving_max_uses>]

        Options:
            --account_id=<account_id>       : (str) id of the account to change
            --wallet_id=<wallet_id>         : (str) restrict operation to specific wallet
            --default                       : (bool) make this account the default
            --new_name=<new_name>           : (str) new name for the account
            --receiving_gap=<receiving_gap> : (int) set the gap for receiving addresses
            --receiving_max_uses=<receiving_max_uses> : (int) set the maximum number of times to
                                                              use a receiving address
            --change_gap=<change_gap>           : (int) set the gap for change addresses
            --change_max_uses=<change_max_uses> : (int) set the maximum number of times to
                                                        use a change address

        Returns: {Account}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        account = wallet.get_account_or_error(account_id)
        change_made = False

        if account.receiving.name == HierarchicalDeterministic.name:
            address_changes = {
                'change': {'gap': change_gap, 'maximum_uses_per_address': change_max_uses},
                'receiving': {'gap': receiving_gap, 'maximum_uses_per_address': receiving_max_uses},
            }
            for chain_name, changes in address_changes.items():
                chain = getattr(account, chain_name)
                for attr, value in changes.items():
                    if value is not None:
                        setattr(chain, attr, value)
                        change_made = True

        if new_name is not None:
            account.name = new_name
            change_made = True

        if default and wallet.default_account != account:
            wallet.accounts.remove(account)
            wallet.accounts.insert(0, account)
            change_made = True

        if change_made:
            account.modified_on = int(time.time())
            wallet.save()

        return account

    @requires("wallet")
    def jsonrpc_account_max_address_gap(self, account_id, wallet_id=None):
        """
        Finds ranges of consecutive addresses that are unused and returns the length
        of the longest such range: for change and receiving address chains. This is
        useful to figure out ideal values to set for 'receiving_gap' and 'change_gap'
        account settings.

        Usage:
            account_max_address_gap (<account_id> | --account_id=<account_id>)
                                    [--wallet_id=<wallet_id>]

        Options:
            --account_id=<account_id>  : (str) account for which to get max gaps
            --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet

        Returns:
            (map) maximum gap for change and receiving addresses
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        return wallet.get_account_or_error(account_id).get_max_gap()

    @requires("wallet")
    def jsonrpc_account_fund(self, to_account=None, from_account=None, amount='0.0',
                             everything=False, outputs=1, broadcast=False, wallet_id=None):
        """
        Transfer some amount (or --everything) to an account from another
        account (can be the same account). Amounts are interpreted as LBC.
        You can also spread the transfer across a number of --outputs (cannot
        be used together with --everything).

        Usage:
            account_fund [<to_account> | --to_account=<to_account>]
                [<from_account> | --from_account=<from_account>]
                (<amount> | --amount=<amount> | --everything)
                [<outputs> | --outputs=<outputs>] [--wallet_id=<wallet_id>]
                [--broadcast]

        Options:
            --to_account=<to_account>     : (str) send to this account
            --from_account=<from_account> : (str) spend from this account
            --amount=<amount>             : (str) the amount to transfer lbc
            --everything                  : (bool) transfer everything (excluding claims), default: false.
            --outputs=<outputs>           : (int) split payment across many outputs, default: 1.
            --wallet_id=<wallet_id>       : (str) limit operation to specific wallet.
            --broadcast                   : (bool) actually broadcast the transaction, default: false.

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        to_account = wallet.get_account_or_default(to_account)
        from_account = wallet.get_account_or_default(from_account)
        amount = self.get_dewies_or_error('amount', amount) if amount else None
        if not isinstance(outputs, int):
            # TODO: use error from lbry.error
            raise ValueError("--outputs must be an integer.")
        if everything and outputs > 1:
            # TODO: use error from lbry.error
            raise ValueError("Using --everything along with --outputs is not supported.")
        return from_account.fund(
            to_account=to_account, amount=amount, everything=everything,
            outputs=outputs, broadcast=broadcast
        )

    @requires("wallet")
    async def jsonrpc_account_deposit(
        self, txid, nout, redeem_script, private_key,
        to_account=None, wallet_id=None, preview=False, blocking=False
    ):
        """
        Spend a time locked transaction into your account.

        Usage:
            account_deposit <txid> <nout> <redeem_script> <private_key>
                [<to_account> | --to_account=<to_account>]
                [--wallet_id=<wallet_id>] [--preview] [--blocking]

        Options:
            --txid=<txid>                   : (str) id of the transaction
            --nout=<nout>                   : (int) output number in the transaction
            --redeem_script=<redeem_script> : (str) redeem script for output
            --private_key=<private_key>     : (str) private key to sign transaction
            --to_account=<to_account>       : (str) deposit to this account
            --wallet_id=<wallet_id>         : (str) limit operation to specific wallet.
            --preview                       : (bool) do not broadcast the transaction
            --blocking                      : (bool) wait until tx has synced

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        account = wallet.get_account_or_default(to_account)
        other_tx = await self.wallet_manager.get_transaction(txid)
        tx = await Transaction.spend_time_lock(
            other_tx.outputs[nout], unhexlify(redeem_script), account
        )
        pk = PrivateKey.from_bytes(
            account.ledger, Base58.decode_check(private_key)[1:-1]
        )
        await tx.sign([account], {pk.address: pk})
        if not preview:
            await self.broadcast_or_release(tx, blocking)
            self.component_manager.loop.create_task(self.analytics_manager.send_credits_sent())
        else:
            await self.ledger.release_tx(tx)
        return tx

    @requires(WALLET_COMPONENT)
    def jsonrpc_account_send(self, amount, addresses, account_id=None, wallet_id=None, preview=False, blocking=False):
        """
        Send the same number of credits to multiple addresses from a specific account (or default account).

        Usage:
            account_send <amount> <addresses>... [--account_id=<account_id>] [--wallet_id=<wallet_id>] [--preview]
                                                 [--blocking]

        Options:
            --account_id=<account_id>  : (str) account to fund the transaction
            --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet
            --preview                  : (bool) do not broadcast the transaction
            --blocking                 : (bool) wait until tx has synced

        Returns: {Transaction}
        """
        return self.jsonrpc_wallet_send(
            amount=amount, addresses=addresses, wallet_id=wallet_id,
            change_account_id=account_id, funding_account_ids=[account_id] if account_id else [],
            preview=preview, blocking=blocking
        )

    SYNC_DOC = """
    Wallet synchronization.
    """

    @requires("wallet")
    def jsonrpc_sync_hash(self, wallet_id=None):
        """
        Deterministic hash of the wallet.

        Usage:
            sync_hash [<wallet_id> | --wallet_id=<wallet_id>]

        Options:
            --wallet_id=<wallet_id>   : (str) wallet for which to generate hash

        Returns:
            (str) sha256 hash of wallet
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        return hexlify(wallet.hash).decode()

    @requires("wallet")
    async def jsonrpc_sync_apply(self, password, data=None, wallet_id=None, blocking=False):
        """
        Apply incoming synchronization data, if provided, and return a sync hash and update wallet data.

        Wallet must be unlocked to perform this operation.

        If "encrypt-on-disk" preference is True and supplied password is different from local password,
        or there is no local password (because local wallet was not encrypted), then the supplied password
        will be used for local encryption (overwriting previous local encryption password).

        Usage:
            sync_apply <password> [--data=<data>] [--wallet_id=<wallet_id>] [--blocking]

        Options:
            --password=<password>         : (str) password to decrypt incoming and encrypt outgoing data
            --data=<data>                 : (str) incoming sync data, if any
            --wallet_id=<wallet_id>       : (str) wallet being sync'ed
            --blocking                    : (bool) wait until any new accounts have sync'ed

        Returns:
            (map) sync hash and data

        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        wallet_changed = False
        if data is not None:
            added_accounts = wallet.merge(self.wallet_manager, password, data)
            if added_accounts and self.ledger.network.is_connected:
                if blocking:
                    await asyncio.wait([
                        a.ledger.subscribe_account(a) for a in added_accounts
                    ])
                else:
                    for new_account in added_accounts:
                        asyncio.create_task(self.ledger.subscribe_account(new_account))
            wallet_changed = True
        if wallet.preferences.get(ENCRYPT_ON_DISK, False) and password != wallet.encryption_password:
            wallet.encryption_password = password
            wallet_changed = True
        if wallet_changed:
            wallet.save()
        encrypted = wallet.pack(password)
        return {
            'hash': self.jsonrpc_sync_hash(wallet_id),
            'data': encrypted.decode()
        }

    ADDRESS_DOC = """
    List, generate and verify addresses.
    """

    @requires(WALLET_COMPONENT)
    async def jsonrpc_address_is_mine(self, address, account_id=None, wallet_id=None):
        """
        Checks if an address is associated with the current wallet.

        Usage:
            address_is_mine (<address> | --address=<address>)
                            [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]

        Options:
            --address=<address>       : (str) address to check
            --account_id=<account_id> : (str) id of the account to use
            --wallet_id=<wallet_id>   : (str) restrict operation to specific wallet

        Returns:
            (bool) true, if address is associated with current wallet
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        account = wallet.get_account_or_default(account_id)
        match = await self.ledger.db.get_address(read_only=True, address=address, accounts=[account])
        if match is not None:
            return True
        return False

    @requires(WALLET_COMPONENT)
    def jsonrpc_address_list(self, address=None, account_id=None, wallet_id=None, page=None, page_size=None):
        """
        List account addresses or details of single address.

        Usage:
            address_list [--address=<address>] [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                         [--page=<page>] [--page_size=<page_size>]

        Options:
            --address=<address>        : (str) just show details for single address
            --account_id=<account_id>  : (str) id of the account to use
            --wallet_id=<wallet_id>    : (str) restrict operation to specific wallet
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination

        Returns: {Paginated[Address]}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        constraints = {
            'cols': ('address', 'account', 'used_times', 'pubkey', 'chain_code', 'n', 'depth')
        }
        if address:
            constraints['address'] = address
        if account_id:
            constraints['accounts'] = [wallet.get_account_or_error(account_id)]
        else:
            constraints['accounts'] = wallet.accounts
        return paginate_rows(
            self.ledger.get_addresses,
            self.ledger.get_address_count,
            page, page_size, read_only=True, **constraints
        )

    @requires(WALLET_COMPONENT)
    def jsonrpc_address_unused(self, account_id=None, wallet_id=None):
        """
        Return an address containing no balance, will create
        a new address if there is none.

        Usage:
            address_unused [--account_id=<account_id>] [--wallet_id=<wallet_id>]

        Options:
            --account_id=<account_id> : (str) id of the account to use
            --wallet_id=<wallet_id>   : (str) restrict operation to specific wallet

        Returns: {Address}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        return wallet.get_account_or_default(account_id).receiving.get_or_create_usable_address()

    FILE_DOC = """
    File management.
    """

    @requires(FILE_MANAGER_COMPONENT)
    async def jsonrpc_file_list(self, sort=None, reverse=False, comparison=None, wallet_id=None, page=None,
                                page_size=None, **kwargs):
        """
        List files limited by optional filters

        Usage:
            file_list [--sd_hash=<sd_hash>] [--file_name=<file_name>] [--stream_hash=<stream_hash>]
                      [--rowid=<rowid>] [--added_on=<added_on>] [--claim_id=<claim_id>]
                      [--outpoint=<outpoint>] [--txid=<txid>] [--nout=<nout>]
                      [--channel_claim_id=<channel_claim_id>] [--channel_name=<channel_name>]
                      [--claim_name=<claim_name>] [--blobs_in_stream=<blobs_in_stream>]
                      [--download_path=<download_path>] [--blobs_remaining=<blobs_remaining>]
                      [--uploading_to_reflector=<uploading_to_reflector>] [--is_fully_reflected=<is_fully_reflected>]
                      [--status=<status>] [--completed=<completed>] [--sort=<sort_by>] [--comparison=<comparison>]
                      [--full_status=<full_status>] [--reverse] [--page=<page>] [--page_size=<page_size>]
                      [--wallet_id=<wallet_id>]

        Options:
            --sd_hash=<sd_hash>                    : (str) get file with matching sd hash
            --file_name=<file_name>                : (str) get file with matching file name in the
                                                     downloads folder
            --stream_hash=<stream_hash>            : (str) get file with matching stream hash
            --rowid=<rowid>                        : (int) get file with matching row id
            --added_on=<added_on>                  : (int) get file with matching time of insertion
            --claim_id=<claim_id>                  : (str) get file with matching claim id(s)
            --outpoint=<outpoint>                  : (str) get file with matching claim outpoint(s)
            --txid=<txid>                          : (str) get file with matching claim txid
            --nout=<nout>                          : (int) get file with matching claim nout
            --channel_claim_id=<channel_claim_id>  : (str) get file with matching channel claim id(s)
            --channel_name=<channel_name>          : (str) get file with matching channel name
            --claim_name=<claim_name>              : (str) get file with matching claim name
            --blobs_in_stream=<blobs_in_stream>    : (int) get file with matching blobs in stream
            --download_path=<download_path>        : (str) get file with matching download path
            --uploading_to_reflector=<uploading_to_reflector> : (bool) get files currently uploading to reflector
            --is_fully_reflected=<is_fully_reflected>         : (bool) get files that have been uploaded to reflector
            --status=<status>                      : (str) match by status, ( running | finished | stopped )
            --completed=<completed>                : (bool) match only completed
            --blobs_remaining=<blobs_remaining>    : (int) amount of remaining blobs to download
            --sort=<sort_by>                       : (str) field to sort by (one of the above filter fields)
            --comparison=<comparison>              : (str) logical comparison, (eq | ne | g | ge | l | le | in)
            --page=<page>                          : (int) page to return during paginating
            --page_size=<page_size>                : (int) number of items on page during pagination
            --wallet_id=<wallet_id>                : (str) add purchase receipts from this wallet

        Returns: {Paginated[File]}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        sort = sort or 'rowid'
        comparison = comparison or 'eq'

        paginated = paginate_list(
            self.file_manager.get_filtered(sort, reverse, comparison, **kwargs), page, page_size
        )
        if paginated['items']:
            receipts = {
                txo.purchased_claim_id: txo for txo in
                await self.ledger.db.get_purchases(
                    accounts=wallet.accounts,
                    purchased_claim_id__in=[s.claim_id for s in paginated['items']]
                )
            }
            for stream in paginated['items']:
                stream.purchase_receipt = receipts.get(stream.claim_id)
        return paginated

    @requires(FILE_MANAGER_COMPONENT)
    async def jsonrpc_file_set_status(self, status, **kwargs):
        """
        Start or stop downloading a file

        Usage:
            file_set_status (<status> | --status=<status>) [--sd_hash=<sd_hash>]
                      [--file_name=<file_name>] [--stream_hash=<stream_hash>] [--rowid=<rowid>]

        Options:
            --status=<status>            : (str) one of "start" or "stop"
            --sd_hash=<sd_hash>          : (str) set status of file with matching sd hash
            --file_name=<file_name>      : (str) set status of file with matching file name in the
                                           downloads folder
            --stream_hash=<stream_hash>  : (str) set status of file with matching stream hash
            --rowid=<rowid>              : (int) set status of file with matching row id

        Returns:
            (str) Confirmation message
        """

        if status not in ['start', 'stop']:
            # TODO: use error from lbry.error
            raise Exception('Status must be "start" or "stop".')

        streams = self.file_manager.get_filtered(**kwargs)
        if not streams:
            # TODO: use error from lbry.error
            raise Exception(f'Unable to find a file for {kwargs}')
        stream = streams[0]
        if status == 'start' and not stream.running:
            if not hasattr(stream, 'bt_infohash') and 'dht' not in self.conf.components_to_skip:
                stream.downloader.node = self.dht_node
            await stream.save_file()
            msg = "Resumed download"
        elif status == 'stop' and stream.running:
            await stream.stop()
            msg = "Stopped download"
        else:
            msg = (
                "File was already being downloaded" if status == 'start'
                else "File was already stopped"
            )
        return msg

    @requires(FILE_MANAGER_COMPONENT)
    async def jsonrpc_file_delete(self, delete_from_download_dir=False, delete_all=False, **kwargs):
        """
        Delete a LBRY file

        Usage:
            file_delete [--delete_from_download_dir] [--delete_all] [--sd_hash=<sd_hash>] [--file_name=<file_name>]
                        [--stream_hash=<stream_hash>] [--rowid=<rowid>] [--claim_id=<claim_id>] [--txid=<txid>]
                        [--nout=<nout>] [--claim_name=<claim_name>] [--channel_claim_id=<channel_claim_id>]
                        [--channel_name=<channel_name>]

        Options:
            --delete_from_download_dir             : (bool) delete file from download directory,
                                                    instead of just deleting blobs
            --delete_all                           : (bool) if there are multiple matching files,
                                                     allow the deletion of multiple files.
                                                     Otherwise do not delete anything.
            --sd_hash=<sd_hash>                    : (str) delete by file sd hash
            --file_name=<file_name>                 : (str) delete by file name in downloads folder
            --stream_hash=<stream_hash>            : (str) delete by file stream hash
            --rowid=<rowid>                        : (int) delete by file row id
            --claim_id=<claim_id>                  : (str) delete by file claim id
            --txid=<txid>                          : (str) delete by file claim txid
            --nout=<nout>                          : (int) delete by file claim nout
            --claim_name=<claim_name>              : (str) delete by file claim name
            --channel_claim_id=<channel_claim_id>  : (str) delete by file channel claim id
            --channel_name=<channel_name>                 : (str) delete by file channel claim name

        Returns:
            (bool) true if deletion was successful
        """

        streams = self.file_manager.get_filtered(**kwargs)

        if len(streams) > 1:
            if not delete_all:
                log.warning("There are %i files to delete, use narrower filters to select one",
                            len(streams))
                return False
            else:
                log.warning("Deleting %i files",
                            len(streams))

        if not streams:
            log.warning("There is no file to delete")
            return False
        else:
            for stream in streams:
                message = f"Deleted file {stream.file_name}"
                await self.file_manager.delete(stream, delete_file=delete_from_download_dir)
                log.info(message)
            result = True
        return result

    @requires(FILE_MANAGER_COMPONENT)
    async def jsonrpc_file_save(self, file_name=None, download_directory=None, **kwargs):
        """
        Start saving a file to disk.

        Usage:
            file_save [--file_name=<file_name>] [--download_directory=<download_directory>] [--sd_hash=<sd_hash>]
                      [--stream_hash=<stream_hash>] [--rowid=<rowid>] [--claim_id=<claim_id>] [--txid=<txid>]
                      [--nout=<nout>] [--claim_name=<claim_name>] [--channel_claim_id=<channel_claim_id>]
                      [--channel_name=<channel_name>]

        Options:
            --file_name=<file_name>                      : (str) file name to save to
            --download_directory=<download_directory>    : (str) directory to save into
            --sd_hash=<sd_hash>                          : (str) save file with matching sd hash
            --stream_hash=<stream_hash>                  : (str) save file with matching stream hash
            --rowid=<rowid>                              : (int) save file with matching row id
            --claim_id=<claim_id>                        : (str) save file with matching claim id
            --txid=<txid>                                : (str) save file with matching claim txid
            --nout=<nout>                                : (int) save file with matching claim nout
            --claim_name=<claim_name>                    : (str) save file with matching claim name
            --channel_claim_id=<channel_claim_id>        : (str) save file with matching channel claim id
            --channel_name=<channel_name>                : (str) save file with matching channel claim name

        Returns: {File}
        """

        streams = self.file_manager.get_filtered(**kwargs)

        if len(streams) > 1:
            log.warning("There are %i matching files, use narrower filters to select one", len(streams))
            return False
        if not streams:
            log.warning("There is no file to save")
            return False
        stream = streams[0]
        if not hasattr(stream, 'bt_infohash') and 'dht' not in self.conf.components_to_skip:
            stream.downloader.node = self.dht_node
        await stream.save_file(file_name, download_directory)
        return stream

    PURCHASE_DOC = """
    List and make purchases of claims.
    """

    @requires(WALLET_COMPONENT)
    def jsonrpc_purchase_list(
            self, claim_id=None, resolve=False, account_id=None, wallet_id=None, page=None, page_size=None):
        """
        List my claim purchases.

        Usage:
            purchase_list [<claim_id> | --claim_id=<claim_id>] [--resolve]
                          [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                          [--page=<page>] [--page_size=<page_size>]

        Options:
            --claim_id=<claim_id>      : (str) purchases for specific claim
            --resolve                  : (str) include resolved claim information
            --account_id=<account_id>  : (str) id of the account to query
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination

        Returns: {Paginated[Output]}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        constraints = {
            "wallet": wallet,
            "accounts": [wallet.get_account_or_error(account_id)] if account_id else wallet.accounts,
            "resolve": resolve,
        }
        if claim_id:
            constraints["purchased_claim_id"] = claim_id
        return paginate_rows(
            self.ledger.get_purchases,
            self.ledger.get_purchase_count,
            page, page_size, **constraints
        )

    @requires(WALLET_COMPONENT)
    async def jsonrpc_purchase_create(
            self, claim_id=None, url=None, wallet_id=None, funding_account_ids=None,
            allow_duplicate_purchase=False, override_max_key_fee=False, preview=False, blocking=False):
        """
        Purchase a claim.

        Usage:
            purchase_create (--claim_id=<claim_id> | --url=<url>) [--wallet_id=<wallet_id>]
                    [--funding_account_ids=<funding_account_ids>...]
                    [--allow_duplicate_purchase] [--override_max_key_fee] [--preview] [--blocking]

        Options:
            --claim_id=<claim_id>          : (str) claim id of claim to purchase
            --url=<url>                    : (str) lookup claim to purchase by url
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet
          --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
            --allow_duplicate_purchase     : (bool) allow purchasing claim_id you already own
            --override_max_key_fee         : (bool) ignore max key fee for this purchase
            --preview                      : (bool) do not broadcast the transaction
            --blocking                     : (bool) wait until transaction is in mempool

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        accounts = wallet.get_accounts_or_all(funding_account_ids)
        txo = None
        if claim_id:
            txo = await self.ledger.get_claim_by_claim_id(claim_id, accounts, include_purchase_receipt=True)
            if not isinstance(txo, Output) or not txo.is_claim:
                # TODO: use error from lbry.error
                raise Exception(f"Could not find claim with claim_id '{claim_id}'.")
        elif url:
            txo = (await self.ledger.resolve(accounts, [url], include_purchase_receipt=True))[url]
            if not isinstance(txo, Output) or not txo.is_claim:
                # TODO: use error from lbry.error
                raise Exception(f"Could not find claim with url '{url}'.")
        else:
            # TODO: use error from lbry.error
            raise Exception("Missing argument claim_id or url.")
        if not allow_duplicate_purchase and txo.purchase_receipt:
            raise AlreadyPurchasedError(claim_id)
        claim = txo.claim
        if not claim.is_stream or not claim.stream.has_fee:
            # TODO: use error from lbry.error
            raise Exception(f"Claim '{claim_id}' does not have a purchase price.")
        tx = await self.wallet_manager.create_purchase_transaction(
            accounts, txo, self.exchange_rate_manager, override_max_key_fee
        )
        if not preview:
            await self.broadcast_or_release(tx, blocking)
        else:
            await self.ledger.release_tx(tx)
        return tx

    CLAIM_DOC = """
    List and search all types of claims.
    """

    @requires(WALLET_COMPONENT)
    def jsonrpc_claim_list(self, claim_type=None, **kwargs):
        """
        List my stream and channel claims.

        Usage:
            claim_list [--claim_type=<claim_type>...] [--claim_id=<claim_id>...] [--name=<name>...] [--is_spent]
                       [--channel_id=<channel_id>...] [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                       [--has_source | --has_no_source] [--page=<page>] [--page_size=<page_size>]
                       [--resolve] [--order_by=<order_by>] [--no_totals] [--include_received_tips]

        Options:
            --claim_type=<claim_type>  : (str or list) claim type: channel, stream, repost, collection
            --claim_id=<claim_id>      : (str or list) claim id
            --channel_id=<channel_id>  : (str or list) streams in this channel
            --name=<name>              : (str or list) claim name
            --is_spent                 : (bool) shows previous claim updates and abandons
            --account_id=<account_id>  : (str) id of the account to query
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --has_source               : (bool) list claims containing a source field
            --has_no_source            : (bool) list claims not containing a source field
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination
            --resolve                  : (bool) resolves each claim to provide additional metadata
            --order_by=<order_by>      : (str) field to order by: 'name', 'height', 'amount'
            --no_totals                : (bool) do not calculate the total number of pages and items in result set
                                                (significant performance boost)
            --include_received_tips    : (bool) calculate the amount of tips received for claim outputs

        Returns: {Paginated[Output]}
        """
        kwargs['type'] = claim_type or CLAIM_TYPE_NAMES
        if not kwargs.get('is_spent', False):
            kwargs['is_not_spent'] = True
        return self.jsonrpc_txo_list(**kwargs)

    async def jsonrpc_support_sum(self, claim_id, new_sdk_server, include_channel_content=False, **kwargs):
        """
        List total staked supports for a claim, grouped by the channel that signed the support.

        If claim_id is a channel claim, you can use --include_channel_content to also include supports for
        content claims in the channel.

        !!!! NOTE: PAGINATION DOES NOT DO ANYTHING AT THE MOMENT !!!!!

        Usage:
            support_sum <claim_id> <new_sdk_server>
                         [--include_channel_content]
                         [--page=<page>] [--page_size=<page_size>]

        Options:
            --claim_id=<claim_id>             : (str)  claim id
            --new_sdk_server=<new_sdk_server> : (str)  URL of the new SDK server (EXPERIMENTAL)
            --include_channel_content         : (bool) if claim_id is for a channel, include supports for claims in
                                                       that channel
            --page=<page>                     : (int)  page to return during paginating
            --page_size=<page_size>           : (int)  number of items on page during pagination

        Returns: {Paginated[Dict]}
        """
        page_num, page_size = abs(kwargs.pop('page', 1)), min(abs(kwargs.pop('page_size', DEFAULT_PAGE_SIZE)), 50)
        kwargs.update({'offset': page_size * (page_num - 1), 'limit': page_size})
        support_sums = await self.ledger.sum_supports(
            new_sdk_server, claim_id=claim_id, include_channel_content=include_channel_content, **kwargs
        )
        return {
            "items": support_sums,
            "page": page_num,
            "page_size": page_size
        }

    @requires(WALLET_COMPONENT)
    async def jsonrpc_claim_search(self, **kwargs):
        """
        Search for stream and channel claims on the blockchain.

        Arguments marked with "supports equality constraints" allow prepending the
        value with an equality constraint such as '>', '>=', '<' and '<='
        eg. --height=">400000" would limit results to only claims above 400k block height.

        They also support multiple constraints passed as a list of the args described above.
        eg. --release_time=[">1000000", "<2000000"]

        Usage:
            claim_search [<name> | --name=<name>] [--text=<text>] [--txid=<txid>] [--nout=<nout>]
                         [--claim_id=<claim_id> | --claim_ids=<claim_ids>...]
                         [--channel=<channel> |
                             [[--channel_ids=<channel_ids>...] [--not_channel_ids=<not_channel_ids>...]]]
                         [--has_channel_signature] [--valid_channel_signature | --invalid_channel_signature]
                         [--limit_claims_per_channel=<limit_claims_per_channel>]
                         [--is_controlling] [--release_time=<release_time>] [--public_key_id=<public_key_id>]
                         [--timestamp=<timestamp>] [--creation_timestamp=<creation_timestamp>]
                         [--height=<height>] [--creation_height=<creation_height>]
                         [--activation_height=<activation_height>] [--expiration_height=<expiration_height>]
                         [--amount=<amount>] [--effective_amount=<effective_amount>]
                         [--support_amount=<support_amount>] [--trending_group=<trending_group>]
                         [--trending_mixed=<trending_mixed>] [--trending_local=<trending_local>]
                         [--trending_global=<trending_global] [--trending_score=<trending_score]
                         [--reposted_claim_id=<reposted_claim_id>] [--reposted=<reposted>]
                         [--claim_type=<claim_type>] [--stream_types=<stream_types>...] [--media_types=<media_types>...]
                         [--fee_currency=<fee_currency>] [--fee_amount=<fee_amount>]
                         [--duration=<duration>]
                         [--any_tags=<any_tags>...] [--all_tags=<all_tags>...] [--not_tags=<not_tags>...]
                         [--any_languages=<any_languages>...] [--all_languages=<all_languages>...]
                         [--not_languages=<not_languages>...]
                         [--any_locations=<any_locations>...] [--all_locations=<all_locations>...]
                         [--not_locations=<not_locations>...]
                         [--order_by=<order_by>...] [--no_totals] [--page=<page>] [--page_size=<page_size>]
                         [--wallet_id=<wallet_id>] [--include_purchase_receipt] [--include_is_my_output]
                         [--remove_duplicates] [--has_source | --has_no_source] [--sd_hash=<sd_hash>]
                         [--new_sdk_server=<new_sdk_server>]

        Options:
            --name=<name>                   : (str) claim name (normalized)
            --text=<text>                   : (str) full text search
            --claim_id=<claim_id>           : (str) full or partial claim id
            --claim_ids=<claim_ids>         : (list) list of full claim ids
            --txid=<txid>                   : (str) transaction id
            --nout=<nout>                   : (str) position in the transaction
            --channel=<channel>             : (str) claims signed by this channel (argument is
                                                    a URL which automatically gets resolved),
                                                    see --channel_ids if you need to filter by
                                                    multiple channels at the same time,
                                                    includes claims with invalid signatures,
                                                    use in conjunction with --valid_channel_signature
            --channel_ids=<channel_ids>     : (list) claims signed by any of these channels
                                                    (arguments must be claim ids of the channels),
                                                    includes claims with invalid signatures,
                                                    implies --has_channel_signature,
                                                    use in conjunction with --valid_channel_signature
            --not_channel_ids=<not_channel_ids>: (list) exclude claims signed by any of these channels
                                                    (arguments must be claim ids of the channels)
            --has_channel_signature         : (bool) claims with a channel signature (valid or invalid)
            --valid_channel_signature       : (bool) claims with a valid channel signature or no signature,
                                                     use in conjunction with --has_channel_signature to
                                                     only get claims with valid signatures
            --invalid_channel_signature     : (bool) claims with invalid channel signature or no signature,
                                                     use in conjunction with --has_channel_signature to
                                                     only get claims with invalid signatures
            --limit_claims_per_channel=<limit_claims_per_channel>: (int) only return up to the specified
                                                                         number of claims per channel
            --is_controlling                : (bool) winning claims of their respective name
            --public_key_id=<public_key_id> : (str) only return channels having this public key id, this is
                                                    the same key as used in the wallet file to map
                                                    channel certificate private keys: {'public_key_id': 'private key'}
            --height=<height>               : (int) last updated block height (supports equality constraints)
            --timestamp=<timestamp>         : (int) last updated timestamp (supports equality constraints)
            --creation_height=<creation_height>      : (int) created at block height (supports equality constraints)
            --creation_timestamp=<creation_timestamp>: (int) created at timestamp (supports equality constraints)
            --activation_height=<activation_height>  : (int) height at which claim starts competing for name
                                                             (supports equality constraints)
            --expiration_height=<expiration_height>  : (int) height at which claim will expire
                                                             (supports equality constraints)
            --release_time=<release_time>   : (int) limit to claims self-described as having been
                                                    released to the public on or after this UTC
                                                    timestamp, when claim does not provide
                                                    a release time the publish time is used instead
                                                    (supports equality constraints)
            --amount=<amount>               : (int) limit by claim value (supports equality constraints)
            --support_amount=<support_amount>: (int) limit by supports and tips received (supports
                                                    equality constraints)
            --effective_amount=<effective_amount>: (int) limit by total value (initial claim value plus
                                                     all tips and supports received), this amount is
                                                     blank until claim has reached activation height
                                                     (supports equality constraints)
            --trending_score=<trending_score>: (int) limit by trending score (supports equality constraints)
            --trending_group=<trending_group>: (int) DEPRECATED - instead please use trending_score
            --trending_mixed=<trending_mixed>: (int) DEPRECATED - instead please use trending_score
            --trending_local=<trending_local>: (int) DEPRECATED - instead please use trending_score
            --trending_global=<trending_global>: (int) DEPRECATED - instead please use trending_score
            --reposted_claim_id=<reposted_claim_id>: (str) all reposts of the specified original claim id
            --reposted=<reposted>           : (int) claims reposted this many times (supports
                                                    equality constraints)
            --claim_type=<claim_type>       : (str) filter by 'channel', 'stream', 'repost' or 'collection'
            --stream_types=<stream_types>   : (list) filter by 'video', 'image', 'document', etc
            --media_types=<media_types>     : (list) filter by 'video/mp4', 'image/png', etc
            --fee_currency=<fee_currency>   : (string) specify fee currency: LBC, BTC, USD
            --fee_amount=<fee_amount>       : (decimal) content download fee (supports equality constraints)
            --duration=<duration>           : (int) duration of video or audio in seconds
                                                     (supports equality constraints)
            --any_tags=<any_tags>           : (list) find claims containing any of the tags
            --all_tags=<all_tags>           : (list) find claims containing every tag
            --not_tags=<not_tags>           : (list) find claims not containing any of these tags
            --any_languages=<any_languages> : (list) find claims containing any of the languages
            --all_languages=<all_languages> : (list) find claims containing every language
            --not_languages=<not_languages> : (list) find claims not containing any of these languages
            --any_locations=<any_locations> : (list) find claims containing any of the locations
            --all_locations=<all_locations> : (list) find claims containing every location
            --not_locations=<not_locations> : (list) find claims not containing any of these locations
            --page=<page>                   : (int) page to return during paginating
            --page_size=<page_size>         : (int) number of items on page during pagination
            --order_by=<order_by>           : (list) field to order by, default is descending order, to do an
                                                    ascending order prepend ^ to the field name, eg. '^amount'
                                                    available fields: 'name', 'height', 'release_time',
                                                    'publish_time', 'amount', 'effective_amount',
                                                    'support_amount', 'trending_group', 'trending_mixed',
                                                    'trending_local', 'trending_global', 'activation_height'
            --no_totals                     : (bool) do not calculate the total number of pages and items in result set
                                                     (significant performance boost)
            --wallet_id=<wallet_id>         : (str) wallet to check for claim purchase receipts
            --include_purchase_receipt      : (bool) lookup and include a receipt if this wallet
                                                     has purchased the claim
            --include_is_my_output          : (bool) lookup and include a boolean indicating
                                                     if claim being resolved is yours
            --remove_duplicates             : (bool) removes duplicated content from search by picking either the
                                                     original claim or the oldest matching repost
            --has_source                    : (bool) find claims containing a source field
            --sd_hash=<sd_hash>             : (str)  find claims where the source stream descriptor hash matches
                                                     (partially or completely) the given hexadecimal string
            --has_no_source                 : (bool) find claims not containing a source field
           --new_sdk_server=<new_sdk_server> : (str) URL of the new SDK server (EXPERIMENTAL)

        Returns: {Paginated[Output]}
        """
        if self.ledger.config.get('use_go_hub'):
            host = self.ledger.network.client.server[0]
            port = "50051"
            kwargs['new_sdk_server'] = f"{host}:{port}"
            if kwargs.get("channel"):
                channel = kwargs.pop("channel")
                channel_obj = (await self.jsonrpc_resolve(channel))[channel]
                if isinstance(channel_obj, dict):
                    # This happens when the channel doesn't exist
                    kwargs["channel_id"] = ""
                else:
                    kwargs["channel_id"] = channel_obj.claim_id
            kwargs = fix_kwargs_for_hub(**kwargs)
        else:
            # Don't do this if using the hub server, it screws everything up
            if "claim_ids" in kwargs and not kwargs["claim_ids"]:
                kwargs.pop("claim_ids")
            if {'claim_id', 'claim_ids'}.issubset(kwargs):
                raise ConflictingInputValueError('claim_id', 'claim_ids')
            if kwargs.pop('valid_channel_signature', False):
                kwargs['signature_valid'] = 1
            if kwargs.pop('invalid_channel_signature', False):
                kwargs['signature_valid'] = 0
            if 'has_no_source' in kwargs:
                kwargs['has_source'] = not kwargs.pop('has_no_source')
            if 'order_by' in kwargs:  # TODO: remove this after removing support for old trending args from the api
                value = kwargs.pop('order_by')
                value = value if isinstance(value, list) else [value]
                new_value = []
                for new_v in value:
                    migrated = new_v if new_v not in (
                        'trending_mixed', 'trending_local', 'trending_global', 'trending_group'
                    ) else 'trending_score'
                    if migrated not in new_value:
                        new_value.append(migrated)
                kwargs['order_by'] = new_value
        page_num, page_size = abs(kwargs.pop('page', 1)), min(abs(kwargs.pop('page_size', DEFAULT_PAGE_SIZE)), 50)
        wallet = self.wallet_manager.get_wallet_or_default(kwargs.pop('wallet_id', None))
        kwargs.update({'offset': page_size * (page_num - 1), 'limit': page_size})
        txos, blocked, _, total = await self.ledger.claim_search(wallet.accounts, **kwargs)
        result = {
            "items": txos,
            "blocked": blocked,
            "page": page_num,
            "page_size": page_size
        }
        if not kwargs.pop('no_totals', False):
            result['total_pages'] = int((total + (page_size - 1)) / page_size)
            result['total_items'] = total
        return result

    CHANNEL_DOC = """
    Create, update, abandon and list your channel claims.
    """

    @deprecated('channel_create')
    def jsonrpc_channel_new(self):
        """ deprecated """

    @requires(WALLET_COMPONENT)
    async def jsonrpc_channel_create(
            self, name, bid, allow_duplicate_name=False, account_id=None, wallet_id=None,
            claim_address=None, funding_account_ids=None, preview=False, blocking=False, **kwargs):
        """
        Create a new channel by generating a channel private key and establishing an '@' prefixed claim.

        Usage:
            channel_create (<name> | --name=<name>) (<bid> | --bid=<bid>)
                           [--allow_duplicate_name=<allow_duplicate_name>]
                           [--title=<title>] [--description=<description>] [--email=<email>]
                           [--website_url=<website_url>] [--featured=<featured>...]
                           [--tags=<tags>...] [--languages=<languages>...] [--locations=<locations>...]
                           [--thumbnail_url=<thumbnail_url>] [--cover_url=<cover_url>]
                           [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                           [--claim_address=<claim_address>] [--funding_account_ids=<funding_account_ids>...]
                           [--preview] [--blocking]

        Options:
            --name=<name>                  : (str) name of the channel prefixed with '@'
            --bid=<bid>                    : (decimal) amount to back the claim
        --allow_duplicate_name=<allow_duplicate_name> : (bool) create new channel even if one already exists with
                                              given name. default: false.
            --title=<title>                : (str) title of the publication
            --description=<description>    : (str) description of the publication
            --email=<email>                : (str) email of channel owner
            --website_url=<website_url>    : (str) website url
            --featured=<featured>          : (list) claim_ids of featured content in channel
            --tags=<tags>                  : (list) content tags
            --languages=<languages>        : (list) languages used by the channel,
                                                    using RFC 5646 format, eg:
                                                    for English `--languages=en`
                                                    for Spanish (Spain) `--languages=es-ES`
                                                    for Spanish (Mexican) `--languages=es-MX`
                                                    for Chinese (Simplified) `--languages=zh-Hans`
                                                    for Chinese (Traditional) `--languages=zh-Hant`
            --locations=<locations>        : (list) locations of the channel, consisting of 2 letter
                                                    `country` code and a `state`, `city` and a postal
                                                    `code` along with a `latitude` and `longitude`.
                                                    for JSON RPC: pass a dictionary with aforementioned
                                                        attributes as keys, eg:
                                                        ...
                                                        "locations": [{'country': 'US', 'state': 'NH'}]
                                                        ...
                                                    for command line: pass a colon delimited list
                                                        with values in the following order:

                                                          "COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE"

                                                        making sure to include colon for blank values, for
                                                        example to provide only the city:

                                                          ... --locations="::Manchester"

                                                        with all values set:

                                                 ... --locations="US:NH:Manchester:03101:42.990605:-71.460989"

                                                        optionally, you can just pass the "LATITUDE:LONGITUDE":

                                                          ... --locations="42.990605:-71.460989"

                                                        finally, you can also pass JSON string of dictionary
                                                        on the command line as you would via JSON RPC

                                                          ... --locations="{'country': 'US', 'state': 'NH'}"

            --thumbnail_url=<thumbnail_url>: (str) thumbnail url
            --cover_url=<cover_url>        : (str) url of cover image
            --account_id=<account_id>      : (str) account to use for holding the transaction
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet
          --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
            --claim_address=<claim_address>: (str) address where the channel is sent to, if not specified
                                                   it will be determined automatically from the account
            --preview                      : (bool) do not broadcast the transaction
            --blocking                     : (bool) wait until transaction is in mempool

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        account = wallet.get_account_or_default(account_id)
        funding_accounts = wallet.get_accounts_or_all(funding_account_ids)
        self.valid_channel_name_or_error(name)
        amount = self.get_dewies_or_error('bid', bid, positive_value=True)
        claim_address = await self.get_receiving_address(claim_address, account)

        existing_channels = await self.ledger.get_channels(accounts=wallet.accounts, claim_name=name)
        if len(existing_channels) > 0:
            if not allow_duplicate_name:
                # TODO: use error from lbry.error
                raise Exception(
                    f"You already have a channel under the name '{name}'. "
                    f"Use --allow-duplicate-name flag to override."
                )

        claim = Claim()
        claim.channel.update(**kwargs)
        tx = await Transaction.claim_create(
            name, claim, amount, claim_address, funding_accounts, funding_accounts[0]
        )
        txo = tx.outputs[0]
        txo.set_channel_private_key(
            await funding_accounts[0].generate_channel_private_key()
        )

        await tx.sign(funding_accounts)

        if not preview:
            wallet.save()
            await self.broadcast_or_release(tx, blocking)
            self.component_manager.loop.create_task(self.storage.save_claims([self._old_get_temp_claim_info(
                tx, txo, claim_address, claim, name, dewies_to_lbc(amount)
            )]))
            self.component_manager.loop.create_task(self.analytics_manager.send_new_channel())
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT)
    async def jsonrpc_channel_update(
            self, claim_id, bid=None, account_id=None, wallet_id=None, claim_address=None,
            funding_account_ids=None, new_signing_key=False, preview=False,
            blocking=False, replace=False, **kwargs):
        """
        Update an existing channel claim.

        Usage:
            channel_update (<claim_id> | --claim_id=<claim_id>) [<bid> | --bid=<bid>]
                           [--title=<title>] [--description=<description>] [--email=<email>]
                           [--website_url=<website_url>]
                           [--featured=<featured>...] [--clear_featured]
                           [--tags=<tags>...] [--clear_tags]
                           [--languages=<languages>...] [--clear_languages]
                           [--locations=<locations>...] [--clear_locations]
                           [--thumbnail_url=<thumbnail_url>] [--cover_url=<cover_url>]
                           [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                           [--claim_address=<claim_address>] [--new_signing_key]
                           [--funding_account_ids=<funding_account_ids>...]
                           [--preview] [--blocking] [--replace]

        Options:
            --claim_id=<claim_id>          : (str) claim_id of the channel to update
            --bid=<bid>                    : (decimal) amount to back the claim
            --title=<title>                : (str) title of the publication
            --description=<description>    : (str) description of the publication
            --email=<email>                : (str) email of channel owner
            --website_url=<website_url>    : (str) website url
            --featured=<featured>          : (list) claim_ids of featured content in channel
            --clear_featured               : (bool) clear existing featured content (prior to adding new ones)
            --tags=<tags>                  : (list) add content tags
            --clear_tags                   : (bool) clear existing tags (prior to adding new ones)
            --languages=<languages>        : (list) languages used by the channel,
                                                    using RFC 5646 format, eg:
                                                    for English `--languages=en`
                                                    for Spanish (Spain) `--languages=es-ES`
                                                    for Spanish (Mexican) `--languages=es-MX`
                                                    for Chinese (Simplified) `--languages=zh-Hans`
                                                    for Chinese (Traditional) `--languages=zh-Hant`
            --clear_languages              : (bool) clear existing languages (prior to adding new ones)
            --locations=<locations>        : (list) locations of the channel, consisting of 2 letter
                                                    `country` code and a `state`, `city` and a postal
                                                    `code` along with a `latitude` and `longitude`.
                                                    for JSON RPC: pass a dictionary with aforementioned
                                                        attributes as keys, eg:
                                                        ...
                                                        "locations": [{'country': 'US', 'state': 'NH'}]
                                                        ...
                                                    for command line: pass a colon delimited list
                                                        with values in the following order:

                                                          "COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE"

                                                        making sure to include colon for blank values, for
                                                        example to provide only the city:

                                                          ... --locations="::Manchester"

                                                        with all values set:

                                                 ... --locations="US:NH:Manchester:03101:42.990605:-71.460989"

                                                        optionally, you can just pass the "LATITUDE:LONGITUDE":

                                                          ... --locations="42.990605:-71.460989"

                                                        finally, you can also pass JSON string of dictionary
                                                        on the command line as you would via JSON RPC

                                                          ... --locations="{'country': 'US', 'state': 'NH'}"

            --clear_locations              : (bool) clear existing locations (prior to adding new ones)
            --thumbnail_url=<thumbnail_url>: (str) thumbnail url
            --cover_url=<cover_url>        : (str) url of cover image
            --account_id=<account_id>      : (str) account in which to look for channel (default: all)
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet
          --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
            --claim_address=<claim_address>: (str) address where the channel is sent
            --new_signing_key              : (bool) generate a new signing key, will invalidate all previous publishes
            --preview                      : (bool) do not broadcast the transaction
            --blocking                     : (bool) wait until transaction is in mempool
            --replace                      : (bool) instead of modifying specific values on
                                                    the channel, this will clear all existing values
                                                    and only save passed in values, useful for form
                                                    submissions where all values are always set

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        funding_accounts = wallet.get_accounts_or_all(funding_account_ids)
        if account_id:
            account = wallet.get_account_or_error(account_id)
            accounts = [account]
        else:
            account = wallet.default_account
            accounts = wallet.accounts

        existing_channels = await self.ledger.get_claims(
            wallet=wallet, accounts=accounts, claim_id=claim_id
        )
        if len(existing_channels) != 1:
            account_ids = ', '.join(f"'{account.id}'" for account in accounts)
            # TODO: use error from lbry.error
            raise Exception(
                f"Can't find the channel '{claim_id}' in account(s) {account_ids}."
            )
        old_txo = existing_channels[0]
        if not old_txo.claim.is_channel:
            # TODO: use error from lbry.error
            raise Exception(
                f"A claim with id '{claim_id}' was found but it is not a channel."
            )

        if bid is not None:
            amount = self.get_dewies_or_error('bid', bid, positive_value=True)
        else:
            amount = old_txo.amount

        if claim_address is not None:
            self.valid_address_or_error(claim_address)
        else:
            claim_address = old_txo.get_address(account.ledger)

        if replace:
            claim = Claim()
            claim.channel.public_key_bytes = old_txo.claim.channel.public_key_bytes
        else:
            claim = Claim.from_bytes(old_txo.claim.to_bytes())
        claim.channel.update(**kwargs)
        tx = await Transaction.claim_update(
            old_txo, claim, amount, claim_address, funding_accounts, funding_accounts[0]
        )
        new_txo = tx.outputs[0]

        if new_signing_key:
            new_txo.set_channel_private_key(
                await funding_accounts[0].generate_channel_private_key()
            )
        else:
            new_txo.private_key = old_txo.private_key

        new_txo.script.generate()

        await tx.sign(funding_accounts)

        if not preview:
            wallet.save()
            await self.broadcast_or_release(tx, blocking)
            self.component_manager.loop.create_task(self.storage.save_claims([self._old_get_temp_claim_info(
                tx, new_txo, claim_address, new_txo.claim, new_txo.claim_name, dewies_to_lbc(amount)
            )]))
            self.component_manager.loop.create_task(self.analytics_manager.send_new_channel())
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT)
    async def jsonrpc_channel_sign(
            self, channel_name=None, channel_id=None, hexdata=None, channel_account_id=None, wallet_id=None):
        """
        Signs data using the specified channel signing key.

        Usage:
            channel_sign [<channel_name> | --channel_name=<channel_name>]
                         [<channel_id> | --channel_id=<channel_id>] [<hexdata> | --hexdata=<hexdata>]
                         [--channel_account_id=<channel_account_id>...] [--wallet_id=<wallet_id>]

        Options:
            --channel_name=<channel_name>            : (str) name of channel used to sign (or use channel id)
            --channel_id=<channel_id>                : (str) claim id of channel used to sign (or use channel name)
            --hexdata=<hexdata>                      : (str) data to sign, encoded as hexadecimal
            --channel_account_id=<channel_account_id>: (str) one or more account ids for accounts to look in
                                                             for channel certificates, defaults to all accounts.
            --wallet_id=<wallet_id>                  : (str) restrict operation to specific wallet

        Returns:
            (dict) Signature if successfully made, (None) or an error otherwise
            {
                "signature":    (str) The signature of the comment,
                "signing_ts":   (str) The timestamp used to sign the comment,
            }
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        signing_channel = await self.get_channel_or_error(
            wallet, channel_account_id, channel_id, channel_name, for_signing=True
        )
        timestamp = str(int(time.time()))
        signature = signing_channel.sign_data(unhexlify(str(hexdata)), timestamp)
        return {
            'signature': signature,
            'signing_ts': timestamp
        }

    @requires(WALLET_COMPONENT)
    async def jsonrpc_channel_abandon(
            self, claim_id=None, txid=None, nout=None, account_id=None, wallet_id=None,
            preview=False, blocking=True):
        """
        Abandon one of my channel claims.

        Usage:
            channel_abandon [<claim_id> | --claim_id=<claim_id>]
                            [<txid> | --txid=<txid>] [<nout> | --nout=<nout>]
                            [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                            [--preview] [--blocking]

        Options:
            --claim_id=<claim_id>     : (str) claim_id of the claim to abandon
            --txid=<txid>             : (str) txid of the claim to abandon
            --nout=<nout>             : (int) nout of the claim to abandon
            --account_id=<account_id> : (str) id of the account to use
            --wallet_id=<wallet_id>   : (str) restrict operation to specific wallet
            --preview                 : (bool) do not broadcast the transaction
            --blocking                : (bool) wait until abandon is in mempool

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        if account_id:
            account = wallet.get_account_or_error(account_id)
            accounts = [account]
        else:
            account = wallet.default_account
            accounts = wallet.accounts

        if txid is not None and nout is not None:
            claims = await self.ledger.get_claims(
                wallet=wallet, accounts=accounts, **{'txo.txid': txid, 'txo.position': nout}
            )
        elif claim_id is not None:
            claims = await self.ledger.get_claims(
                wallet=wallet, accounts=accounts, claim_id=claim_id
            )
        else:
            # TODO: use error from lbry.error
            raise Exception('Must specify claim_id, or txid and nout')

        if not claims:
            # TODO: use error from lbry.error
            raise Exception('No claim found for the specified claim_id or txid:nout')

        tx = await Transaction.create(
            [Input.spend(txo) for txo in claims], [], [account], account
        )

        if not preview:
            await self.broadcast_or_release(tx, blocking)
            self.component_manager.loop.create_task(self.analytics_manager.send_claim_action('abandon'))
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT)
    def jsonrpc_channel_list(self, *args, **kwargs):
        """
        List my channel claims.

        Usage:
            channel_list [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]
                         [--name=<name>...] [--claim_id=<claim_id>...] [--is_spent]
                         [--page=<page>] [--page_size=<page_size>] [--resolve] [--no_totals]

        Options:
            --name=<name>              : (str or list) channel name
            --claim_id=<claim_id>      : (str or list) channel id
            --is_spent                 : (bool) shows previous channel updates and abandons
            --account_id=<account_id>  : (str) id of the account to use
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination
            --resolve                  : (bool) resolves each channel to provide additional metadata
            --no_totals                : (bool) do not calculate the total number of pages and items in result set
                                                (significant performance boost)

        Returns: {Paginated[Output]}
        """
        kwargs['type'] = 'channel'
        if 'is_spent' not in kwargs or not kwargs['is_spent']:
            kwargs['is_not_spent'] = True
        return self.jsonrpc_txo_list(*args, **kwargs)

    @requires(WALLET_COMPONENT)
    async def jsonrpc_channel_export(self, channel_id=None, channel_name=None, account_id=None, wallet_id=None):
        """
        Export channel private key.

        Usage:
            channel_export (<channel_id> | --channel_id=<channel_id> | --channel_name=<channel_name>)
                           [--account_id=<account_id>...] [--wallet_id=<wallet_id>]

        Options:
            --channel_id=<channel_id>     : (str) claim id of channel to export
            --channel_name=<channel_name> : (str) name of channel to export
            --account_id=<account_id>     : (str) one or more account ids for accounts
                                                  to look in for channels, defaults to
                                                  all accounts.
            --wallet_id=<wallet_id>       : (str) restrict operation to specific wallet

        Returns:
            (str) serialized channel private key
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        channel = await self.get_channel_or_error(wallet, account_id, channel_id, channel_name, for_signing=True)
        address = channel.get_address(self.ledger)
        public_key = await self.ledger.get_public_key_for_address(wallet, address)
        if not public_key:
            # TODO: use error from lbry.error
            raise Exception("Can't find public key for address holding the channel.")
        export = {
            'name': channel.claim_name,
            'channel_id': channel.claim_id,
            'holding_address': address,
            'holding_public_key': public_key.extended_key_string(),
            'signing_private_key': channel.private_key.signing_key.to_pem().decode()
        }
        return base58.b58encode(json.dumps(export, separators=(',', ':')))

    @requires(WALLET_COMPONENT)
    async def jsonrpc_channel_import(self, channel_data, wallet_id=None):
        """
        Import serialized channel private key (to allow signing new streams to the channel)

        Usage:
            channel_import (<channel_data> | --channel_data=<channel_data>) [--wallet_id=<wallet_id>]

        Options:
            --channel_data=<channel_data> : (str) serialized channel, as exported by channel export
            --wallet_id=<wallet_id>       : (str) import into specific wallet

        Returns:
            (dict) Result dictionary
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)

        decoded = base58.b58decode(channel_data)
        data = json.loads(decoded)
        channel_private_key = PrivateKey.from_pem(
            self.ledger, data['signing_private_key']
        )

        # check that the holding_address hasn't changed since the export was made
        holding_address = data['holding_address']
        channels, _, _, _ = await self.ledger.claim_search(
            wallet.accounts, public_key_id=channel_private_key.address
        )
        if channels and channels[0].get_address(self.ledger) != holding_address:
            holding_address = channels[0].get_address(self.ledger)

        account = await self.ledger.get_account_for_address(wallet, holding_address)
        if account:
            # Case 1: channel holding address is in one of the accounts we already have
            #         simply add the certificate to existing account
            pass
        else:
            # Case 2: channel holding address hasn't changed and thus is in the bundled read-only account
            #         create a single-address holding account to manage the channel
            if holding_address == data['holding_address']:
                account = Account.from_dict(self.ledger, wallet, {
                    'name': f"Holding Account For Channel {data['name']}",
                    'public_key': data['holding_public_key'],
                    'address_generator': {'name': 'single-address'}
                })
                if self.ledger.network.is_connected:
                    await self.ledger.subscribe_account(account)
                    await self.ledger._update_tasks.done.wait()
            # Case 3: the holding address has changed and we can't create or find an account for it
            else:
                # TODO: use error from lbry.error
                raise Exception(
                    "Channel owning account has changed since the channel was exported and "
                    "it is not an account to which you have access."
                )
        account.add_channel_private_key(channel_private_key)
        wallet.save()
        return f"Added channel signing key for {data['name']}."

    STREAM_DOC = """
    Create, update, abandon, list and inspect your stream claims.
    """

    @requires(WALLET_COMPONENT, FILE_MANAGER_COMPONENT, BLOB_COMPONENT, DATABASE_COMPONENT)
    async def jsonrpc_publish(self, name, **kwargs):
        """
        Create or replace a stream claim at a given name (use 'stream create/update' for more control).

        Usage:
            publish (<name> | --name=<name>) [--bid=<bid>] [--file_path=<file_path>]
                    [--file_name=<file_name>] [--file_hash=<file_hash>] [--validate_file] [--optimize_file]
                    [--fee_currency=<fee_currency>] [--fee_amount=<fee_amount>] [--fee_address=<fee_address>]
                    [--title=<title>] [--description=<description>] [--author=<author>]
                    [--tags=<tags>...] [--languages=<languages>...] [--locations=<locations>...]
                    [--license=<license>] [--license_url=<license_url>] [--thumbnail_url=<thumbnail_url>]
                    [--release_time=<release_time>] [--width=<width>] [--height=<height>] [--duration=<duration>]
                    [--sd_hash=<sd_hash>] [--channel_id=<channel_id> | --channel_name=<channel_name>]
                    [--channel_account_id=<channel_account_id>...]
                    [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                    [--claim_address=<claim_address>] [--funding_account_ids=<funding_account_ids>...]
                    [--preview] [--blocking]

        Options:
            --name=<name>                  : (str) name of the content (can only consist of a-z A-Z 0-9 and -(dash))
            --bid=<bid>                    : (decimal) amount to back the claim
            --file_path=<file_path>        : (str) path to file to be associated with name.
            --file_name=<file_name>        : (str) name of file to be associated with stream.
            --file_hash=<file_hash>        : (str) hash of file to be associated with stream.
            --validate_file                : (bool) validate that the video container and encodings match
                                             common web browser support or that optimization succeeds if specified.
                                             FFmpeg is required
            --optimize_file                : (bool) transcode the video & audio if necessary to ensure
                                             common web browser support. FFmpeg is required
            --fee_currency=<fee_currency>  : (string) specify fee currency
            --fee_amount=<fee_amount>      : (decimal) content download fee
            --fee_address=<fee_address>    : (str) address where to send fee payments, will use
                                                   value from --claim_address if not provided
            --title=<title>                : (str) title of the publication
            --description=<description>    : (str) description of the publication
            --author=<author>              : (str) author of the publication. The usage for this field is not
                                             the same as for channels. The author field is used to credit an author
                                             who is not the publisher and is not represented by the channel. For
                                             example, a pdf file of 'The Odyssey' has an author of 'Homer' but may
                                             by published to a channel such as '@classics', or to no channel at all
            --tags=<tags>                  : (list) add content tags
            --languages=<languages>        : (list) languages used by the channel,
                                                    using RFC 5646 format, eg:
                                                    for English `--languages=en`
                                                    for Spanish (Spain) `--languages=es-ES`
                                                    for Spanish (Mexican) `--languages=es-MX`
                                                    for Chinese (Simplified) `--languages=zh-Hans`
                                                    for Chinese (Traditional) `--languages=zh-Hant`
            --locations=<locations>        : (list) locations relevant to the stream, consisting of 2 letter
                                                    `country` code and a `state`, `city` and a postal
                                                    `code` along with a `latitude` and `longitude`.
                                                    for JSON RPC: pass a dictionary with aforementioned
                                                        attributes as keys, eg:
                                                        ...
                                                        "locations": [{'country': 'US', 'state': 'NH'}]
                                                        ...
                                                    for command line: pass a colon delimited list
                                                        with values in the following order:

                                                          "COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE"

                                                        making sure to include colon for blank values, for
                                                        example to provide only the city:

                                                          ... --locations="::Manchester"

                                                        with all values set:

                                                 ... --locations="US:NH:Manchester:03101:42.990605:-71.460989"

                                                        optionally, you can just pass the "LATITUDE:LONGITUDE":

                                                          ... --locations="42.990605:-71.460989"

                                                        finally, you can also pass JSON string of dictionary
                                                        on the command line as you would via JSON RPC

                                                          ... --locations="{'country': 'US', 'state': 'NH'}"

            --license=<license>            : (str) publication license
            --license_url=<license_url>    : (str) publication license url
            --thumbnail_url=<thumbnail_url>: (str) thumbnail url
            --release_time=<release_time>  : (int) original public release of content, seconds since UNIX epoch
            --width=<width>                : (int) image/video width, automatically calculated from media file
            --height=<height>              : (int) image/video height, automatically calculated from media file
            --duration=<duration>          : (int) audio/video duration in seconds, automatically calculated
            --sd_hash=<sd_hash>            : (str) sd_hash of stream
            --channel_id=<channel_id>      : (str) claim id of the publisher channel
            --channel_name=<channel_name>  : (str) name of publisher channel
          --channel_account_id=<channel_account_id>: (str) one or more account ids for accounts to look in
                                                   for channel certificates, defaults to all accounts.
            --account_id=<account_id>      : (str) account to use for holding the transaction
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet
          --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
            --claim_address=<claim_address>: (str) address where the claim is sent to, if not specified
                                                   it will be determined automatically from the account
            --preview                      : (bool) do not broadcast the transaction
            --blocking                     : (bool) wait until transaction is in mempool

        Returns: {Transaction}
        """
        self.valid_stream_name_or_error(name)
        wallet = self.wallet_manager.get_wallet_or_default(kwargs.get('wallet_id'))
        if kwargs.get('account_id'):
            accounts = [wallet.get_account_or_error(kwargs.get('account_id'))]
        else:
            accounts = wallet.accounts
        claims = await self.ledger.get_claims(
            wallet=wallet, accounts=accounts, claim_name=name
        )
        if len(claims) == 0:
            if 'bid' not in kwargs:
                # TODO: use error from lbry.error
                raise Exception("'bid' is a required argument for new publishes.")
            return await self.jsonrpc_stream_create(name, **kwargs)
        elif len(claims) == 1:
            assert claims[0].claim.is_stream, f"Claim at name '{name}' is not a stream claim."
            return await self.jsonrpc_stream_update(claims[0].claim_id, replace=True, **kwargs)
        # TODO: use error from lbry.error
        raise Exception(
            f"There are {len(claims)} claims for '{name}', please use 'stream update' command "
            f"to update a specific stream claim."
        )

    @requires(WALLET_COMPONENT, FILE_MANAGER_COMPONENT, BLOB_COMPONENT, DATABASE_COMPONENT)
    async def jsonrpc_stream_repost(
            self, name, bid, claim_id, allow_duplicate_name=False, channel_id=None,
            channel_name=None, channel_account_id=None, account_id=None, wallet_id=None,
            claim_address=None, funding_account_ids=None, preview=False, blocking=False, **kwargs):
        """
            Creates a claim that references an existing stream by its claim id.

            Usage:
                stream_repost (<name> | --name=<name>) (<bid> | --bid=<bid>) (<claim_id> | --claim_id=<claim_id>)
                        [--allow_duplicate_name=<allow_duplicate_name>]
                        [--title=<title>] [--description=<description>] [--tags=<tags>...]
                        [--channel_id=<channel_id> | --channel_name=<channel_name>]
                        [--channel_account_id=<channel_account_id>...]
                        [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                        [--claim_address=<claim_address>] [--funding_account_ids=<funding_account_ids>...]
                        [--preview] [--blocking]

            Options:
                --name=<name>                  : (str) name of the content (can only consist of a-z A-Z 0-9 and -(dash))
                --bid=<bid>                    : (decimal) amount to back the claim
                --claim_id=<claim_id>          : (str) id of the claim being reposted
                --allow_duplicate_name=<allow_duplicate_name> : (bool) create new claim even if one already exists with
                                                                       given name. default: false.
                --title=<title>                : (str) title of the repost
                --description=<description>    : (str) description of the repost
                --tags=<tags>                  : (list) add repost tags
                --channel_id=<channel_id>      : (str) claim id of the publisher channel
                --channel_name=<channel_name>  : (str) name of the publisher channel
                --channel_account_id=<channel_account_id>: (str) one or more account ids for accounts to look in
                                                                 for channel certificates, defaults to all accounts.
                --account_id=<account_id>      : (str) account to use for holding the transaction
                --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet
                --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
                --claim_address=<claim_address>: (str) address where the claim is sent to, if not specified
                                                       it will be determined automatically from the account
                --preview                      : (bool) do not broadcast the transaction
                --blocking                     : (bool) wait until transaction is in mempool

            Returns: {Transaction}
            """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        self.valid_stream_name_or_error(name)
        account = wallet.get_account_or_default(account_id)
        funding_accounts = wallet.get_accounts_or_all(funding_account_ids)
        channel = await self.get_channel_or_none(wallet, channel_account_id, channel_id, channel_name, for_signing=True)
        amount = self.get_dewies_or_error('bid', bid, positive_value=True)
        claim_address = await self.get_receiving_address(claim_address, account)
        claims = await account.get_claims(claim_name=name)
        if len(claims) > 0:
            if not allow_duplicate_name:
                # TODO: use error from lbry.error
                raise Exception(
                    f"You already have a stream claim published under the name '{name}'. "
                    f"Use --allow-duplicate-name flag to override."
                )
        if not VALID_FULL_CLAIM_ID.fullmatch(claim_id):
            # TODO: use error from lbry.error
            raise Exception('Invalid claim id. It is expected to be a 40 characters long hexadecimal string.')

        claim = Claim()
        claim.repost.update(**kwargs)
        claim.repost.reference.claim_id = claim_id
        tx = await Transaction.claim_create(
            name, claim, amount, claim_address, funding_accounts, funding_accounts[0], channel
        )
        new_txo = tx.outputs[0]

        if channel:
            new_txo.sign(channel)
        await tx.sign(funding_accounts)

        if not preview:
            await self.broadcast_or_release(tx, blocking)
            self.component_manager.loop.create_task(self.analytics_manager.send_claim_action('publish'))
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT, FILE_MANAGER_COMPONENT, BLOB_COMPONENT, DATABASE_COMPONENT)
    async def jsonrpc_stream_create(
            self, name, bid, file_path=None, allow_duplicate_name=False,
            channel_id=None, channel_name=None, channel_account_id=None,
            account_id=None, wallet_id=None, claim_address=None, funding_account_ids=None,
            preview=False, blocking=False, validate_file=False, optimize_file=False, **kwargs):
        """
        Make a new stream claim and announce the associated file to lbrynet.

        Usage:
            stream_create (<name> | --name=<name>) (<bid> | --bid=<bid>) [<file_path> | --file_path=<file_path>]
                    [--file_name=<file_name>] [--file_hash=<file_hash>] [--validate_file] [--optimize_file]
                    [--allow_duplicate_name=<allow_duplicate_name>]
                    [--fee_currency=<fee_currency>] [--fee_amount=<fee_amount>] [--fee_address=<fee_address>]
                    [--title=<title>] [--description=<description>] [--author=<author>]
                    [--tags=<tags>...] [--languages=<languages>...] [--locations=<locations>...]
                    [--license=<license>] [--license_url=<license_url>] [--thumbnail_url=<thumbnail_url>]
                    [--release_time=<release_time>] [--width=<width>] [--height=<height>] [--duration=<duration>]
                    [--sd_hash=<sd_hash>] [--channel_id=<channel_id> | --channel_name=<channel_name>]
                    [--channel_account_id=<channel_account_id>...]
                    [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                    [--claim_address=<claim_address>] [--funding_account_ids=<funding_account_ids>...]
                    [--preview] [--blocking]

        Options:
            --name=<name>                  : (str) name of the content (can only consist of a-z A-Z 0-9 and -(dash))
            --bid=<bid>                    : (decimal) amount to back the claim
            --file_path=<file_path>        : (str) path to file to be associated with name.
            --file_name=<file_name>        : (str) name of file to be associated with stream.
            --file_hash=<file_hash>        : (str) hash of file to be associated with stream.
            --validate_file                : (bool) validate that the video container and encodings match
                                             common web browser support or that optimization succeeds if specified.
                                             FFmpeg is required
            --optimize_file                : (bool) transcode the video & audio if necessary to ensure
                                             common web browser support. FFmpeg is required
        --allow_duplicate_name=<allow_duplicate_name> : (bool) create new claim even if one already exists with
                                              given name. default: false.
            --fee_currency=<fee_currency>  : (string) specify fee currency
            --fee_amount=<fee_amount>      : (decimal) content download fee
            --fee_address=<fee_address>    : (str) address where to send fee payments, will use
                                                   value from --claim_address if not provided
            --title=<title>                : (str) title of the publication
            --description=<description>    : (str) description of the publication
            --author=<author>              : (str) author of the publication. The usage for this field is not
                                             the same as for channels. The author field is used to credit an author
                                             who is not the publisher and is not represented by the channel. For
                                             example, a pdf file of 'The Odyssey' has an author of 'Homer' but may
                                             by published to a channel such as '@classics', or to no channel at all
            --tags=<tags>                  : (list) add content tags
            --languages=<languages>        : (list) languages used by the channel,
                                                    using RFC 5646 format, eg:
                                                    for English `--languages=en`
                                                    for Spanish (Spain) `--languages=es-ES`
                                                    for Spanish (Mexican) `--languages=es-MX`
                                                    for Chinese (Simplified) `--languages=zh-Hans`
                                                    for Chinese (Traditional) `--languages=zh-Hant`
            --locations=<locations>        : (list) locations relevant to the stream, consisting of 2 letter
                                                    `country` code and a `state`, `city` and a postal
                                                    `code` along with a `latitude` and `longitude`.
                                                    for JSON RPC: pass a dictionary with aforementioned
                                                        attributes as keys, eg:
                                                        ...
                                                        "locations": [{'country': 'US', 'state': 'NH'}]
                                                        ...
                                                    for command line: pass a colon delimited list
                                                        with values in the following order:

                                                          "COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE"

                                                        making sure to include colon for blank values, for
                                                        example to provide only the city:

                                                          ... --locations="::Manchester"

                                                        with all values set:

                                                 ... --locations="US:NH:Manchester:03101:42.990605:-71.460989"

                                                        optionally, you can just pass the "LATITUDE:LONGITUDE":

                                                          ... --locations="42.990605:-71.460989"

                                                        finally, you can also pass JSON string of dictionary
                                                        on the command line as you would via JSON RPC

                                                          ... --locations="{'country': 'US', 'state': 'NH'}"

            --license=<license>            : (str) publication license
            --license_url=<license_url>    : (str) publication license url
            --thumbnail_url=<thumbnail_url>: (str) thumbnail url
            --release_time=<release_time>  : (int) original public release of content, seconds since UNIX epoch
            --width=<width>                : (int) image/video width, automatically calculated from media file
            --height=<height>              : (int) image/video height, automatically calculated from media file
            --duration=<duration>          : (int) audio/video duration in seconds, automatically calculated
            --sd_hash=<sd_hash>            : (str) sd_hash of stream
            --channel_id=<channel_id>      : (str) claim id of the publisher channel
            --channel_name=<channel_name>  : (str) name of the publisher channel
            --channel_account_id=<channel_account_id>: (str) one or more account ids for accounts to look in
                                                   for channel certificates, defaults to all accounts.
            --account_id=<account_id>      : (str) account to use for holding the transaction
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet
            --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
            --claim_address=<claim_address>: (str) address where the claim is sent to, if not specified
                                                   it will be determined automatically from the account
            --preview                      : (bool) do not broadcast the transaction
            --blocking                     : (bool) wait until transaction is in mempool

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        self.valid_stream_name_or_error(name)
        account = wallet.get_account_or_default(account_id)
        funding_accounts = wallet.get_accounts_or_all(funding_account_ids)
        channel = await self.get_channel_or_none(wallet, channel_account_id, channel_id, channel_name, for_signing=True)
        amount = self.get_dewies_or_error('bid', bid, positive_value=True)
        claim_address = await self.get_receiving_address(claim_address, account)
        kwargs['fee_address'] = self.get_fee_address(kwargs, claim_address)

        claims = await account.get_claims(claim_name=name)
        if len(claims) > 0:
            if not allow_duplicate_name:
                # TODO: use error from lbry.error
                raise Exception(
                    f"You already have a stream claim published under the name '{name}'. "
                    f"Use --allow-duplicate-name flag to override."
                )

        if file_path is not None:
            file_path, spec = await self._video_file_analyzer.verify_or_repair(
                validate_file, optimize_file, file_path, ignore_non_video=True
            )
            kwargs.update(spec)

        claim = Claim()
        if file_path is not None:
            claim.stream.update(file_path=file_path, sd_hash='0' * 96, **kwargs)
        else:
            claim.stream.update(**kwargs)
        tx = await Transaction.claim_create(
            name, claim, amount, claim_address, funding_accounts, funding_accounts[0], channel
        )
        new_txo = tx.outputs[0]

        file_stream = None
        if not preview and file_path is not None:
            file_stream = await self.file_manager.create_stream(file_path)
            claim.stream.source.sd_hash = file_stream.sd_hash
            new_txo.script.generate()

        if channel:
            new_txo.sign(channel)
        await tx.sign(funding_accounts)

        if not preview:
            await self.broadcast_or_release(tx, blocking)

            async def save_claims():
                await self.storage.save_claims([self._old_get_temp_claim_info(
                    tx, new_txo, claim_address, claim, name, dewies_to_lbc(amount)
                )])
                if file_path is not None:
                    await self.storage.save_content_claim(file_stream.stream_hash, new_txo.id)

            self.component_manager.loop.create_task(save_claims())
            self.component_manager.loop.create_task(self.analytics_manager.send_claim_action('publish'))
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT, FILE_MANAGER_COMPONENT, BLOB_COMPONENT, DATABASE_COMPONENT)
    async def jsonrpc_stream_update(
            self, claim_id, bid=None, file_path=None,
            channel_id=None, channel_name=None, channel_account_id=None, clear_channel=False,
            account_id=None, wallet_id=None, claim_address=None, funding_account_ids=None,
            preview=False, blocking=False, replace=False, validate_file=False, optimize_file=False, **kwargs):
        """
        Update an existing stream claim and if a new file is provided announce it to lbrynet.

        Usage:
            stream_update (<claim_id> | --claim_id=<claim_id>) [--bid=<bid>] [--file_path=<file_path>]
                    [--validate_file] [--optimize_file]
                    [--file_name=<file_name>] [--file_size=<file_size>] [--file_hash=<file_hash>]
                    [--fee_currency=<fee_currency>] [--fee_amount=<fee_amount>]
                    [--fee_address=<fee_address>] [--clear_fee]
                    [--title=<title>] [--description=<description>] [--author=<author>]
                    [--tags=<tags>...] [--clear_tags]
                    [--languages=<languages>...] [--clear_languages]
                    [--locations=<locations>...] [--clear_locations]
                    [--license=<license>] [--license_url=<license_url>] [--thumbnail_url=<thumbnail_url>]
                    [--release_time=<release_time>] [--width=<width>] [--height=<height>] [--duration=<duration>]
                    [--sd_hash=<sd_hash>] [--channel_id=<channel_id> | --channel_name=<channel_name> | --clear_channel]
                    [--channel_account_id=<channel_account_id>...]
                    [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                    [--claim_address=<claim_address>] [--funding_account_ids=<funding_account_ids>...]
                    [--preview] [--blocking] [--replace]

        Options:
            --claim_id=<claim_id>          : (str) id of the stream claim to update
            --bid=<bid>                    : (decimal) amount to back the claim
            --file_path=<file_path>        : (str) path to file to be associated with name.
            --validate_file                : (bool) validate that the video container and encodings match
                                             common web browser support or that optimization succeeds if specified.
                                             FFmpeg is required and file_path must be specified.
            --optimize_file                : (bool) transcode the video & audio if necessary to ensure common
                                             web browser support. FFmpeg is required and file_path must be specified.
            --file_name=<file_name>        : (str) override file name, defaults to name from file_path.
            --file_size=<file_size>        : (str) override file size, otherwise automatically computed.
            --file_hash=<file_hash>        : (str) override file hash, otherwise automatically computed.
            --fee_currency=<fee_currency>  : (string) specify fee currency
            --fee_amount=<fee_amount>      : (decimal) content download fee
            --fee_address=<fee_address>    : (str) address where to send fee payments, will use
                                                   value from --claim_address if not provided
            --clear_fee                    : (bool) clear previously set fee
            --title=<title>                : (str) title of the publication
            --description=<description>    : (str) description of the publication
            --author=<author>              : (str) author of the publication. The usage for this field is not
                                             the same as for channels. The author field is used to credit an author
                                             who is not the publisher and is not represented by the channel. For
                                             example, a pdf file of 'The Odyssey' has an author of 'Homer' but may
                                             by published to a channel such as '@classics', or to no channel at all
            --tags=<tags>                  : (list) add content tags
            --clear_tags                   : (bool) clear existing tags (prior to adding new ones)
            --languages=<languages>        : (list) languages used by the channel,
                                                    using RFC 5646 format, eg:
                                                    for English `--languages=en`
                                                    for Spanish (Spain) `--languages=es-ES`
                                                    for Spanish (Mexican) `--languages=es-MX`
                                                    for Chinese (Simplified) `--languages=zh-Hans`
                                                    for Chinese (Traditional) `--languages=zh-Hant`
            --clear_languages              : (bool) clear existing languages (prior to adding new ones)
            --locations=<locations>        : (list) locations relevant to the stream, consisting of 2 letter
                                                    `country` code and a `state`, `city` and a postal
                                                    `code` along with a `latitude` and `longitude`.
                                                    for JSON RPC: pass a dictionary with aforementioned
                                                        attributes as keys, eg:
                                                        ...
                                                        "locations": [{'country': 'US', 'state': 'NH'}]
                                                        ...
                                                    for command line: pass a colon delimited list
                                                        with values in the following order:

                                                          "COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE"

                                                        making sure to include colon for blank values, for
                                                        example to provide only the city:

                                                          ... --locations="::Manchester"

                                                        with all values set:

                                                 ... --locations="US:NH:Manchester:03101:42.990605:-71.460989"

                                                        optionally, you can just pass the "LATITUDE:LONGITUDE":

                                                          ... --locations="42.990605:-71.460989"

                                                        finally, you can also pass JSON string of dictionary
                                                        on the command line as you would via JSON RPC

                                                          ... --locations="{'country': 'US', 'state': 'NH'}"

            --clear_locations              : (bool) clear existing locations (prior to adding new ones)
            --license=<license>            : (str) publication license
            --license_url=<license_url>    : (str) publication license url
            --thumbnail_url=<thumbnail_url>: (str) thumbnail url
            --release_time=<release_time>  : (int) original public release of content, seconds since UNIX epoch
            --width=<width>                : (int) image/video width, automatically calculated from media file
            --height=<height>              : (int) image/video height, automatically calculated from media file
            --duration=<duration>          : (int) audio/video duration in seconds, automatically calculated
            --sd_hash=<sd_hash>            : (str) sd_hash of stream
            --channel_id=<channel_id>      : (str) claim id of the publisher channel
            --channel_name=<channel_name>  : (str) name of the publisher channel
            --clear_channel                : (bool) remove channel signature
          --channel_account_id=<channel_account_id>: (str) one or more account ids for accounts to look in
                                                   for channel certificates, defaults to all accounts.
            --account_id=<account_id>      : (str) account in which to look for stream (default: all)
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet
          --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
            --claim_address=<claim_address>: (str) address where the claim is sent to, if not specified
                                                   it will be determined automatically from the account
            --preview                      : (bool) do not broadcast the transaction
            --blocking                     : (bool) wait until transaction is in mempool
            --replace                      : (bool) instead of modifying specific values on
                                                    the stream, this will clear all existing values
                                                    and only save passed in values, useful for form
                                                    submissions where all values are always set

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        funding_accounts = wallet.get_accounts_or_all(funding_account_ids)
        if account_id:
            account = wallet.get_account_or_error(account_id)
            accounts = [account]
        else:
            account = wallet.default_account
            accounts = wallet.accounts

        existing_claims = await self.ledger.get_claims(
            wallet=wallet, accounts=accounts, claim_id=claim_id
        )
        if len(existing_claims) != 1:
            account_ids = ', '.join(f"'{account.id}'" for account in accounts)
            raise InputValueError(
                f"Can't find the stream '{claim_id}' in account(s) {account_ids}."
            )

        old_txo = existing_claims[0]
        if not old_txo.claim.is_stream and not old_txo.claim.is_repost:
            # in principle it should work with any type of claim, but its safer to
            # limit it to ones we know won't be broken. in the future we can expand
            # this if we have a test case for e.g. channel or support claims
            raise InputValueError(
                f"A claim with id '{claim_id}' was found but it is not a stream or repost claim."
            )

        if bid is not None:
            amount = self.get_dewies_or_error('bid', bid, positive_value=True)
        else:
            amount = old_txo.amount

        if claim_address is not None:
            self.valid_address_or_error(claim_address)
        else:
            claim_address = old_txo.get_address(account.ledger)

        channel = None
        if not clear_channel and (channel_id or channel_name):
            channel = await self.get_channel_or_error(
                wallet, channel_account_id, channel_id, channel_name, for_signing=True)
        elif old_txo.claim.is_signed and not clear_channel and not replace:
            channel = old_txo.channel

        fee_address = self.get_fee_address(kwargs, claim_address)
        if fee_address:
            kwargs['fee_address'] = fee_address

        file_path, spec = await self._video_file_analyzer.verify_or_repair(
            validate_file, optimize_file, file_path, ignore_non_video=True
        )
        kwargs.update(spec)

        if replace:
            claim = Claim()
            if old_txo.claim.is_stream:
                if old_txo.claim.stream.has_source:
                    claim.stream.message.source.CopyFrom(
                        old_txo.claim.stream.message.source
                    )
                stream_type = old_txo.claim.stream.stream_type
                if stream_type:
                    old_stream_type = getattr(old_txo.claim.stream.message, stream_type)
                    new_stream_type = getattr(claim.stream.message, stream_type)
                    new_stream_type.CopyFrom(old_stream_type)
        else:
            claim = Claim.from_bytes(old_txo.claim.to_bytes())

        if old_txo.claim.is_stream:
            claim.stream.update(file_path=file_path, **kwargs)
        elif old_txo.claim.is_repost:
            claim.repost.update(**kwargs)

        if clear_channel:
            claim.clear_signature()
        tx = await Transaction.claim_update(
            old_txo, claim, amount, claim_address, funding_accounts, funding_accounts[0],
            channel if not clear_channel else None
        )

        new_txo = tx.outputs[0]
        stream_hash = None
        if not preview and old_txo.claim.is_stream:
            old_stream = self.file_manager.get_filtered(sd_hash=old_txo.claim.stream.source.sd_hash)
            old_stream = old_stream[0] if old_stream else None
            if file_path is not None:
                if old_stream:
                    await self.file_manager.delete(old_stream, delete_file=False)
                file_stream = await self.file_manager.create_stream(file_path)
                new_txo.claim.stream.source.sd_hash = file_stream.sd_hash
                new_txo.script.generate()
                stream_hash = file_stream.stream_hash
            elif old_stream:
                stream_hash = old_stream.stream_hash

        if channel:
            new_txo.sign(channel)
        await tx.sign(funding_accounts)

        if not preview:
            await self.broadcast_or_release(tx, blocking)

            async def save_claims():
                await self.storage.save_claims([self._old_get_temp_claim_info(
                    tx, new_txo, claim_address, new_txo.claim, new_txo.claim_name, dewies_to_lbc(amount)
                )])
                if stream_hash:
                    await self.storage.save_content_claim(stream_hash, new_txo.id)

            self.component_manager.loop.create_task(save_claims())
            self.component_manager.loop.create_task(self.analytics_manager.send_claim_action('publish'))
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT)
    async def jsonrpc_stream_abandon(
            self, claim_id=None, txid=None, nout=None, account_id=None, wallet_id=None,
            preview=False, blocking=False):
        """
        Abandon one of my stream claims.

        Usage:
            stream_abandon [<claim_id> | --claim_id=<claim_id>]
                           [<txid> | --txid=<txid>] [<nout> | --nout=<nout>]
                           [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                           [--preview] [--blocking]

        Options:
            --claim_id=<claim_id>     : (str) claim_id of the claim to abandon
            --txid=<txid>             : (str) txid of the claim to abandon
            --nout=<nout>             : (int) nout of the claim to abandon
            --account_id=<account_id> : (str) id of the account to use
            --wallet_id=<wallet_id>   : (str) restrict operation to specific wallet
            --preview                 : (bool) do not broadcast the transaction
            --blocking                : (bool) wait until abandon is in mempool

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        if account_id:
            account = wallet.get_account_or_error(account_id)
            accounts = [account]
        else:
            account = wallet.default_account
            accounts = wallet.accounts

        if txid is not None and nout is not None:
            claims = await self.ledger.get_claims(
                wallet=wallet, accounts=accounts, **{'txo.txid': txid, 'txo.position': nout}
            )
        elif claim_id is not None:
            claims = await self.ledger.get_claims(
                wallet=wallet, accounts=accounts, claim_id=claim_id
            )
        else:
            # TODO: use error from lbry.error
            raise Exception('Must specify claim_id, or txid and nout')

        if not claims:
            # TODO: use error from lbry.error
            raise Exception('No claim found for the specified claim_id or txid:nout')

        tx = await Transaction.create(
            [Input.spend(txo) for txo in claims], [], accounts, account
        )

        if not preview:
            await self.broadcast_or_release(tx, blocking)
            self.component_manager.loop.create_task(self.analytics_manager.send_claim_action('abandon'))
        else:
            await self.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT)
    def jsonrpc_stream_list(self, *args, **kwargs):
        """
        List my stream claims.

        Usage:
            stream_list [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]
                        [--name=<name>...] [--claim_id=<claim_id>...] [--is_spent]
                        [--page=<page>] [--page_size=<page_size>] [--resolve] [--no_totals]

        Options:
            --name=<name>              : (str or list) stream name
            --claim_id=<claim_id>      : (str or list) stream id
            --is_spent                 : (bool) shows previous stream updates and abandons
            --account_id=<account_id>  : (str) id of the account to query
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination
            --resolve                  : (bool) resolves each stream to provide additional metadata
            --no_totals                : (bool) do not calculate the total number of pages and items in result set
                                                (significant performance boost)

        Returns: {Paginated[Output]}
        """
        kwargs['type'] = 'stream'
        if 'is_spent' not in kwargs:
            kwargs['is_not_spent'] = True
        return self.jsonrpc_txo_list(*args, **kwargs)

    @requires(WALLET_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT, BLOB_COMPONENT,
              DHT_COMPONENT, DATABASE_COMPONENT)
    def jsonrpc_stream_cost_estimate(self, uri):
        """
        Get estimated cost for a lbry stream

        Usage:
            stream_cost_estimate (<uri> | --uri=<uri>)

        Options:
            --uri=<uri>      : (str) uri to use

        Returns:
            (float) Estimated cost in lbry credits, returns None if uri is not
                resolvable
        """
        return self.get_est_cost_from_uri(uri)

    COLLECTION_DOC = """
    Create, update, list, resolve, and abandon collections.
    """

    @requires(WALLET_COMPONENT)
    async def jsonrpc_collection_create(
            self, name, bid, claims, allow_duplicate_name=False,
            channel_id=None, channel_name=None, channel_account_id=None,
            account_id=None, wallet_id=None, claim_address=None, funding_account_ids=None,
            preview=False, blocking=False, **kwargs):
        """
        Create a new collection.

        Usage:
            collection_create (<name> | --name=<name>) (<bid> | --bid=<bid>)
                    (--claims=<claims>...)
                    [--allow_duplicate_name]
                    [--title=<title>] [--description=<description>]
                    [--tags=<tags>...] [--languages=<languages>...] [--locations=<locations>...]
                    [--thumbnail_url=<thumbnail_url>]
                    [--channel_id=<channel_id> | --channel_name=<channel_name>]
                    [--channel_account_id=<channel_account_id>...]
                    [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                    [--claim_address=<claim_address>] [--funding_account_ids=<funding_account_ids>...]
                    [--preview] [--blocking]

        Options:
            --name=<name>                  : (str) name of the collection
            --bid=<bid>                    : (decimal) amount to back the claim
            --claims=<claims>              : (list) claim ids to be included in the collection
            --allow_duplicate_name         : (bool) create new collection even if one already exists with
                                                    given name. default: false.
            --title=<title>                : (str) title of the collection
            --description=<description>    : (str) description of the collection
            --tags=<tags>                  : (list) content tags
            --clear_languages              : (bool) clear existing languages (prior to adding new ones)
            --languages=<languages>        : (list) languages used by the collection,
                                                    using RFC 5646 format, eg:
                                                    for English `--languages=en`
                                                    for Spanish (Spain) `--languages=es-ES`
                                                    for Spanish (Mexican) `--languages=es-MX`
                                                    for Chinese (Simplified) `--languages=zh-Hans`
                                                    for Chinese (Traditional) `--languages=zh-Hant`
            --locations=<locations>        : (list) locations of the collection, consisting of 2 letter
                                                    `country` code and a `state`, `city` and a postal
                                                    `code` along with a `latitude` and `longitude`.
                                                    for JSON RPC: pass a dictionary with aforementioned
                                                        attributes as keys, eg:
                                                        ...
                                                        "locations": [{'country': 'US', 'state': 'NH'}]
                                                        ...
                                                    for command line: pass a colon delimited list
                                                        with values in the following order:

                                                          "COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE"

                                                        making sure to include colon for blank values, for
                                                        example to provide only the city:

                                                          ... --locations="::Manchester"

                                                        with all values set:

                                                 ... --locations="US:NH:Manchester:03101:42.990605:-71.460989"

                                                        optionally, you can just pass the "LATITUDE:LONGITUDE":

                                                          ... --locations="42.990605:-71.460989"

                                                        finally, you can also pass JSON string of dictionary
                                                        on the command line as you would via JSON RPC

                                                          ... --locations="{'country': 'US', 'state': 'NH'}"

            --thumbnail_url=<thumbnail_url>: (str) thumbnail url
            --channel_id=<channel_id>      : (str) claim id of the publisher channel
            --channel_name=<channel_name>  : (str) name of the publisher channel
            --channel_account_id=<channel_account_id>: (str) one or more account ids for accounts to look in
                                                   for channel certificates, defaults to all accounts.
            --account_id=<account_id>      : (str) account to use for holding the transaction
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet
            --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
            --claim_address=<claim_address>: (str) address where the collection is sent to, if not specified
                                                   it will be determined automatically from the account
            --preview                      : (bool) do not broadcast the transaction
            --blocking                     : (bool) wait until transaction is in mempool

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        account = wallet.get_account_or_default(account_id)
        funding_accounts = wallet.get_accounts_or_all(funding_account_ids)
        self.valid_collection_name_or_error(name)
        channel = await self.get_channel_or_none(wallet, channel_account_id, channel_id, channel_name, for_signing=True)
        amount = self.get_dewies_or_error('bid', bid, positive_value=True)
        claim_address = await self.get_receiving_address(claim_address, account)

        existing_collections = await self.ledger.get_collections(accounts=wallet.accounts, claim_name=name)
        if len(existing_collections) > 0:
            if not allow_duplicate_name:
                # TODO: use error from lbry.error
                raise Exception(
                    f"You already have a collection under the name '{name}'. "
                    f"Use --allow-duplicate-name flag to override."
                )

        claim = Claim()
        claim.collection.update(claims=claims, **kwargs)
        tx = await Transaction.claim_create(
            name, claim, amount, claim_address, funding_accounts, funding_accounts[0], channel
        )
        new_txo = tx.outputs[0]

        if channel:
            new_txo.sign(channel)
        await tx.sign(funding_accounts)

        if not preview:
            await self.broadcast_or_release(tx, blocking)
            self.component_manager.loop.create_task(self.analytics_manager.send_claim_action('publish'))
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT)
    async def jsonrpc_collection_update(
            self, claim_id, bid=None,
            channel_id=None, channel_name=None, channel_account_id=None, clear_channel=False,
            account_id=None, wallet_id=None, claim_address=None, funding_account_ids=None,
            preview=False, blocking=False, replace=False, **kwargs):
        """
        Update an existing collection claim.

        Usage:
            collection_update (<claim_id> | --claim_id=<claim_id>) [--bid=<bid>]
                            [--claims=<claims>...] [--clear_claims]
                           [--title=<title>] [--description=<description>]
                           [--tags=<tags>...] [--clear_tags]
                           [--languages=<languages>...] [--clear_languages]
                           [--locations=<locations>...] [--clear_locations]
                           [--thumbnail_url=<thumbnail_url>] [--cover_url=<cover_url>]
                           [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                           [--claim_address=<claim_address>]
                           [--funding_account_ids=<funding_account_ids>...]
                           [--preview] [--blocking] [--replace]

        Options:
            --claim_id=<claim_id>          : (str) claim_id of the collection to update
            --bid=<bid>                    : (decimal) amount to back the claim
            --claims=<claims>              : (list) claim ids
            --clear_claims                 : (bool) clear existing claim references (prior to adding new ones)
            --title=<title>                : (str) title of the collection
            --description=<description>    : (str) description of the collection
            --tags=<tags>                  : (list) add content tags
            --clear_tags                   : (bool) clear existing tags (prior to adding new ones)
            --languages=<languages>        : (list) languages used by the collection,
                                                    using RFC 5646 format, eg:
                                                    for English `--languages=en`
                                                    for Spanish (Spain) `--languages=es-ES`
                                                    for Spanish (Mexican) `--languages=es-MX`
                                                    for Chinese (Simplified) `--languages=zh-Hans`
                                                    for Chinese (Traditional) `--languages=zh-Hant`
            --clear_languages              : (bool) clear existing languages (prior to adding new ones)
            --locations=<locations>        : (list) locations of the collection, consisting of 2 letter
                                                    `country` code and a `state`, `city` and a postal
                                                    `code` along with a `latitude` and `longitude`.
                                                    for JSON RPC: pass a dictionary with aforementioned
                                                        attributes as keys, eg:
                                                        ...
                                                        "locations": [{'country': 'US', 'state': 'NH'}]
                                                        ...
                                                    for command line: pass a colon delimited list
                                                        with values in the following order:

                                                          "COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE"

                                                        making sure to include colon for blank values, for
                                                        example to provide only the city:

                                                          ... --locations="::Manchester"

                                                        with all values set:

                                                 ... --locations="US:NH:Manchester:03101:42.990605:-71.460989"

                                                        optionally, you can just pass the "LATITUDE:LONGITUDE":

                                                          ... --locations="42.990605:-71.460989"

                                                        finally, you can also pass JSON string of dictionary
                                                        on the command line as you would via JSON RPC

                                                          ... --locations="{'country': 'US', 'state': 'NH'}"

            --clear_locations              : (bool) clear existing locations (prior to adding new ones)
            --thumbnail_url=<thumbnail_url>: (str) thumbnail url
            --account_id=<account_id>      : (str) account in which to look for collection (default: all)
            --wallet_id=<wallet_id>        : (str) restrict operation to specific wallet
          --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
            --claim_address=<claim_address>: (str) address where the collection is sent
            --preview                      : (bool) do not broadcast the transaction
            --blocking                     : (bool) wait until transaction is in mempool
            --replace                      : (bool) instead of modifying specific values on
                                                    the collection, this will clear all existing values
                                                    and only save passed in values, useful for form
                                                    submissions where all values are always set

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        funding_accounts = wallet.get_accounts_or_all(funding_account_ids)
        if account_id:
            account = wallet.get_account_or_error(account_id)
            accounts = [account]
        else:
            account = wallet.default_account
            accounts = wallet.accounts

        existing_collections = await self.ledger.get_collections(
            wallet=wallet, accounts=accounts, claim_id=claim_id
        )
        if len(existing_collections) != 1:
            account_ids = ', '.join(f"'{account.id}'" for account in accounts)
            # TODO: use error from lbry.error
            raise Exception(
                f"Can't find the collection '{claim_id}' in account(s) {account_ids}."
            )
        old_txo = existing_collections[0]
        if not old_txo.claim.is_collection:
            # TODO: use error from lbry.error
            raise Exception(
                f"A claim with id '{claim_id}' was found but it is not a collection."
            )

        if bid is not None:
            amount = self.get_dewies_or_error('bid', bid, positive_value=True)
        else:
            amount = old_txo.amount

        if claim_address is not None:
            self.valid_address_or_error(claim_address)
        else:
            claim_address = old_txo.get_address(account.ledger)

        channel = None
        if channel_id or channel_name:
            channel = await self.get_channel_or_error(
                wallet, channel_account_id, channel_id, channel_name, for_signing=True)
        elif old_txo.claim.is_signed and not clear_channel and not replace:
            channel = old_txo.channel

        if replace:
            claim = Claim()
            claim.collection.update(**kwargs)
        else:
            claim = Claim.from_bytes(old_txo.claim.to_bytes())
            claim.collection.update(**kwargs)
        tx = await Transaction.claim_update(
            old_txo, claim, amount, claim_address, funding_accounts, funding_accounts[0], channel
        )
        new_txo = tx.outputs[0]

        if channel:
            new_txo.sign(channel)
        await tx.sign(funding_accounts)

        if not preview:
            await self.broadcast_or_release(tx, blocking)
            self.component_manager.loop.create_task(self.analytics_manager.send_claim_action('publish'))
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT)
    async def jsonrpc_collection_abandon(self, *args, **kwargs):
        """
        Abandon one of my collection claims.

        Usage:
            collection_abandon [<claim_id> | --claim_id=<claim_id>]
                            [<txid> | --txid=<txid>] [<nout> | --nout=<nout>]
                            [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                            [--preview] [--blocking]

        Options:
            --claim_id=<claim_id>     : (str) claim_id of the claim to abandon
            --txid=<txid>             : (str) txid of the claim to abandon
            --nout=<nout>             : (int) nout of the claim to abandon
            --account_id=<account_id> : (str) id of the account to use
            --wallet_id=<wallet_id>   : (str) restrict operation to specific wallet
            --preview                 : (bool) do not broadcast the transaction
            --blocking                : (bool) wait until abandon is in mempool

        Returns: {Transaction}
        """
        return await self.jsonrpc_stream_abandon(*args, **kwargs)

    @requires(WALLET_COMPONENT)
    def jsonrpc_collection_list(
            self, resolve_claims=0, resolve=False, account_id=None,
            wallet_id=None, page=None, page_size=None):
        """
        List my collection claims.

        Usage:
            collection_list [--resolve_claims=<resolve_claims>] [--resolve] [<account_id> | --account_id=<account_id>]
                [--wallet_id=<wallet_id>] [--page=<page>] [--page_size=<page_size>]

        Options:
            --resolve                         : (bool) resolve collection claim
            --resolve_claims=<resolve_claims> : (int) resolve every claim
            --account_id=<account_id>         : (str) id of the account to use
            --wallet_id=<wallet_id>           : (str) restrict results to specific wallet
            --page=<page>                     : (int) page to return during paginating
            --page_size=<page_size>           : (int) number of items on page during pagination

        Returns: {Paginated[Output]}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        if account_id:
            account = wallet.get_account_or_error(account_id)
            collections = account.get_collections
            collection_count = account.get_collection_count
        else:
            collections = partial(self.ledger.get_collections, wallet=wallet, accounts=wallet.accounts)
            collection_count = partial(self.ledger.get_collection_count, wallet=wallet, accounts=wallet.accounts)
        return paginate_rows(
            collections, collection_count, page, page_size,
            resolve=resolve, resolve_claims=resolve_claims
        )

    async def jsonrpc_collection_resolve(
            self, claim_id=None, url=None, wallet_id=None, page=1, page_size=DEFAULT_PAGE_SIZE):
        """
        Resolve claims in the collection.

        Usage:
            collection_resolve (--claim_id=<claim_id> | --url=<url>)
                [--wallet_id=<wallet_id>] [--page=<page>] [--page_size=<page_size>]

        Options:
            --claim_id=<claim_id>      : (str) claim id of the collection
            --url=<url>                : (str) url of the collection
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination

        Returns: {Paginated[Output]}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)

        if claim_id:
            txo = await self.ledger.get_claim_by_claim_id(claim_id, wallet.accounts)
            if not isinstance(txo, Output) or not txo.is_claim:
                # TODO: use error from lbry.error
                raise Exception(f"Could not find collection with claim_id '{claim_id}'.")
        elif url:
            txo = (await self.ledger.resolve(wallet.accounts, [url]))[url]
            if not isinstance(txo, Output) or not txo.is_claim:
                # TODO: use error from lbry.error
                raise Exception(f"Could not find collection with url '{url}'.")
        else:
            # TODO: use error from lbry.error
            raise Exception("Missing argument claim_id or url.")

        page_num, page_size = abs(page), min(abs(page_size), 50)
        items = await self.ledger.resolve_collection(txo, page_size * (page_num - 1), page_size)
        total_items = len(txo.claim.collection.claims.ids)

        return {
            "items": items,
            "total_pages": int((total_items + (page_size - 1)) / page_size),
            "total_items": total_items,
            "page_size": page_size,
            "page": page
        }

    SUPPORT_DOC = """
    Create, list and abandon all types of supports.
    """

    @requires(WALLET_COMPONENT)
    async def jsonrpc_support_create(
            self, claim_id, amount, tip=False,
            channel_id=None, channel_name=None, channel_account_id=None,
            account_id=None, wallet_id=None, funding_account_ids=None,
            comment=None, preview=False, blocking=False):
        """
        Create a support or a tip for name claim.

        Usage:
            support_create (<claim_id> | --claim_id=<claim_id>) (<amount> | --amount=<amount>)
                           [--tip] [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                           [--channel_id=<channel_id> | --channel_name=<channel_name>]
                           [--channel_account_id=<channel_account_id>...] [--comment=<comment>]
                           [--preview] [--blocking] [--funding_account_ids=<funding_account_ids>...]

        Options:
            --claim_id=<claim_id>         : (str) claim_id of the claim to support
            --amount=<amount>             : (decimal) amount of support
            --tip                         : (bool) send support to claim owner, default: false.
            --channel_id=<channel_id>     : (str) claim id of the supporters identity channel
            --channel_name=<channel_name> : (str) name of the supporters identity channel
          --channel_account_id=<channel_account_id>: (str) one or more account ids for accounts to look in
                                                   for channel certificates, defaults to all accounts.
            --account_id=<account_id>     : (str) account to use for holding the transaction
            --wallet_id=<wallet_id>       : (str) restrict operation to specific wallet
          --funding_account_ids=<funding_account_ids>: (list) ids of accounts to fund this transaction
            --comment=<comment>           : (str) add a comment to the support
            --preview                     : (bool) do not broadcast the transaction
            --blocking                    : (bool) wait until transaction is in mempool

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        funding_accounts = wallet.get_accounts_or_all(funding_account_ids)
        channel = await self.get_channel_or_none(wallet, channel_account_id, channel_id, channel_name, for_signing=True)
        amount = self.get_dewies_or_error("amount", amount)
        claim = await self.ledger.get_claim_by_claim_id(claim_id)
        claim_address = claim.get_address(self.ledger)
        if not tip:
            account = wallet.get_account_or_default(account_id)
            claim_address = await account.receiving.get_or_create_usable_address()

        tx = await Transaction.support(
            claim.claim_name, claim_id, amount, claim_address, funding_accounts, funding_accounts[0], channel,
            comment=comment
        )
        new_txo = tx.outputs[0]

        if channel:
            new_txo.sign(channel)
        await tx.sign(funding_accounts)

        if not preview:
            await self.broadcast_or_release(tx, blocking)
            await self.storage.save_supports({claim_id: [{
                'txid': tx.id,
                'nout': tx.position,
                'address': claim_address,
                'claim_id': claim_id,
                'amount': dewies_to_lbc(amount)
            }]})
            self.component_manager.loop.create_task(self.analytics_manager.send_claim_action('new_support'))
        else:
            await self.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT)
    def jsonrpc_support_list(self, *args, received=False, sent=False, staked=False, **kwargs):
        """
        List staked supports and sent/received tips.

        Usage:
            support_list [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]
                         [--name=<name>...] [--claim_id=<claim_id>...]
                         [--received | --sent | --staked] [--is_spent]
                         [--page=<page>] [--page_size=<page_size>] [--no_totals]

        Options:
            --name=<name>              : (str or list) claim name
            --claim_id=<claim_id>      : (str or list) claim id
            --received                 : (bool) only show received (tips)
            --sent                     : (bool) only show sent (tips)
            --staked                   : (bool) only show my staked supports
            --is_spent                 : (bool) show abandoned supports
            --account_id=<account_id>  : (str) id of the account to query
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination
            --no_totals                : (bool) do not calculate the total number of pages and items in result set
                                                (significant performance boost)

        Returns: {Paginated[Output]}
        """
        kwargs['type'] = 'support'
        if 'is_spent' not in kwargs:
            kwargs['is_not_spent'] = True
        if received:
            kwargs['is_not_my_input'] = True
            kwargs['is_my_output'] = True
        elif sent:
            kwargs['is_my_input'] = True
            kwargs['is_not_my_output'] = True
            # spent for not my outputs is undetermined
            kwargs.pop('is_spent', None)
            kwargs.pop('is_not_spent', None)
        elif staked:
            kwargs['is_my_input'] = True
            kwargs['is_my_output'] = True
        return self.jsonrpc_txo_list(*args, **kwargs)

    @requires(WALLET_COMPONENT)
    async def jsonrpc_support_abandon(
            self, claim_id=None, txid=None, nout=None, keep=None,
            account_id=None, wallet_id=None, preview=False, blocking=False):
        """
        Abandon supports, including tips, of a specific claim, optionally
        keeping some amount as supports.

        Usage:
            support_abandon [--claim_id=<claim_id>] [(--txid=<txid> --nout=<nout>)] [--keep=<keep>]
                            [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                            [--preview] [--blocking]

        Options:
            --claim_id=<claim_id>     : (str) claim_id of the support to abandon
            --txid=<txid>             : (str) txid of the claim to abandon
            --nout=<nout>             : (int) nout of the claim to abandon
            --keep=<keep>             : (decimal) amount of lbc to keep as support
            --account_id=<account_id> : (str) id of the account to use
            --wallet_id=<wallet_id>   : (str) restrict operation to specific wallet
            --preview                 : (bool) do not broadcast the transaction
            --blocking                : (bool) wait until abandon is in mempool

        Returns: {Transaction}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        if account_id:
            account = wallet.get_account_or_error(account_id)
            accounts = [account]
        else:
            account = wallet.default_account
            accounts = wallet.accounts

        if txid is not None and nout is not None:
            supports = await self.ledger.get_supports(
                wallet=wallet, accounts=accounts, **{'txo.txid': txid, 'txo.position': nout}
            )
        elif claim_id is not None:
            supports = await self.ledger.get_supports(
                wallet=wallet, accounts=accounts, claim_id=claim_id
            )
        else:
            # TODO: use error from lbry.error
            raise Exception('Must specify claim_id, or txid and nout')

        if not supports:
            # TODO: use error from lbry.error
            raise Exception('No supports found for the specified claim_id or txid:nout')

        if keep is not None:
            keep = self.get_dewies_or_error('keep', keep)
        else:
            keep = 0

        outputs = []
        if keep > 0:
            outputs = [
                Output.pay_support_pubkey_hash(
                    keep, supports[0].claim_name, supports[0].claim_id, supports[0].pubkey_hash
                )
            ]

        tx = await Transaction.create(
            [Input.spend(txo) for txo in supports], outputs, accounts, account
        )

        if not preview:
            await self.broadcast_or_release(tx, blocking)
            self.component_manager.loop.create_task(self.analytics_manager.send_claim_action('abandon'))
        else:
            await self.ledger.release_tx(tx)

        return tx

    TRANSACTION_DOC = """
    Transaction management.
    """

    @requires(WALLET_COMPONENT)
    def jsonrpc_transaction_list(self, account_id=None, wallet_id=None, page=None, page_size=None):
        """
        List transactions belonging to wallet

        Usage:
            transaction_list [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]
                             [--page=<page>] [--page_size=<page_size>]

        Options:
            --account_id=<account_id>  : (str) id of the account to query
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination

        Returns:
            (list) List of transactions

            {
                "claim_info": (list) claim info if in txn [{
                                                        "address": (str) address of claim,
                                                        "balance_delta": (float) bid amount,
                                                        "amount": (float) claim amount,
                                                        "claim_id": (str) claim id,
                                                        "claim_name": (str) claim name,
                                                        "nout": (int) nout
                                                        }],
                "abandon_info": (list) abandon info if in txn [{
                                                        "address": (str) address of abandoned claim,
                                                        "balance_delta": (float) returned amount,
                                                        "amount": (float) claim amount,
                                                        "claim_id": (str) claim id,
                                                        "claim_name": (str) claim name,
                                                        "nout": (int) nout
                                                        }],
                "confirmations": (int) number of confirmations for the txn,
                "date": (str) date and time of txn,
                "fee": (float) txn fee,
                "support_info": (list) support info if in txn [{
                                                        "address": (str) address of support,
                                                        "balance_delta": (float) support amount,
                                                        "amount": (float) support amount,
                                                        "claim_id": (str) claim id,
                                                        "claim_name": (str) claim name,
                                                        "is_tip": (bool),
                                                        "nout": (int) nout
                                                        }],
                "timestamp": (int) timestamp,
                "txid": (str) txn id,
                "update_info": (list) update info if in txn [{
                                                        "address": (str) address of claim,
                                                        "balance_delta": (float) credited/debited
                                                        "amount": (float) absolute amount,
                                                        "claim_id": (str) claim id,
                                                        "claim_name": (str) claim name,
                                                        "nout": (int) nout
                                                        }],
                "value": (float) value of txn
            }

        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        if account_id:
            account = wallet.get_account_or_error(account_id)
            transactions = account.get_transaction_history
            transaction_count = account.get_transaction_history_count
        else:
            transactions = partial(
                self.ledger.get_transaction_history, wallet=wallet, accounts=wallet.accounts)
            transaction_count = partial(
                self.ledger.get_transaction_history_count, wallet=wallet, accounts=wallet.accounts)
        return paginate_rows(transactions, transaction_count, page, page_size, read_only=True)

    @requires(WALLET_COMPONENT)
    def jsonrpc_transaction_show(self, txid):
        """
        Get a decoded transaction from a txid

        Usage:
            transaction_show (<txid> | --txid=<txid>)

        Options:
            --txid=<txid>  : (str) txid of the transaction

        Returns: {Transaction}
        """
        return self.wallet_manager.get_transaction(txid)

    TXO_DOC = """
    List and sum transaction outputs.
    """

    @staticmethod
    def _constrain_txo_from_kwargs(
            constraints, type=None, txid=None,  # pylint: disable=redefined-builtin
            claim_id=None, channel_id=None, not_channel_id=None,
            name=None, reposted_claim_id=None,
            is_spent=False, is_not_spent=False,
            has_source=None, has_no_source=None,
            is_my_input_or_output=None, exclude_internal_transfers=False,
            is_my_output=None, is_not_my_output=None,
            is_my_input=None, is_not_my_input=None):
        if is_spent:
            constraints['is_spent'] = True
        elif is_not_spent:
            constraints['is_spent'] = False
        if has_source:
            constraints['has_source'] = True
        elif has_no_source:
            constraints['has_source'] = False
        constraints['exclude_internal_transfers'] = exclude_internal_transfers
        if is_my_input_or_output is True:
            constraints['is_my_input_or_output'] = True
        else:
            if is_my_input is True:
                constraints['is_my_input'] = True
            elif is_not_my_input is True:
                constraints['is_my_input'] = False
            if is_my_output is True:
                constraints['is_my_output'] = True
            elif is_not_my_output is True:
                constraints['is_my_output'] = False
        database.constrain_single_or_list(constraints, 'txo_type', type, lambda x: TXO_TYPES[x])
        database.constrain_single_or_list(constraints, 'channel_id', channel_id)
        database.constrain_single_or_list(constraints, 'channel_id', not_channel_id, negate=True)
        database.constrain_single_or_list(constraints, 'claim_id', claim_id)
        database.constrain_single_or_list(constraints, 'claim_name', name)
        database.constrain_single_or_list(constraints, 'txid', txid)
        database.constrain_single_or_list(constraints, 'reposted_claim_id', reposted_claim_id)
        return constraints

    @requires(WALLET_COMPONENT)
    def jsonrpc_txo_list(
            self, account_id=None, wallet_id=None, page=None, page_size=None,
            resolve=False, order_by=None, no_totals=False, include_received_tips=False, **kwargs):
        """
        List my transaction outputs.

        Usage:
            txo_list [--account_id=<account_id>] [--type=<type>...] [--txid=<txid>...] [--claim_id=<claim_id>...]
                     [--channel_id=<channel_id>...] [--not_channel_id=<not_channel_id>...]
                     [--name=<name>...] [--is_spent | --is_not_spent]
                     [--is_my_input_or_output |
                         [[--is_my_output | --is_not_my_output] [--is_my_input | --is_not_my_input]]
                     ]
                     [--exclude_internal_transfers] [--include_received_tips]
                     [--wallet_id=<wallet_id>] [--page=<page>] [--page_size=<page_size>]
                     [--resolve] [--order_by=<order_by>][--no_totals]

        Options:
            --type=<type>              : (str or list) claim type: stream, channel, support,
                                         purchase, collection, repost, other
            --txid=<txid>              : (str or list) transaction id of outputs
            --claim_id=<claim_id>      : (str or list) claim id
            --channel_id=<channel_id>  : (str or list) claims in this channel
      --not_channel_id=<not_channel_id>: (str or list) claims not in this channel
            --name=<name>              : (str or list) claim name
            --is_spent                 : (bool) only show spent txos
            --is_not_spent             : (bool) only show not spent txos
            --is_my_input_or_output    : (bool) txos which have your inputs or your outputs,
                                                if using this flag the other related flags
                                                are ignored (--is_my_output, --is_my_input, etc)
            --is_my_output             : (bool) show outputs controlled by you
            --is_not_my_output         : (bool) show outputs not controlled by you
            --is_my_input              : (bool) show outputs created by you
            --is_not_my_input          : (bool) show outputs not created by you
           --exclude_internal_transfers: (bool) excludes any outputs that are exactly this combination:
                                                "--is_my_input --is_my_output --type=other"
                                                this allows to exclude "change" payments, this
                                                flag can be used in combination with any of the other flags
            --include_received_tips    : (bool) calculate the amount of tips received for claim outputs
            --account_id=<account_id>  : (str) id of the account to query
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination
            --resolve                  : (bool) resolves each claim to provide additional metadata
            --order_by=<order_by>      : (str) field to order by: 'name', 'height', 'amount' and 'none'
            --no_totals                : (bool) do not calculate the total number of pages and items in result set
                                                (significant performance boost)

        Returns: {Paginated[Output]}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        if account_id:
            account = wallet.get_account_or_error(account_id)
            claims = account.get_txos
            claim_count = account.get_txo_count
        else:
            claims = partial(self.ledger.get_txos, wallet=wallet, accounts=wallet.accounts, read_only=True)
            claim_count = partial(self.ledger.get_txo_count, wallet=wallet, accounts=wallet.accounts, read_only=True)
        constraints = {
            'resolve': resolve,
            'include_is_spent': True,
            'include_is_my_input': True,
            'include_is_my_output': True,
            'include_received_tips': include_received_tips
        }
        if order_by is not None:
            if order_by == 'name':
                constraints['order_by'] = 'txo.claim_name'
            elif order_by in ('height', 'amount', 'none'):
                constraints['order_by'] = order_by
            else:
                # TODO: use error from lbry.error
                raise ValueError(f"'{order_by}' is not a valid --order_by value.")
        self._constrain_txo_from_kwargs(constraints, **kwargs)
        return paginate_rows(claims, None if no_totals else claim_count, page, page_size, **constraints)

    @requires(WALLET_COMPONENT)
    async def jsonrpc_txo_spend(
            self, account_id=None, wallet_id=None, batch_size=100,
            include_full_tx=False, preview=False, blocking=False, **kwargs):
        """
        Spend transaction outputs, batching into multiple transactions as necessary.

        Usage:
            txo_spend [--account_id=<account_id>] [--type=<type>...] [--txid=<txid>...] [--claim_id=<claim_id>...]
                      [--channel_id=<channel_id>...] [--not_channel_id=<not_channel_id>...]
                      [--name=<name>...] [--is_my_input | --is_not_my_input]
                      [--exclude_internal_transfers] [--wallet_id=<wallet_id>]
                      [--preview] [--blocking] [--batch_size=<batch_size>] [--include_full_tx]

        Options:
            --type=<type>              : (str or list) claim type: stream, channel, support,
                                         purchase, collection, repost, other
            --txid=<txid>              : (str or list) transaction id of outputs
            --claim_id=<claim_id>      : (str or list) claim id
            --channel_id=<channel_id>  : (str or list) claims in this channel
      --not_channel_id=<not_channel_id>: (str or list) claims not in this channel
            --name=<name>              : (str or list) claim name
            --is_my_input              : (bool) show outputs created by you
            --is_not_my_input          : (bool) show outputs not created by you
           --exclude_internal_transfers: (bool) excludes any outputs that are exactly this combination:
                                                "--is_my_input --is_my_output --type=other"
                                                this allows to exclude "change" payments, this
                                                flag can be used in combination with any of the other flags
            --account_id=<account_id>  : (str) id of the account to query
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --preview                  : (bool) do not broadcast the transaction
            --blocking                 : (bool) wait until abandon is in mempool
            --batch_size=<batch_size>  : (int) number of txos to spend per transactions
            --include_full_tx          : (bool) include entire tx in output and not just the txid

        Returns: {List[Transaction]}
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        accounts = [wallet.get_account_or_error(account_id)] if account_id else wallet.accounts
        txos = await self.ledger.get_txos(
            wallet=wallet, accounts=accounts, read_only=True,
            no_tx=True, no_channel_info=True,
            **self._constrain_txo_from_kwargs(
                {}, is_not_spent=True, is_my_output=True, **kwargs
            )
        )
        txs = []
        while txos:
            txs.append(
                await Transaction.create(
                    [Input.spend(txos.pop()) for _ in range(min(len(txos), batch_size))],
                    [], accounts, accounts[0]
                )
            )
        if not preview:
            for tx in txs:
                await self.broadcast_or_release(tx, blocking)
        if include_full_tx:
            return txs
        return [{'txid': tx.id} for tx in txs]

    @requires(WALLET_COMPONENT)
    def jsonrpc_txo_sum(self, account_id=None, wallet_id=None, **kwargs):
        """
        Sum of transaction outputs.

        Usage:
            txo_list [--account_id=<account_id>] [--type=<type>...] [--txid=<txid>...]
                     [--channel_id=<channel_id>...] [--not_channel_id=<not_channel_id>...]
                     [--claim_id=<claim_id>...] [--name=<name>...]
                     [--is_spent] [--is_not_spent]
                     [--is_my_input_or_output |
                         [[--is_my_output | --is_not_my_output] [--is_my_input | --is_not_my_input]]
                     ]
                     [--exclude_internal_transfers] [--wallet_id=<wallet_id>]

        Options:
            --type=<type>              : (str or list) claim type: stream, channel, support,
                                         purchase, collection, repost, other
            --txid=<txid>              : (str or list) transaction id of outputs
            --claim_id=<claim_id>      : (str or list) claim id
            --name=<name>              : (str or list) claim name
            --channel_id=<channel_id>  : (str or list) claims in this channel
      --not_channel_id=<not_channel_id>: (str or list) claims not in this channel
            --is_spent                 : (bool) only show spent txos
            --is_not_spent             : (bool) only show not spent txos
            --is_my_input_or_output    : (bool) txos which have your inputs or your outputs,
                                                if using this flag the other related flags
                                                are ignored (--is_my_output, --is_my_input, etc)
            --is_my_output             : (bool) show outputs controlled by you
            --is_not_my_output         : (bool) show outputs not controlled by you
            --is_my_input              : (bool) show outputs created by you
            --is_not_my_input          : (bool) show outputs not created by you
           --exclude_internal_transfers: (bool) excludes any outputs that are exactly this combination:
                                                "--is_my_input --is_my_output --type=other"
                                                this allows to exclude "change" payments, this
                                                flag can be used in combination with any of the other flags
            --account_id=<account_id>  : (str) id of the account to query
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet

        Returns: int
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        return self.ledger.get_txo_sum(
            wallet=wallet, accounts=[wallet.get_account_or_error(account_id)] if account_id else wallet.accounts,
            read_only=True, **self._constrain_txo_from_kwargs({}, **kwargs)
        )

    @requires(WALLET_COMPONENT)
    async def jsonrpc_txo_plot(
            self, account_id=None, wallet_id=None,
            days_back=0, start_day=None, days_after=None, end_day=None, **kwargs):
        """
        Plot transaction output sum over days.

        Usage:
            txo_plot [--account_id=<account_id>] [--type=<type>...] [--txid=<txid>...]
                     [--claim_id=<claim_id>...] [--name=<name>...] [--is_spent] [--is_not_spent]
                     [--channel_id=<channel_id>...] [--not_channel_id=<not_channel_id>...]
                     [--is_my_input_or_output |
                         [[--is_my_output | --is_not_my_output] [--is_my_input | --is_not_my_input]]
                     ]
                     [--exclude_internal_transfers] [--wallet_id=<wallet_id>]
                     [--days_back=<days_back> |
                        [--start_day=<start_day> [--days_after=<days_after> | --end_day=<end_day>]]
                     ]

        Options:
            --type=<type>              : (str or list) claim type: stream, channel, support,
                                         purchase, collection, repost, other
            --txid=<txid>              : (str or list) transaction id of outputs
            --claim_id=<claim_id>      : (str or list) claim id
            --name=<name>              : (str or list) claim name
            --channel_id=<channel_id>  : (str or list) claims in this channel
      --not_channel_id=<not_channel_id>: (str or list) claims not in this channel
            --is_spent                 : (bool) only show spent txos
            --is_not_spent             : (bool) only show not spent txos
            --is_my_input_or_output    : (bool) txos which have your inputs or your outputs,
                                                if using this flag the other related flags
                                                are ignored (--is_my_output, --is_my_input, etc)
            --is_my_output             : (bool) show outputs controlled by you
            --is_not_my_output         : (bool) show outputs not controlled by you
            --is_my_input              : (bool) show outputs created by you
            --is_not_my_input          : (bool) show outputs not created by you
           --exclude_internal_transfers: (bool) excludes any outputs that are exactly this combination:
                                                "--is_my_input --is_my_output --type=other"
                                                this allows to exclude "change" payments, this
                                                flag can be used in combination with any of the other flags
            --account_id=<account_id>  : (str) id of the account to query
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --days_back=<days_back>    : (int) number of days back from today
                                               (not compatible with --start_day, --days_after, --end_day)
            --start_day=<start_day>    : (date) start on specific date (YYYY-MM-DD)
                                               (instead of --days_back)
            --days_after=<days_after>  : (int) end number of days after --start_day
                                               (instead of --end_day)
            --end_day=<end_day>        : (date) end on specific date (YYYY-MM-DD)
                                               (instead of --days_after)

        Returns: List[Dict]
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        plot = await self.ledger.get_txo_plot(
            wallet=wallet, accounts=[wallet.get_account_or_error(account_id)] if account_id else wallet.accounts,
            read_only=True, days_back=days_back, start_day=start_day, days_after=days_after, end_day=end_day,
            **self._constrain_txo_from_kwargs({}, **kwargs)
        )
        for row in plot:
            row['total'] = dewies_to_lbc(row['total'])
        return plot

    UTXO_DOC = """
    Unspent transaction management.
    """

    @requires(WALLET_COMPONENT)
    def jsonrpc_utxo_list(self, *args, **kwargs):
        """
        List unspent transaction outputs

        Usage:
            utxo_list [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]
                      [--page=<page>] [--page_size=<page_size>]

        Options:
            --account_id=<account_id>  : (str) id of the account to query
            --wallet_id=<wallet_id>    : (str) restrict results to specific wallet
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination

        Returns: {Paginated[Output]}
        """
        kwargs['type'] = ['other', 'purchase']
        kwargs['is_not_spent'] = True
        return self.jsonrpc_txo_list(*args, **kwargs)

    @requires(WALLET_COMPONENT)
    async def jsonrpc_utxo_release(self, account_id=None, wallet_id=None):
        """
        When spending a UTXO it is locally locked to prevent double spends;
        occasionally this can result in a UTXO being locked which ultimately
        did not get spent (failed to broadcast, spend transaction was not
        accepted by blockchain node, etc). This command releases the lock
        on all UTXOs in your account.

        Usage:
            utxo_release [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]

        Options:
            --account_id=<account_id> : (str) id of the account to query
            --wallet_id=<wallet_id>   : (str) restrict operation to specific wallet

        Returns:
            None
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        if account_id is not None:
            await wallet.get_account_or_error(account_id).release_all_outputs()
        else:
            for account in wallet.accounts:
                await account.release_all_outputs()

    BLOB_DOC = """
    Blob management.
    """

    @requires(WALLET_COMPONENT, DHT_COMPONENT, BLOB_COMPONENT)
    async def jsonrpc_blob_get(self, blob_hash, timeout=None, read=False):
        """
        Download and return a blob

        Usage:
            blob_get (<blob_hash> | --blob_hash=<blob_hash>) [--timeout=<timeout>] [--read]

        Options:
        --blob_hash=<blob_hash>                        : (str) blob hash of the blob to get
        --timeout=<timeout>                            : (int) timeout in number of seconds

        Returns:
            (str) Success/Fail message or (dict) decoded data
        """

        blob = await download_blob(asyncio.get_event_loop(), self.conf, self.blob_manager, self.dht_node, blob_hash)
        if read:
            with blob.reader_context() as handle:
                return handle.read().decode()
        elif isinstance(blob, BlobBuffer):
            log.warning("manually downloaded blob buffer could have missed garbage collection, clearing it")
            blob.delete()
        return "Downloaded blob %s" % blob_hash

    @requires(BLOB_COMPONENT, DATABASE_COMPONENT)
    async def jsonrpc_blob_delete(self, blob_hash):
        """
        Delete a blob

        Usage:
            blob_delete (<blob_hash> | --blob_hash=<blob_hash>)

        Options:
            --blob_hash=<blob_hash>  : (str) blob hash of the blob to delete

        Returns:
            (str) Success/fail message
        """
        if not blob_hash or not is_valid_blobhash(blob_hash):
            return f"Invalid blob hash to delete '{blob_hash}'"
        streams = self.file_manager.get_filtered(sd_hash=blob_hash)
        if streams:
            await self.file_manager.delete(streams[0])
        else:
            await self.blob_manager.delete_blobs([blob_hash])
        return "Deleted %s" % blob_hash

    PEER_DOC = """
    DHT / Blob Exchange peer commands.
    """

    async def jsonrpc_peer_list(self, blob_hash, page=None, page_size=None):
        """
        Get peers for blob hash

        Usage:
            peer_list (<blob_hash> | --blob_hash=<blob_hash>)
                [--page=<page>] [--page_size=<page_size>]

        Options:
            --blob_hash=<blob_hash>                                  : (str) find available peers for this blob hash
            --page=<page>                                            : (int) page to return during paginating
            --page_size=<page_size>                                  : (int) number of items on page during pagination

        Returns:
            (list) List of contact dictionaries {'address': <peer ip>, 'udp_port': <dht port>, 'tcp_port': <peer port>,
             'node_id': <peer node id>}
        """

        if not is_valid_blobhash(blob_hash):
            # TODO: use error from lbry.error
            raise Exception("invalid blob hash")
        peer_q = asyncio.Queue(loop=self.component_manager.loop)
        if self.component_manager.has_component(TRACKER_ANNOUNCER_COMPONENT):
            tracker = self.component_manager.get_component(TRACKER_ANNOUNCER_COMPONENT)
            tracker_peers = await tracker.get_kademlia_peer_list(bytes.fromhex(blob_hash))
            log.info("Found %d peers for %s from trackers.", len(tracker_peers), blob_hash[:8])
            peer_q.put_nowait(tracker_peers)
        elif not self.component_manager.has_component(DHT_COMPONENT):
            raise Exception("Peer list needs, at least, either a DHT component or a Tracker component for discovery.")
        peers = []
        if self.component_manager.has_component(DHT_COMPONENT):
            await self.dht_node._peers_for_value_producer(blob_hash, peer_q)
        while not peer_q.empty():
            peers.extend(peer_q.get_nowait())
        results = {
            (peer.address, peer.tcp_port): {
                "node_id": hexlify(peer.node_id).decode() if peer.node_id else None,
                "address": peer.address,
                "udp_port": peer.udp_port,
                "tcp_port": peer.tcp_port,
            }
            for peer in peers
        }
        return paginate_list(list(results.values()), page, page_size)

    @requires(DATABASE_COMPONENT)
    async def jsonrpc_blob_announce(self, blob_hash=None, stream_hash=None, sd_hash=None):
        """
        Announce blobs to the DHT

        Usage:
            blob_announce (<blob_hash> | --blob_hash=<blob_hash>
                          | --stream_hash=<stream_hash> | --sd_hash=<sd_hash>)

        Options:
            --blob_hash=<blob_hash>        : (str) announce a blob, specified by blob_hash
            --stream_hash=<stream_hash>    : (str) announce all blobs associated with
                                             stream_hash
            --sd_hash=<sd_hash>            : (str) announce all blobs associated with
                                             sd_hash and the sd_hash itself

        Returns:
            (bool) true if successful
        """
        blob_hashes = []
        if blob_hash:
            blob_hashes.append(blob_hash)
        elif stream_hash or sd_hash:
            if sd_hash and stream_hash:
                # TODO: use error from lbry.error
                raise Exception("either the sd hash or the stream hash should be provided, not both")
            if sd_hash:
                stream_hash = await self.storage.get_stream_hash_for_sd_hash(sd_hash)
            blobs = await self.storage.get_blobs_for_stream(stream_hash, only_completed=True)
            blob_hashes.extend(blob.blob_hash for blob in blobs if blob.blob_hash is not None)
        else:
            # TODO: use error from lbry.error
            raise Exception('single argument must be specified')
        await self.storage.should_single_announce_blobs(blob_hashes, immediate=True)
        return True

    @requires(BLOB_COMPONENT, WALLET_COMPONENT)
    async def jsonrpc_blob_list(self, uri=None, stream_hash=None, sd_hash=None, needed=None,
                                finished=None, page=None, page_size=None):
        """
        Returns blob hashes. If not given filters, returns all blobs known by the blob manager

        Usage:
            blob_list [--needed] [--finished] [<uri> | --uri=<uri>]
                      [<stream_hash> | --stream_hash=<stream_hash>]
                      [<sd_hash> | --sd_hash=<sd_hash>]
                      [--page=<page>] [--page_size=<page_size>]

        Options:
            --needed                     : (bool) only return needed blobs
            --finished                   : (bool) only return finished blobs
            --uri=<uri>                  : (str) filter blobs by stream in a uri
            --stream_hash=<stream_hash>  : (str) filter blobs by stream hash
            --sd_hash=<sd_hash>          : (str) filter blobs in a stream by sd hash, ie the hash of the stream
                                                 descriptor blob for a stream that has been downloaded
            --page=<page>                : (int) page to return during paginating
            --page_size=<page_size>      : (int) number of items on page during pagination

        Returns:
            (list) List of blob hashes
        """

        if uri or stream_hash or sd_hash:
            if uri:
                metadata = (await self.resolve([], uri))[uri]
                sd_hash = utils.get_sd_hash(metadata)
                stream_hash = await self.storage.get_stream_hash_for_sd_hash(sd_hash)
            elif stream_hash:
                sd_hash = await self.storage.get_sd_blob_hash_for_stream(stream_hash)
            elif sd_hash:
                stream_hash = await self.storage.get_stream_hash_for_sd_hash(sd_hash)
                sd_hash = await self.storage.get_sd_blob_hash_for_stream(stream_hash)
            if sd_hash:
                blobs = [sd_hash]
            else:
                blobs = []
            if stream_hash:
                blobs.extend([b.blob_hash for b in (await self.storage.get_blobs_for_stream(stream_hash))[:-1]])
        else:
            blobs = list(self.blob_manager.completed_blob_hashes)
        if needed:
            blobs = [blob_hash for blob_hash in blobs if not self.blob_manager.is_blob_verified(blob_hash)]
        if finished:
            blobs = [blob_hash for blob_hash in blobs if self.blob_manager.is_blob_verified(blob_hash)]
        return paginate_list(blobs, page, page_size)

    @requires(BLOB_COMPONENT)
    async def jsonrpc_blob_reflect(self, blob_hashes, reflector_server=None):
        """
        Reflects specified blobs

        Usage:
            blob_reflect (<blob_hashes>...) [--reflector_server=<reflector_server>]

        Options:
            --reflector_server=<reflector_server>          : (str) reflector address

        Returns:
            (list) reflected blob hashes
        """

        raise NotImplementedError()

    @requires(BLOB_COMPONENT)
    async def jsonrpc_blob_reflect_all(self):
        """
        Reflects all saved blobs

        Usage:
            blob_reflect_all

        Options:
            None

        Returns:
            (bool) true if successful
        """

        raise NotImplementedError()

    @requires(DISK_SPACE_COMPONENT)
    async def jsonrpc_blob_clean(self):
        """
        Deletes blobs to cleanup disk space

        Usage:
            blob_clean

        Options:
            None

        Returns:
            (bool) true if successful
        """
        return await self.disk_space_manager.clean()

    @requires(FILE_MANAGER_COMPONENT)
    async def jsonrpc_file_reflect(self, **kwargs):
        """
        Reflect all the blobs in a file matching the filter criteria

        Usage:
            file_reflect [--sd_hash=<sd_hash>] [--file_name=<file_name>]
                         [--stream_hash=<stream_hash>] [--rowid=<rowid>]
                         [--reflector=<reflector>]

        Options:
            --sd_hash=<sd_hash>          : (str) get file with matching sd hash
            --file_name=<file_name>      : (str) get file with matching file name in the
                                           downloads folder
            --stream_hash=<stream_hash>  : (str) get file with matching stream hash
            --rowid=<rowid>              : (int) get file with matching row id
            --reflector=<reflector>      : (str) reflector server, ip address or url
                                           by default choose a server from the config

        Returns:
            (list) list of blobs reflected
        """

        server, port = kwargs.get('server'), kwargs.get('port')
        if server and port:
            port = int(port)
        else:
            server, port = random.choice(self.conf.reflector_servers)
        reflected = await asyncio.gather(*[
            self.file_manager.source_managers['stream'].reflect_stream(stream, server, port)
            for stream in self.file_manager.get_filtered(**kwargs)
        ])
        total = []
        for reflected_for_stream in reflected:
            total.extend(reflected_for_stream)
        return total

    @requires(DHT_COMPONENT)
    async def jsonrpc_peer_ping(self, node_id, address, port):
        """
        Send a kademlia ping to the specified peer. If address and port are provided the peer is directly pinged,
        if not provided the peer is located first.

        Usage:
            peer_ping (<node_id> | --node_id=<node_id>) (<address> | --address=<address>) (<port> | --port=<port>)

        Options:
            None

        Returns:
            (str) pong, or {'error': <error message>} if an error is encountered
        """
        peer = None
        if node_id and address and port:
            peer = make_kademlia_peer(unhexlify(node_id), address, udp_port=int(port))
            try:
                return await self.dht_node.protocol.get_rpc_peer(peer).ping()
            except asyncio.TimeoutError:
                return {'error': 'timeout'}
        if not peer:
            return {'error': 'peer not found'}

    @requires(DHT_COMPONENT)
    def jsonrpc_routing_table_get(self):
        """
        Get DHT routing information

        Usage:
            routing_table_get

        Options:
            None

        Returns:
            (dict) dictionary containing routing and peer information
            {
                "buckets": {
                    <bucket index>: [
                        {
                            "address": (str) peer address,
                            "udp_port": (int) peer udp port,
                            "tcp_port": (int) peer tcp port,
                            "node_id": (str) peer node id,
                        }
                    ]
                },
                "node_id": (str) the local dht node id
                "prefix_neighbors_count": (int) the amount of peers sharing the same byte prefix of the local node id
            }
        """
        result = {
            'buckets': {},
            'prefix_neighbors_count': 0
        }

        for i, _ in enumerate(self.dht_node.protocol.routing_table.buckets):
            result['buckets'][i] = []
            for peer in self.dht_node.protocol.routing_table.buckets[i].peers:
                host = {
                    "address": peer.address,
                    "udp_port": peer.udp_port,
                    "tcp_port": peer.tcp_port,
                    "node_id": hexlify(peer.node_id).decode(),
                }
                result['buckets'][i].append(host)
                result['prefix_neighbors_count'] += 1 if peer.node_id[0] == self.dht_node.protocol.node_id[0] else 0

        result['node_id'] = hexlify(self.dht_node.protocol.node_id).decode()
        return result

    TRACEMALLOC_DOC = """
    Controls and queries tracemalloc memory tracing tools for troubleshooting.
    """

    def jsonrpc_tracemalloc_enable(self):  # pylint: disable=no-self-use
        """
        Enable tracemalloc memory tracing

        Usage:
            jsonrpc_tracemalloc_enable

        Options:
            None

        Returns:
            (bool) is it tracing?
        """
        tracemalloc.start()
        return tracemalloc.is_tracing()

    def jsonrpc_tracemalloc_disable(self):  # pylint: disable=no-self-use
        """
        Disable tracemalloc memory tracing

        Usage:
            jsonrpc_tracemalloc_disable

        Options:
            None

        Returns:
            (bool) is it tracing?
        """
        tracemalloc.stop()
        return tracemalloc.is_tracing()

    def jsonrpc_tracemalloc_top(self, items: int = 10):  # pylint: disable=no-self-use
        """
        Show most common objects, the place that created them and their size.

        Usage:
            jsonrpc_tracemalloc_top [(<items> | --items=<items>)]

        Options:
            --items=<items>               : (int) maximum items to return, from the most common

        Returns:
            (dict) dictionary containing most common objects in memory
            {
                "line": (str) filename and line number where it was created,
                "code": (str) code that created it,
                "size": (int) size in bytes, for each "memory block",
                "count" (int) number of memory blocks
            }
        """
        if not tracemalloc.is_tracing():
            # TODO: use error from lbry.error
            raise Exception("Enable tracemalloc first! See 'tracemalloc set' command.")
        stats = tracemalloc.take_snapshot().filter_traces((
            tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
            tracemalloc.Filter(False, "<unknown>"),
            # tracemalloc and linecache here use some memory, but thats not relevant
            tracemalloc.Filter(False, tracemalloc.__file__),
            tracemalloc.Filter(False, linecache.__file__),
        )).statistics('lineno', True)
        results = []
        for stat in stats:
            frame = stat.traceback[0]
            filename = os.sep.join(frame.filename.split(os.sep)[-2:])
            line = linecache.getline(frame.filename, frame.lineno).strip()
            results.append({
                "line": f"{filename}:{frame.lineno}",
                "code": line,
                "size": stat.size,
                "count": stat.count
            })
            if len(results) == items:
                break
        return results

    async def broadcast_or_release(self, tx, blocking=False):
        await self.wallet_manager.broadcast_or_release(tx, blocking)

    def valid_address_or_error(self, address, allow_script_address=False):
        try:
            assert self.ledger.is_pubkey_address(address) or (
                allow_script_address and self.ledger.is_script_address(address)
            )
        except:
            # TODO: use error from lbry.error
            raise Exception(f"'{address}' is not a valid address")

    @staticmethod
    def valid_stream_name_or_error(name: str):
        try:
            if not name:
                raise InputStringIsBlankError('Stream name')
            parsed = URL.parse(name)
            if parsed.has_channel:
                # TODO: use error from lbry.error
                raise Exception(
                    "Stream names cannot start with '@' symbol. This is reserved for channels claims."
                )
            if not parsed.has_stream or parsed.stream.name != name:
                # TODO: use error from lbry.error
                raise Exception('Stream name has invalid characters.')
        except (TypeError, ValueError):
            # TODO: use error from lbry.error
            raise Exception("Invalid stream name.")

    @staticmethod
    def valid_collection_name_or_error(name: str):
        try:
            if not name:
                # TODO: use error from lbry.error
                raise Exception('Collection name cannot be blank.')
            parsed = URL.parse(name)
            if parsed.has_channel:
                # TODO: use error from lbry.error
                raise Exception(
                    "Collection names cannot start with '@' symbol. This is reserved for channels claims."
                )
            if not parsed.has_stream or parsed.stream.name != name:
                # TODO: use error from lbry.error
                raise Exception('Collection name has invalid characters.')
        except (TypeError, ValueError):
            # TODO: use error from lbry.error
            raise Exception("Invalid collection name.")

    @staticmethod
    def valid_channel_name_or_error(name: str):
        try:
            if not name:
                # TODO: use error from lbry.error
                raise Exception(
                    "Channel name cannot be blank."
                )
            parsed = URL.parse(name)
            if not parsed.has_channel:
                # TODO: use error from lbry.error
                raise Exception("Channel names must start with '@' symbol.")
            if parsed.channel.name != name:
                # TODO: use error from lbry.error
                raise Exception("Channel name has invalid character")
        except (TypeError, ValueError):
            # TODO: use error from lbry.error
            raise Exception("Invalid channel name.")

    def get_fee_address(self, kwargs: dict, claim_address: str) -> str:
        if 'fee_address' in kwargs:
            self.valid_address_or_error(kwargs['fee_address'])
            return kwargs['fee_address']
        if 'fee_currency' in kwargs or 'fee_amount' in kwargs:
            return claim_address

    async def get_receiving_address(self, address: str, account: Optional[Account]) -> str:
        if address is None and account is not None:
            return await account.receiving.get_or_create_usable_address()
        self.valid_address_or_error(address)
        return address

    async def get_channel_or_none(
            self, wallet: Wallet, account_ids: List[str], channel_id: str = None,
            channel_name: str = None, for_signing: bool = False) -> Output:
        if channel_id is not None or channel_name is not None:
            return await self.get_channel_or_error(
                wallet, account_ids, channel_id, channel_name, for_signing
            )

    async def get_channel_or_error(
            self, wallet: Wallet, account_ids: List[str], channel_id: str = None,
            channel_name: str = None, for_signing: bool = False) -> Output:
        if channel_id:
            key, value = 'id', channel_id
        elif channel_name:
            key, value = 'name', channel_name
        else:
            # TODO: use error from lbry.error
            raise ValueError("Couldn't find channel because a channel_id or channel_name was not provided.")
        channels = await self.ledger.get_channels(
            wallet=wallet, accounts=wallet.get_accounts_or_all(account_ids),
            **{f'claim_{key}': value}
        )
        if len(channels) == 1:
            if for_signing and not channels[0].has_private_key:
                # TODO: use error from lbry.error
                raise PrivateKeyNotFoundError(key, value)
            return channels[0]
        elif len(channels) > 1:
            # TODO: use error from lbry.error
            raise ValueError(
                f"Multiple channels found with channel_{key} '{value}', "
                f"pass a channel_id to narrow it down."
            )
        # TODO: use error from lbry.error
        raise ValueError(f"Couldn't find channel with channel_{key} '{value}'.")

    @staticmethod
    def get_dewies_or_error(argument: str, lbc: str, positive_value=False):
        try:
            dewies = lbc_to_dewies(lbc)
            if positive_value and dewies <= 0:
                # TODO: use error from lbry.error
                raise ValueError(f"'{argument}' value must be greater than 0.0")
            return dewies
        except ValueError as e:
            # TODO: use error from lbry.error
            raise ValueError(f"Invalid value for '{argument}': {e.args[0]}")

    async def resolve(self, accounts, urls, **kwargs):
        results = await self.ledger.resolve(accounts, urls, **kwargs)
        if self.conf.save_resolved_claims and results:
            try:
                await self.storage.save_claim_from_output(
                    self.ledger,
                    *(result for result in results.values() if isinstance(result, Output))
                )
            except DecodeError:
                pass
        return results

    @staticmethod
    def _old_get_temp_claim_info(tx, txo, address, claim_dict, name, bid):
        return {
            "claim_id": txo.claim_id,
            "name": name,
            "amount": bid,
            "address": address,
            "txid": tx.id,
            "nout": txo.position,
            "value": claim_dict,
            "height": -1,
            "claim_sequence": -1,
        }


def loggly_time_string(date):
    formatted_dt = date.strftime("%Y-%m-%dT%H:%M:%S")
    milliseconds = str(round(date.microsecond * (10.0 ** -5), 3))
    return quote(formatted_dt + milliseconds + "Z")


def get_loggly_query_string(installation_id):
    base_loggly_search_url = "https://lbry.loggly.com/search#"
    now = utils.now()
    yesterday = now - utils.timedelta(days=1)
    params = {
        'terms': f'json.installation_id:{installation_id[:SHORT_ID_LEN]}*',
        'from': loggly_time_string(yesterday),
        'to': loggly_time_string(now)
    }
    data = urlencode(params)
    return base_loggly_search_url + data
