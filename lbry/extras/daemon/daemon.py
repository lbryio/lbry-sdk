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
import hashlib
import tracemalloc
from urllib.parse import urlencode, quote
from typing import Callable, Optional, List
from binascii import hexlify, unhexlify
from traceback import format_exc
from functools import wraps, partial

import ecdsa
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

from lbry import utils
from lbry.conf import Config, Setting, NOT_SET
from lbry.blob.blob_file import is_valid_blobhash, BlobBuffer
from lbry.blob_exchange.downloader import download_blob
from lbry.dht.peer import make_kademlia_peer
from lbry.error import (
    DownloadSDTimeoutError, ComponentsNotStartedError, ComponentStartConditionNotMetError,
    CommandDoesNotExistError
)
from lbry.extras import system_info
from lbry.extras.daemon import analytics
from lbry.extras.daemon.components import WALLET_COMPONENT, DATABASE_COMPONENT, DHT_COMPONENT, BLOB_COMPONENT
from lbry.extras.daemon.components import FILE_MANAGER_COMPONENT
from lbry.extras.daemon.components import EXCHANGE_RATE_MANAGER_COMPONENT, UPNP_COMPONENT
from lbry.extras.daemon.componentmanager import RequiredCondition
from lbry.extras.daemon.componentmanager import ComponentManager
from lbry.extras.daemon.json_response_encoder import JSONResponseEncoder
from lbry.extras.daemon import comment_client
from lbry.extras.daemon.undecorated import undecorated
from lbry.extras.daemon.security import ensure_request_allowed
from lbry.file_analysis import VideoFileAnalyzer
from lbry.schema.claim import Claim
from lbry.schema.url import URL

if typing.TYPE_CHECKING:
    from lbry.blob.blob_manager import BlobManager
    from lbry.dht.node import Node
    from lbry.extras.daemon.components import UPnPComponent
    from lbry.extras.daemon.exchange_rate_manager import ExchangeRateManager
    from lbry.extras.daemon.storage import SQLiteStorage
    from lbry.wallet import WalletManager, Ledger
    from lbry.file.file_manager import FileManager

log = logging.getLogger(__name__)


def is_transactional_function(name):
    for action in ('create', 'update', 'abandon', 'send', 'fund'):
        if action in name:
            return True

from lbry.extras.daemon.daemon_meta import requires


from lbry.extras.daemon.daemon_meta import deprecated


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
from lbry.extras.daemon.daemon_meta import DEFAULT_PAGE_SIZE

from lbry.extras.daemon.daemon_meta import VALID_FULL_CLAIM_ID


def encode_pagination_doc(items):
    return {
        "page": "Page number of the current items.",
        "page_size": "Number of items to show on a page.",
        "total_pages": "Total number of pages.",
        "total_items": "Total number of items.",
        "items": [items],
    }


from lbry.extras.daemon.daemon_meta import paginate_rows


from lbry.extras.daemon.daemon_meta import paginate_list


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


from lbry.extras.daemon.daemon_meta import JSONRPCServerType
from lbry.extras.daemon.daemon_basic import Daemon_base
from lbry.extras.daemon.daemon_get import Daemon_get
from lbry.extras.daemon.daemon_settings import Daemon_settings
from lbry.extras.daemon.daemon_wallet import Daemon_wallet
from lbry.extras.daemon.daemon_account import Daemon_account
from lbry.extras.daemon.daemon_sync import Daemon_sync
from lbry.extras.daemon.daemon_address import Daemon_address
from lbry.extras.daemon.daemon_file import Daemon_file
from lbry.extras.daemon.daemon_purchase import Daemon_purchase
from lbry.extras.daemon.daemon_claim import Daemon_claim
from lbry.extras.daemon.daemon_channel import Daemon_channel
from lbry.extras.daemon.daemon_stream import Daemon_stream
from lbry.extras.daemon.daemon_collection import Daemon_collection
from lbry.extras.daemon.daemon_support import Daemon_support
from lbry.extras.daemon.daemon_transaction import Daemon_transaction
from lbry.extras.daemon.daemon_txo import Daemon_txo
from lbry.extras.daemon.daemon_utxo import Daemon_utxo
from lbry.extras.daemon.daemon_blob import Daemon_blob
from lbry.extras.daemon.daemon_peer import Daemon_peer
from lbry.extras.daemon.daemon_tracemalloc import Daemon_tracemalloc
from lbry.extras.daemon.daemon_comment import Daemon_comment

HISTOGRAM_BUCKETS = (
    .005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0, 15.0, 20.0, 30.0, 60.0, float('inf')
)


class Daemon(Daemon_base, Daemon_get, Daemon_settings, Daemon_wallet,
             Daemon_account, Daemon_sync, Daemon_address, Daemon_file,
             Daemon_purchase, Daemon_claim, Daemon_channel,
             Daemon_stream, Daemon_collection, Daemon_support,
             Daemon_transaction, Daemon_txo, Daemon_utxo, Daemon_blob,
             Daemon_peer, Daemon_tracemalloc, Daemon_comment):
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
            log.exception("error handling api request")
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

    # jsonrpc_stop
    # jsonrpc_ffmpeg_find
    # jsonrpc_status
    # jsonrpc_version
    # jsonrpc_resolve
    # jsonrpc_routing_table_get

    # jsonrpc_get

    SETTINGS_DOC = """
    Settings management.
    """
    # jsonrpc_settings_get
    # jsonrpc_settings_set
    # jsonrpc_settings_clear

    PREFERENCE_DOC = """
    Preferences management.
    """
    # jsonrpc_preference_get
    # jsonrpc_preference_set

    WALLET_DOC = """
    Create, modify and inspect wallets.
    """
    # jsonrpc_wallet_list
    # jsonrpc_wallet_reconnect
    # jsonrpc_wallet_create
    # jsonrpc_wallet_add
    # jsonrpc_wallet_remove
    # jsonrpc_wallet_balance
    # jsonrpc_wallet_status
    # jsonrpc_wallet_unlock
    # jsonrpc_wallet_lock
    # jsonrpc_wallet_decrypt
    # jsonrpc_wallet_encrypt
    # jsonrpc_wallet_send

    ACCOUNT_DOC = """
    Create, modify and inspect wallet accounts.
    """
    # jsonrpc_account_list
    # jsonrpc_account_balance
    # jsonrpc_account_add
    # jsonrpc_account_create
    # jsonrpc_account_remove
    # jsonrpc_account_set
    # jsonrpc_account_max_address_gap
    # jsonrpc_account_fund
    # jsonrpc_account_send

    SYNC_DOC = """
    Wallet synchronization.
    """
    # jsonrpc_sync_hash
    # jsonrpc_sync_apply

    ADDRESS_DOC = """
    List, generate and verify addresses.
    """
    # jsonrpc_address_is_mine
    # jsonrpc_address_list
    # jsonrpc_address_unused

    FILE_DOC = """
    File management.
    """
    # jsonrpc_file_list
    # jsonrpc_file_set_status
    # jsonrpc_file_delete
    # jsonrpc_file_save
    # jsonrpc_file_reflect

    PURCHASE_DOC = """
    List and make purchases of claims.
    """
    # jsonrpc_purchase_list
    # jsonrpc_purchase_create

    CLAIM_DOC = """
    List and search all types of claims.
    """
    # jsonrpc_claim_list
    # jsonrpc_claim_search

    CHANNEL_DOC = """
    Create, update, abandon and list your channel claims.
    """
    # jsonrpc_channel_new
    # jsonrpc_channel_create
    # jsonrpc_channel_update
    # jsonrpc_channel_sign
    # jsonrpc_channel_abandon
    # jsonrpc_channel_list
    # jsonrpc_channel_export
    # jsonrpc_channel_import

    STREAM_DOC = """
    Create, update, abandon, list and inspect your stream claims.
    """
    # jsonrpc_publish
    # jsonrpc_stream_repost
    # jsonrpc_stream_create
    # jsonrpc_stream_update
    # jsonrpc_stream_abandon
    # jsonrpc_stream_list
    # jsonrpc_stream_cost_estimate

    COLLECTION_DOC = """
    Create, update, list, resolve, and abandon collections.
    """
    # jsonrpc_collection_create
    # jsonrpc_collection_update
    # jsonrpc_collection_abandon
    # jsonrpc_collection_list
    # jsonrpc_collection_resolve

    SUPPORT_DOC = """
    Create, list and abandon all types of supports.
    """
    # jsonrpc_support_create
    # jsonrpc_support_list
    # jsonrpc_support_abandon
    # jsonrpc_support_sum

    TRANSACTION_DOC = """
    Transaction management.
    """
    # jsonrpc_transaction_list
    # jsonrpc_transaction_show

    TXO_DOC = """
    List and sum transaction outputs.
    """
    # _constrain_txo_from_kwargs
    # jsonrpc_txo_list
    # jsonrpc_txo_spend
    # jsonrpc_txo_sum
    # jsonrpc_txo_plot

    UTXO_DOC = """
    Unspent transaction management.
    """
    # jsonrpc_utxo_list
    # jsonrpc_utxo_release

    BLOB_DOC = """
    Blob management.
    """
    # jsonrpc_blob_announce
    # jsonrpc_blob_delete
    # jsonrpc_blob_get
    # jsonrpc_blob_list
    # jsonrpc_blob_reflect
    # jsonrpc_blob_reflect_all

    PEER_DOC = """
    DHT / Blob Exchange peer commands.
    """
    # jsonrpc_peer_list
    # jsonrpc_peer_ping

    TRACEMALLOC_DOC = """
    Controls and queries tracemalloc memory tracing tools for troubleshooting.
    """
    # jsonrpc_tracemalloc_enable
    # jsonrpc_tracemalloc_disable
    # jsonrpc_tracemalloc_top

    COMMENT_DOC = """
    View, create and abandon comments.
    """
    # jsonrpc_comment_list
    # jsonrpc_comment_create
    # jsonrpc_comment_update
    # jsonrpc_comment_abandon
    # jsonrpc_comment_hide
    # jsonrpc_comment_pin
    # jsonrpc_comment_react
    # jsonrpc_comment_react_list

    async def broadcast_or_release(self, tx, blocking=False):
        await self.wallet_manager.broadcast_or_release(tx, blocking)

    def valid_address_or_error(self, address, allow_script_address=False):
        try:
            assert self.ledger.is_pubkey_address(address) or (
                allow_script_address and self.ledger.is_script_address(address)
            )
        except:
            raise Exception(f"'{address}' is not a valid address")

    @staticmethod
    def valid_stream_name_or_error(name: str):
        try:
            if not name:
                raise Exception('Stream name cannot be blank.')
            parsed = URL.parse(name)
            if parsed.has_channel:
                raise Exception(
                    "Stream names cannot start with '@' symbol. This is reserved for channels claims."
                )
            if not parsed.has_stream or parsed.stream.name != name:
                raise Exception('Stream name has invalid characters.')
        except (TypeError, ValueError):
            raise Exception("Invalid stream name.")

    @staticmethod
    def valid_collection_name_or_error(name: str):
        try:
            if not name:
                raise Exception('Collection name cannot be blank.')
            parsed = URL.parse(name)
            if parsed.has_channel:
                raise Exception(
                    "Collection names cannot start with '@' symbol. This is reserved for channels claims."
                )
            if not parsed.has_stream or parsed.stream.name != name:
                raise Exception('Collection name has invalid characters.')
        except (TypeError, ValueError):
            raise Exception("Invalid collection name.")

    @staticmethod
    def valid_channel_name_or_error(name: str):
        try:
            if not name:
                raise Exception(
                    "Channel name cannot be blank."
                )
            parsed = URL.parse(name)
            if not parsed.has_channel:
                raise Exception("Channel names must start with '@' symbol.")
            if parsed.channel.name != name:
                raise Exception("Channel name has invalid character")
        except (TypeError, ValueError):
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
            raise ValueError("Couldn't find channel because a channel_id or channel_name was not provided.")
        channels = await self.ledger.get_channels(
            wallet=wallet, accounts=wallet.get_accounts_or_all(account_ids),
            **{f'claim_{key}': value}
        )
        if len(channels) == 1:
            if for_signing and not channels[0].has_private_key:
                raise Exception(f"Couldn't find private key for {key} '{value}'. ")
            return channels[0]
        elif len(channels) > 1:
            raise ValueError(
                f"Multiple channels found with channel_{key} '{value}', "
                f"pass a channel_id to narrow it down."
            )
        raise ValueError(f"Couldn't find channel with channel_{key} '{value}'.")

    @staticmethod
    def get_dewies_or_error(argument: str, lbc: str, positive_value=False):
        try:
            dewies = lbc_to_dewies(lbc)
            if positive_value and dewies <= 0:
                raise ValueError(f"'{argument}' value must be greater than 0.0")
            return dewies
        except ValueError as e:
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
