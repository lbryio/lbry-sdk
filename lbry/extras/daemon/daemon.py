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

HISTOGRAM_BUCKETS = (
    .005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0, 15.0, 20.0, 30.0, 60.0, float('inf')
)


class Daemon(Daemon_base, Daemon_get, Daemon_settings, Daemon_wallet,
             Daemon_account, Daemon_sync, Daemon_address, Daemon_file,
             Daemon_purchase, Daemon_claim, Daemon_channel,
             Daemon_stream, Daemon_collection, Daemon_support,
             Daemon_transaction):
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

    @requires(DHT_COMPONENT)
    async def jsonrpc_peer_list(self, blob_hash, search_bottom_out_limit=None, page=None, page_size=None):
        """
        Get peers for blob hash

        Usage:
            peer_list (<blob_hash> | --blob_hash=<blob_hash>)
                [<search_bottom_out_limit> | --search_bottom_out_limit=<search_bottom_out_limit>]
                [--page=<page>] [--page_size=<page_size>]

        Options:
            --blob_hash=<blob_hash>                                  : (str) find available peers for this blob hash
            --search_bottom_out_limit=<search_bottom_out_limit>      : (int) the number of search probes in a row
                                                                             that don't find any new peers
                                                                             before giving up and returning
            --page=<page>                                            : (int) page to return during paginating
            --page_size=<page_size>                                  : (int) number of items on page during pagination

        Returns:
            (list) List of contact dictionaries {'address': <peer ip>, 'udp_port': <dht port>, 'tcp_port': <peer port>,
             'node_id': <peer node id>}
        """

        if not is_valid_blobhash(blob_hash):
            raise Exception("invalid blob hash")
        if search_bottom_out_limit is not None:
            search_bottom_out_limit = int(search_bottom_out_limit)
            if search_bottom_out_limit <= 0:
                raise Exception("invalid bottom out limit")
        else:
            search_bottom_out_limit = 4
        peers = []
        peer_q = asyncio.Queue(loop=self.component_manager.loop)
        await self.dht_node._peers_for_value_producer(blob_hash, peer_q)
        while not peer_q.empty():
            peers.extend(peer_q.get_nowait())
        results = [
            {
                "node_id": hexlify(peer.node_id).decode(),
                "address": peer.address,
                "udp_port": peer.udp_port,
                "tcp_port": peer.tcp_port,
            }
            for peer in peers
        ]
        return paginate_list(results, page, page_size)

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
                raise Exception("either the sd hash or the stream hash should be provided, not both")
            if sd_hash:
                stream_hash = await self.storage.get_stream_hash_for_sd_hash(sd_hash)
            blobs = await self.storage.get_blobs_for_stream(stream_hash, only_completed=True)
            blob_hashes.extend(blob.blob_hash for blob in blobs if blob.blob_hash is not None)
        else:
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
            --sd_hash=<sd_hash>          : (str) filter blobs by sd hash
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

    COMMENT_DOC = """
    View, create and abandon comments.
    """

    async def jsonrpc_comment_list(self, claim_id, parent_id=None, page=1, page_size=50,
                                   include_replies=False, skip_validation=False,
                                   is_channel_signature_valid=False, hidden=False, visible=False):
        """
        List comments associated with a claim.

        Usage:
            comment_list    (<claim_id> | --claim_id=<claim_id>)
                            [(--page=<page> --page_size=<page_size>)]
                            [--parent_id=<parent_id>] [--include_replies]
                            [--skip_validation] [--is_channel_signature_valid]
                            [--visible | --hidden]

        Options:
            --claim_id=<claim_id>           : (str) The claim on which the comment will be made on
            --parent_id=<parent_id>         : (str) CommentId of a specific thread you'd like to see
            --page=<page>                   : (int) The page you'd like to see in the comment list.
            --page_size=<page_size>         : (int) The amount of comments that you'd like to retrieve
            --skip_validation               : (bool) Skip resolving comments to validate channel names
            --include_replies               : (bool) Whether or not you want to include replies in list
            --is_channel_signature_valid    : (bool) Only include comments with valid signatures.
                                              [Warning: Paginated total size will not change, even
                                               if list reduces]
            --visible                       : (bool) Select only Visible Comments
            --hidden                        : (bool) Select only Hidden Comments

        Returns:
            (dict)  Containing the list, and information about the paginated content:
            {
                "page": "Page number of the current items.",
                "page_size": "Number of items to show on a page.",
                "total_pages": "Total number of pages.",
                "total_items": "Total number of items.",
                "items": "A List of dict objects representing comments."
                [
                    {
                        "comment":      (str) The actual string as inputted by the user,
                        "comment_id":   (str) The Comment's unique identifier,
                        "channel_name": (str) Name of the channel this was posted under, prepended with a '@',
                        "channel_id":   (str) The Channel Claim ID that this comment was posted under,
                        "signature":    (str) The signature of the comment,
                        "channel_url":  (str) Channel's URI in the ClaimTrie,
                        "parent_id":    (str) Comment this is replying to, (None) if this is the root,
                        "timestamp":    (int) The time at which comment was entered into the server at, in nanoseconds.
                    },
                    ...
                ]
            }
        """
        if hidden ^ visible:
            result = await comment_client.jsonrpc_post(
                self.conf.comment_server,
                'comment.List',
                claim_id=claim_id,
                visible=visible,
                hidden=hidden,
                page=page,
                page_size=page_size
            )
        else:
            result = await comment_client.jsonrpc_post(
                self.conf.comment_server,
                'comment.List',
                claim_id=claim_id,
                parent_id=parent_id,
                page=page,
                page_size=page_size,
                top_level=not include_replies
            )
        if not skip_validation:
            for comment in result.get('items', []):
                channel_url = comment.get('channel_url')
                if not channel_url:
                    continue
                resolve_response = await self.resolve([], [channel_url])
                if isinstance(resolve_response[channel_url], Output):
                    comment['is_channel_signature_valid'] = comment_client.is_comment_signed_by_channel(
                        comment, resolve_response[channel_url]
                    )
                else:
                    comment['is_channel_signature_valid'] = False
            if is_channel_signature_valid:
                result['items'] = [
                    c for c in result.get('items', []) if c.get('is_channel_signature_valid', False)
                ]
        return result

    @requires(WALLET_COMPONENT)
    async def jsonrpc_comment_create(self, comment, claim_id=None, parent_id=None, channel_account_id=None,
                                     channel_name=None, channel_id=None, wallet_id=None):
        """
        Create and associate a comment with a claim using your channel identity.

        Usage:
            comment_create  (<comment> | --comment=<comment>)
                            (<claim_id> | --claim_id=<claim_id>) [--parent_id=<parent_id>]
                            (--channel_id=<channel_id> | --channel_name=<channel_name>)
                            [--channel_account_id=<channel_account_id>...] [--wallet_id=<wallet_id>]

        Options:
            --comment=<comment>                         : (str) Comment to be made, should be at most 2000 characters.
            --claim_id=<claim_id>                       : (str) The ID of the claim to comment on
            --parent_id=<parent_id>                     : (str) The ID of a comment to make a response to
            --channel_id=<channel_id>                   : (str) The ID of the channel you want to post under
            --channel_name=<channel_name>               : (str) The channel you want to post as, prepend with a '@'
            --channel_account_id=<channel_account_id>   : (str) one or more account ids for accounts to look in
                                                          for channel certificates, defaults to all accounts
            --wallet_id=<wallet_id>                     : (str) restrict operation to specific wallet

        Returns:
            (dict) Comment object if successfully made, (None) otherwise
            {
                "comment":      (str) The actual string as inputted by the user,
                "comment_id":   (str) The Comment's unique identifier,
                "claim_id":     (str) The claim commented on,
                "channel_name": (str) Name of the channel this was posted under, prepended with a '@',
                "channel_id":   (str) The Channel Claim ID that this comment was posted under,
                "is_pinned":    (boolean) Channel owner has pinned this comment,
                "signature":    (str) The signature of the comment,
                "signing_ts":   (str) The timestamp used to sign the comment,
                "channel_url":  (str) Channel's URI in the ClaimTrie,
                "parent_id":    (str) Comment this is replying to, (None) if this is the root,
                "timestamp":    (int) The time at which comment was entered into the server at, in nanoseconds.
            }
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        channel = await self.get_channel_or_error(
            wallet, channel_account_id, channel_id, channel_name, for_signing=True
        )

        comment_body = {
            'comment': comment.strip(),
            'claim_id': claim_id,
            'parent_id': parent_id,
            'channel_id': channel.claim_id,
            'channel_name': channel.claim_name,
        }
        comment_client.sign_comment(comment_body, channel)

        response = await comment_client.jsonrpc_post(self.conf.comment_server, 'comment.Create', comment_body)
        response.update({
            'is_claim_signature_valid': comment_client.is_comment_signed_by_channel(response, channel)
        })
        return response

    @requires(WALLET_COMPONENT)
    async def jsonrpc_comment_update(self, comment, comment_id, wallet_id=None):
        """
        Edit a comment published as one of your channels.

        Usage:
            comment_update (<comment> | --comment=<comment>)
                         (<comment_id> | --comment_id=<comment_id>)
                         [--wallet_id=<wallet_id>]

        Options:
            --comment=<comment>         : (str) New comment replacing the old one
            --comment_id=<comment_id>   : (str) Hash identifying the comment to edit
            --wallet_id=<wallet_id      : (str) restrict operation to specific wallet

        Returns:
            (dict) Comment object if edit was successful, (None) otherwise
            {
                "comment":      (str) The actual string as inputted by the user,
                "comment_id":   (str) The Comment's unique identifier,
                "claim_id":     (str) The claim commented on,
                "channel_name": (str) Name of the channel this was posted under, prepended with a '@',
                "channel_id":   (str) The Channel Claim ID that this comment was posted under,
                "signature":    (str) The signature of the comment,
                "signing_ts":   (str) Timestamp used to sign the most recent signature,
                "channel_url":  (str) Channel's URI in the ClaimTrie,
                "is_pinned":    (boolean) Channel owner has pinned this comment,
                "parent_id":    (str) Comment this is replying to, (None) if this is the root,
                "timestamp":    (int) The time at which comment was entered into the server at, in nanoseconds.
            }
        """
        channel = await comment_client.jsonrpc_post(
            self.conf.comment_server,
            'comment.GetChannelFromCommentID',
            comment_id=comment_id
        )
        if 'error' in channel:
            raise ValueError(channel['error'])

        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        # channel = await self.get_channel_or_none(wallet, None, **channel)
        channel_claim = await self.get_channel_or_error(wallet, [], **channel)
        edited_comment = {
            'comment_id': comment_id,
            'comment': comment,
            'channel_id': channel_claim.claim_id,
            'channel_name': channel_claim.claim_name
        }
        comment_client.sign_comment(edited_comment, channel_claim)
        return await comment_client.jsonrpc_post(
            self.conf.comment_server, 'comment.Edit', edited_comment
        )

    @requires(WALLET_COMPONENT)
    async def jsonrpc_comment_abandon(self, comment_id, wallet_id=None):
        """
        Abandon a comment published under your channel identity.

        Usage:
            comment_abandon  (<comment_id> | --comment_id=<comment_id>) [--wallet_id=<wallet_id>]

        Options:
            --comment_id=<comment_id>   : (str) The ID of the comment to be abandoned.
            --wallet_id=<wallet_id      : (str) restrict operation to specific wallet

        Returns:
            (dict) Object with the `comment_id` passed in as the key, and a flag indicating if it was abandoned
            {
                <comment_id> (str): {
                    "abandoned": (bool)
                }
            }
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        abandon_comment_body = {'comment_id': comment_id}
        channel = await comment_client.jsonrpc_post(
            self.conf.comment_server, 'comment.GetChannelFromCommentID', comment_id=comment_id
        )
        if 'error' in channel:
            return {comment_id: {'abandoned': False}}
        channel = await self.get_channel_or_none(wallet, None, **channel)
        abandon_comment_body.update({
            'channel_id': channel.claim_id,
            'channel_name': channel.claim_name,
        })
        comment_client.sign_comment(abandon_comment_body, channel, sign_comment_id=True)
        return await comment_client.jsonrpc_post(self.conf.comment_server, 'comment.Abandon', abandon_comment_body)

    @requires(WALLET_COMPONENT)
    async def jsonrpc_comment_hide(self, comment_ids: typing.Union[str, list], wallet_id=None):
        """
        Hide a comment published to a claim you control.

        Usage:
            comment_hide  <comment_ids>... [--wallet_id=<wallet_id>]

        Options:
            --comment_ids=<comment_ids>  : (str, list) one or more comment_id to hide.
            --wallet_id=<wallet_id>      : (str) restrict operation to specific wallet

        Returns: lists containing the ids comments that are hidden and visible.

            {
                "hidden":   (list) IDs of hidden comments.
                "visible":  (list) IDs of visible comments.
            }
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)

        if isinstance(comment_ids, str):
            comment_ids = [comment_ids]

        comments = await comment_client.jsonrpc_post(
            self.conf.comment_server, 'get_comments_by_id', comment_ids=comment_ids
        )
        comments = comments['items']
        claim_ids = {comment['claim_id'] for comment in comments}
        claims = {cid: await self.ledger.get_claim_by_claim_id(wallet.accounts, claim_id=cid) for cid in claim_ids}
        pieces = []
        for comment in comments:
            claim = claims.get(comment['claim_id'])
            if claim:
                channel = await self.get_channel_or_none(
                    wallet,
                    account_ids=[],
                    channel_id=claim.channel.claim_id,
                    channel_name=claim.channel.claim_name,
                    for_signing=True
                )
                piece = {'comment_id': comment['comment_id']}
                comment_client.sign_comment(piece, channel, sign_comment_id=True)
                pieces.append(piece)
        return await comment_client.jsonrpc_post(self.conf.comment_server, 'comment.Hide', pieces=pieces)

    @requires(WALLET_COMPONENT)
    async def jsonrpc_comment_pin(self, comment_id=None, channel_id=None, channel_name=None,
                                  channel_account_id=None, remove=False, wallet_id=None):
        """
        Pin a comment published to a claim you control.

        Usage:
            comment_pin     (<comment_id> | --comment_id=<comment_id>)
                            (--channel_id=<channel_id>)
                            (--channel_name=<channel_name>)
                            [--remove]
                            [--channel_account_id=<channel_account_id>...] [--wallet_id=<wallet_id>]

        Options:
            --comment_id=<comment_id>   : (str) Hash identifying the comment to pin
            --channel_id=<claim_id>                     : (str) The ID of channel owning the commented claim
            --channel_name=<claim_name>                 : (str) The name of channel owning the commented claim
            --remove                                    : (bool) remove the pin
            --channel_account_id=<channel_account_id>   : (str) one or more account ids for accounts to look in
            --wallet_id=<wallet_id                      : (str) restrict operation to specific wallet

        Returns: lists containing the ids comments that are hidden and visible.

            {
                "hidden":   (list) IDs of hidden comments.
                "visible":  (list) IDs of visible comments.
            }
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        channel = await self.get_channel_or_error(
            wallet, channel_account_id, channel_id, channel_name, for_signing=True
        )
        comment_pin_args = {
            'comment_id': comment_id,
            'channel_name': channel_name,
            'channel_id': channel_id,
            'remove': remove,
        }
        comment_client.sign_comment(comment_pin_args, channel, sign_comment_id=True)
        return await comment_client.jsonrpc_post(self.conf.comment_server, 'comment.Pin', comment_pin_args)

    @requires(WALLET_COMPONENT)
    async def jsonrpc_comment_react(
            self, comment_ids, channel_name=None, channel_id=None,
            channel_account_id=None, remove=False, clear_types=None, react_type=None, wallet_id=None):
        """
        Create and associate a reaction emoji with a comment using your channel identity.

        Usage:
            comment_react   (--comment_ids=<comment_ids>)
                            (--channel_id=<channel_id>)
                            (--channel_name=<channel_name>)
                            (--react_type=<react_type>)
                            [(--remove) | (--clear_types=<clear_types>)]
                            [--channel_account_id=<channel_account_id>...] [--wallet_id=<wallet_id>]

        Options:
            --comment_ids=<comment_ids>                 : (str) one or more comment id reacted to, comma delimited
            --channel_id=<claim_id>                     : (str) The ID of channel reacting
            --channel_name=<claim_name>                 : (str) The name of the channel reacting
            --wallet_id=<wallet_id>                     : (str) restrict operation to specific wallet
            --channel_account_id=<channel_account_id>   : (str) one or more account ids for accounts to look in
            --react_type=<react_type>                   : (str) name of reaction type
            --remove                                    : (bool) remove specified react_type
            --clear_types=<clear_types>                 : (str) types to clear when adding another type


        Returns:
            (dict) Reaction object if successfully made, (None) otherwise
            {
            "Reactions": {
                <comment_id>: {
                    <reaction_type>: (int) Count for this reaction
                    ...
                }
            }
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        channel = await self.get_channel_or_error(
            wallet, channel_account_id, channel_id, channel_name, for_signing=True
        )

        react_body = {
            'comment_ids': comment_ids,
            'channel_id': channel_id,
            'channel_name': channel.claim_name,
            'type': react_type,
            'remove': remove,
            'clear_types': clear_types,
        }
        comment_client.sign_reaction(react_body, channel)

        response = await comment_client.jsonrpc_post(self.conf.comment_server, 'reaction.React', react_body)

        return response

    @requires(WALLET_COMPONENT)
    async def jsonrpc_comment_react_list(
            self, comment_ids, channel_name=None, channel_id=None,
            channel_account_id=None, react_types=None, wallet_id=None):
        """
        List reactions emoji with a claim using your channel identity.

        Usage:
            comment_react_list  (--comment_ids=<comment_ids>)
                                [(--channel_id=<channel_id>)(--channel_name=<channel_name>)]
                                [--react_types=<react_types>]

        Options:
            --comment_ids=<comment_ids>                 : (str) The comment ids reacted to, comma delimited
            --channel_id=<claim_id>                     : (str) The ID of channel reacting
            --channel_name=<claim_name>                 : (str) The name of the channel reacting
            --wallet_id=<wallet_id>                     : (str) restrict operation to specific wallet
            --react_types=<react_type>                   : (str) comma delimited reaction types

        Returns:
            (dict) Comment object if successfully made, (None) otherwise
            {
                "my_reactions": {
                    <comment_id>: {
                    <reaction_type>: (int) Count for this reaction type
                    ...
                    }
                }
                "other_reactions": {
                    <comment_id>: {
                    <reaction_type>: (int) Count for this reaction type
                    ...
                    }
                }
            }
        """
        wallet = self.wallet_manager.get_wallet_or_default(wallet_id)
        react_list_body = {
            'comment_ids': comment_ids,
        }
        if channel_id:
            channel = await self.get_channel_or_error(
                wallet, channel_account_id, channel_id, channel_name, for_signing=True
            )
            react_list_body['channel_id'] = channel_id
            react_list_body['channel_name'] = channel.claim_name

        if react_types:
            react_list_body['types'] = react_types
        if channel_id:
            comment_client.sign_reaction(react_list_body, channel)
        response = await comment_client.jsonrpc_post(self.conf.comment_server, 'reaction.List', react_list_body)
        return response

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
