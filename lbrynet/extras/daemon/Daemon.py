import os
import asyncio
import logging
import json
import time
import inspect
import typing
import base58
import random
import ecdsa
import hashlib
from urllib.parse import urlencode, quote
from typing import Callable, Optional, List
from binascii import hexlify, unhexlify
from traceback import format_exc
from aiohttp import web
from functools import wraps
from google.protobuf.message import DecodeError
from torba.client.wallet import Wallet
from torba.client.baseaccount import SingleKey, HierarchicalDeterministic

from lbrynet import utils
from lbrynet.conf import Config, Setting
from lbrynet.blob.blob_file import is_valid_blobhash, BlobBuffer
from lbrynet.blob_exchange.downloader import download_blob
from lbrynet.error import DownloadSDTimeout, ComponentsNotStarted
from lbrynet.error import NullFundsError, NegativeFundsError, ComponentStartConditionNotMet
from lbrynet.extras import system_info
from lbrynet.extras.daemon import analytics
from lbrynet.extras.daemon.Components import WALLET_COMPONENT, DATABASE_COMPONENT, DHT_COMPONENT, BLOB_COMPONENT
from lbrynet.extras.daemon.Components import STREAM_MANAGER_COMPONENT
from lbrynet.extras.daemon.Components import EXCHANGE_RATE_MANAGER_COMPONENT, UPNP_COMPONENT
from lbrynet.extras.daemon.ComponentManager import RequiredCondition
from lbrynet.extras.daemon.ComponentManager import ComponentManager
from lbrynet.extras.daemon.json_response_encoder import JSONResponseEncoder
from lbrynet.extras.daemon.undecorated import undecorated
from lbrynet.wallet.transaction import Transaction, Output, Input
from lbrynet.wallet.account import Account as LBCAccount
from lbrynet.wallet.dewies import dewies_to_lbc, lbc_to_dewies
from lbrynet.schema.claim import Claim
from lbrynet.schema.url import URL
from lbrynet.extras.daemon.comment_client import jsonrpc_batch, jsonrpc_post, rpc_body


if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_manager import BlobManager
    from lbrynet.dht.node import Node
    from lbrynet.extras.daemon.Components import UPnPComponent
    from lbrynet.extras.daemon.exchange_rate_manager import ExchangeRateManager
    from lbrynet.extras.daemon.storage import SQLiteStorage
    from lbrynet.wallet.manager import LbryWalletManager
    from lbrynet.wallet.ledger import MainNetLedger
    from lbrynet.stream.stream_manager import StreamManager
    from lbrynet.stream.managed_stream import ManagedStream

log = logging.getLogger(__name__)


def requires(*components, **conditions):
    if conditions and ["conditions"] != list(conditions.keys()):
        raise SyntaxError("invalid conditions argument")
    condition_names = conditions.get("conditions", [])

    def _wrap(fn):
        @wraps(fn)
        def _inner(*args, **kwargs):
            component_manager = args[0].component_manager
            for condition_name in condition_names:
                condition_result, err_msg = component_manager.evaluate_condition(condition_name)
                if not condition_result:
                    raise ComponentStartConditionNotMet(err_msg)
            if not component_manager.all_components_running(*components):
                raise ComponentsNotStarted("the following required components have not yet started: "
                                           "%s" % json.dumps(components))
            return fn(*args, **kwargs)
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

CONNECTION_STATUS_CONNECTED = 'connected'
CONNECTION_STATUS_NETWORK = 'network_connection'
CONNECTION_MESSAGES = {
    CONNECTION_STATUS_CONNECTED: 'No connection problems detected',
    CONNECTION_STATUS_NETWORK: "Your internet connection appears to have been interrupted",
}

SHORT_ID_LEN = 20
MAX_UPDATE_FEE_ESTIMATE = 0.3


def encode_pagination_doc(items):
    return {
        "page": "Page number of the current items.",
        "page_size": "Number of items to show on a page.",
        "total_pages": "Total number of pages.",
        "total_items": "Total number of items.",
        "items": [items],
    }


async def maybe_paginate(get_records: Callable, get_record_count: Callable,
                         page: Optional[int], page_size: Optional[int], **constraints):
    if None not in (page, page_size):
        constraints.update({
            "offset": page_size * (page-1),
            "limit": page_size
        })
        total_items = await get_record_count(**constraints)
        return {
            "items": await get_records(**constraints),
            "total_pages": int((total_items + (page_size-1)) / page_size),
            "total_items": total_items,
            "page": page, "page_size": page_size
        }
    return await get_records(**constraints)


def sort_claim_results(claims):
    claims.sort(key=lambda d: (d['height'], d['name'], d['claim_id'], d['txid'], d['nout']))


DHT_HAS_CONTACTS = "dht_has_contacts"
WALLET_IS_UNLOCKED = "wallet_is_unlocked"


class DHTHasContacts(RequiredCondition):
    name = DHT_HAS_CONTACTS
    component = DHT_COMPONENT
    message = "your node is not connected to the dht"

    @staticmethod
    def evaluate(component):
        return len(component.contacts) > 0


class WalletIsUnlocked(RequiredCondition):
    name = WALLET_IS_UNLOCKED
    component = WALLET_COMPONENT
    message = "your wallet is locked"

    @staticmethod
    def evaluate(component):
        return not component.check_locked()


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

    def __init__(self, message, code=CODE_APPLICATION_ERROR, traceback=None, data=None):
        assert isinstance(code, int), "'code' must be an int"
        assert (data is None or isinstance(data, dict)), "'data' must be None or a dict"
        self.code = code
        if message is None:
            message = self.MESSAGES[code] if code in self.MESSAGES else "API Error"
        self.message = message
        self.data = {} if data is None else data
        self.traceback = []
        if traceback is not None:
            self.traceback = trace_lines = traceback.split("\n")
            for i, t in enumerate(trace_lines):
                if "--- <exception caught here> ---" in t:
                    if len(trace_lines) > i + 1:
                        self.traceback = [j for j in trace_lines[i+1:] if j]
                        break

    def to_dict(self):
        return {
            'code': self.code,
            'message': self.message,
            'data': self.traceback
        }

    @classmethod
    def create_from_exception(cls, message, code=CODE_APPLICATION_ERROR, traceback=None):
        return cls(message, code=code, traceback=traceback)


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


class Daemon(metaclass=JSONRPCServerType):
    """
    LBRYnet daemon, a jsonrpc interface to lbry functions
    """

    def __init__(self, conf: Config, component_manager: typing.Optional[ComponentManager] = None):
        self.conf = conf
        self._node_id = None
        self._installation_id = None
        self.session_id = base58.b58encode(utils.generate_id()).decode()
        self.analytics_manager = analytics.AnalyticsManager(conf, self.installation_id, self.session_id)
        self.component_manager = component_manager or ComponentManager(
            conf, analytics_manager=self.analytics_manager,
            skip_components=conf.components_to_skip or []
        )
        self.component_startup_task = None
        self._connection_status: typing.Tuple[float, bool] = [self.component_manager.loop.time(), False]
        self.stop_event = asyncio.Event()

        logging.getLogger('aiohttp.access').setLevel(logging.WARN)
        rpc_app = web.Application()
        rpc_app.router.add_get('/lbryapi', self.handle_old_jsonrpc)
        rpc_app.router.add_post('/lbryapi', self.handle_old_jsonrpc)
        rpc_app.router.add_post('/', self.handle_old_jsonrpc)
        self.rpc_runner = web.AppRunner(rpc_app)

        streaming_app = web.Application()
        streaming_app.router.add_get('/get/{claim_name}', self.handle_stream_get_request)
        streaming_app.router.add_get('/get/{claim_name}/{claim_id}', self.handle_stream_get_request)
        streaming_app.router.add_get('/stream/{sd_hash}', self.handle_stream_range_request)
        self.streaming_runner = web.AppRunner(streaming_app)

    @property
    def dht_node(self) -> typing.Optional['Node']:
        return self.component_manager.get_component(DHT_COMPONENT)

    @property
    def wallet_manager(self) -> typing.Optional['LbryWalletManager']:
        return self.component_manager.get_component(WALLET_COMPONENT)

    @property
    def storage(self) -> typing.Optional['SQLiteStorage']:
        return self.component_manager.get_component(DATABASE_COMPONENT)

    @property
    def stream_manager(self) -> typing.Optional['StreamManager']:
        return self.component_manager.get_component(STREAM_MANAGER_COMPONENT)

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
        not_grouped = ['routing_table_get']
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
                    assert group in api['groups'],\
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

    async def update_connection_status(self):
        connected = await utils.async_check_connection()
        self._connection_status = (self.component_manager.loop.time(), connected)

    async def get_connection_status(self) -> str:
        if self._connection_status[0] + 300 > self.component_manager.loop.time():
            if not self._connection_status[1]:
                await self.update_connection_status()
        else:
            await self.update_connection_status()
        return CONNECTION_STATUS_CONNECTED if self._connection_status[1] else CONNECTION_STATUS_NETWORK

    async def start(self):
        log.info("Starting LBRYNet Daemon")
        log.debug("Settings: %s", json.dumps(self.conf.settings_dict, indent=2))
        log.info("Platform: %s", json.dumps(system_info.get_platform(), indent=2))
        await self.analytics_manager.send_server_startup()
        await self.rpc_runner.setup()
        await self.streaming_runner.setup()

        try:
            rpc_site = web.TCPSite(self.rpc_runner, self.conf.api_host, self.conf.api_port, shutdown_timeout=.5)
            await rpc_site.start()
            log.info('lbrynet API listening on TCP %s:%i', *rpc_site._server.sockets[0].getsockname()[:2])

            streaming_site = web.TCPSite(self.streaming_runner, self.conf.streaming_host, self.conf.streaming_port,
                                         shutdown_timeout=.5)
            await streaming_site.start()
            log.info('lbrynet media server listening on TCP %s:%i',
                     *streaming_site._server.sockets[0].getsockname()[:2])

        except OSError as e:
            log.error('lbrynet API failed to bind TCP %s for listening. Daemon is already running or this port is '
                      'already in use by another application.', self.conf.api)
            await self.analytics_manager.send_server_startup_error(str(e))
            raise SystemExit()

        try:
            await self.initialize()
        except asyncio.CancelledError:
            log.info("shutting down before finished starting")
            await self.analytics_manager.send_server_startup_error("shutting down before finished starting")
            await self.stop()
        except Exception as e:
            await self.analytics_manager.send_server_startup_error(str(e))
            log.exception('Failed to start lbrynet-daemon')

        await self.analytics_manager.send_server_startup_success()

    async def initialize(self):
        self.ensure_data_dir()
        self.ensure_wallet_dir()
        self.ensure_download_dir()
        if not self.analytics_manager.is_started:
            await self.analytics_manager.start()
        self.component_startup_task = asyncio.create_task(self.component_manager.start())
        await self.component_startup_task

    async def stop(self, shutdown_runner=True):
        if self.component_startup_task is not None:
            if self.component_startup_task.done():
                await self.component_manager.stop()
            else:
                self.component_startup_task.cancel()
        log.info("stopped api components")
        if shutdown_runner:
            await self.rpc_runner.shutdown()
            await self.streaming_runner.shutdown()
        await self.rpc_runner.cleanup()
        await self.streaming_runner.cleanup()
        log.info("stopped api server")
        if self.analytics_manager.is_started:
            self.analytics_manager.stop()
        log.info("finished shutting down")

    async def handle_old_jsonrpc(self, request):
        data = await request.json()
        include_protobuf = data.get('params', {}).pop('include_protobuf', False)
        result = await self._process_rpc_call(data)
        ledger = None
        if 'wallet' in self.component_manager.get_components_status():
            # self.ledger only available if wallet component is not skipped
            ledger = self.ledger
        try:
            encoded_result = jsonrpc_dumps_pretty(
                result, ledger=ledger, include_protobuf=include_protobuf)
        except:
            log.exception('Failed to encode JSON RPC result:')
            encoded_result = jsonrpc_dumps_pretty(JSONRPCError(
                'After successfully executing the command, failed to encode result for JSON RPC response.',
                JSONRPCError.CODE_APPLICATION_ERROR, format_exc()
            ), ledger=ledger)
        return web.Response(
            text=encoded_result,
            content_type='application/json'
        )

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
        if not self.stream_manager.started.is_set():
            await self.stream_manager.started.wait()
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
            log.debug("/stream range request cancelled")
        except Exception:
            log.exception("error handling /stream range request")
            raise
        finally:
            log.debug("finished handling /stream range request")

    async def _handle_stream_range_request(self, request: web.Request):
        sd_hash = request.path.split("/stream/")[1]
        if not self.stream_manager.started.is_set():
            await self.stream_manager.started.wait()
        if sd_hash not in self.stream_manager.streams:
            return web.HTTPNotFound()
        return await self.stream_manager.stream_partial_content(request, sd_hash)

    async def _process_rpc_call(self, data):
        args = data.get('params', {})

        try:
            function_name = data['method']
        except KeyError:
            return JSONRPCError(
                "Missing 'method' value in request.", JSONRPCError.CODE_METHOD_NOT_FOUND
            )

        try:
            fn = self._get_jsonrpc_method(function_name)
        except UnknownAPIMethodError:
            return JSONRPCError(
                f"Invalid method requested: {function_name}.", JSONRPCError.CODE_METHOD_NOT_FOUND
            )

        if args in ([{}], []):
            _args, _kwargs = (), {}
        elif isinstance(args, dict):
            _args, _kwargs = (), args
        elif len(args) == 1 and isinstance(args[0], dict):
            # TODO: this is for backwards compatibility. Remove this once API and UI are updated
            # TODO: also delete EMPTY_PARAMS then
            _args, _kwargs = (), args[0]
        elif len(args) == 2 and isinstance(args[0], list) and isinstance(args[1], dict):
            _args, _kwargs = args
        else:
            return JSONRPCError(
                f"Invalid parameters format.", JSONRPCError.CODE_INVALID_PARAMS
            )

        params_error, erroneous_params = self._check_params(fn, _args, _kwargs)
        if params_error is not None:
            params_error_message = '{} for {} command: {}'.format(
                params_error, function_name, ', '.join(erroneous_params)
            )
            log.warning(params_error_message)
            return JSONRPCError(
                params_error_message, JSONRPCError.CODE_INVALID_PARAMS
            )

        try:
            result = fn(self, *_args, **_kwargs)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except asyncio.CancelledError:
            log.info("cancelled API call for: %s", function_name)
            raise
        except Exception as e:  # pylint: disable=broad-except
            log.exception("error handling api request")
            return JSONRPCError(
                str(e), JSONRPCError.CODE_APPLICATION_ERROR, format_exc()
            )

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
            for required_param in argspec.args[len(args_tup)+1:-num_optional_params]
            if required_param not in args_dict
        ]
        if len(missing_required_params):
            return 'Missing required parameters', missing_required_params

        extraneous_params = [] if argspec.varkw is not None else [
            extra_param
            for extra_param in args_dict
            if extra_param not in argspec.args[1:]
        ]
        if len(extraneous_params):
            return 'Extraneous parameters', extraneous_params

        return None, None

    @property
    def default_wallet(self):
        try:
            return self.wallet_manager.default_wallet
        except AttributeError:
            return None

    @property
    def default_account(self) -> Optional[LBCAccount]:
        try:
            return self.wallet_manager.default_account
        except AttributeError:
            return None

    @property
    def ledger(self) -> Optional['MainNetLedger']:
        try:
            return self.wallet_manager.default_account.ledger
        except AttributeError:
            return None

    async def get_est_cost_from_uri(self, uri: str) -> typing.Optional[float]:
        """
        Resolve a name and return the estimated stream cost
        """

        resolved = await self.resolve(uri)
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

    def jsonrpc_stop(self):
        """
        Stop lbrynet API server.

        Usage:
            stop

        Options:
            None

        Returns:
            (string) Shutdown message
        """
        log.info("Shutting down lbrynet daemon")
        self.stop_event.set()
        return "Shutting down"

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
                    'stream_manager': (bool),
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
                    'blocks': (int) local blockchain height,
                    'blocks_behind': (int) remote_height - local_height,
                    'best_blockhash': (str) block hash of most recent block,
                    'is_encrypted': (bool),
                    'is_locked': (bool),
                },
                'dht': {
                    'node_id': (str) lbry dht node id - hex encoded,
                    'peers_in_routing_table': (int) the number of peers in the routing table,
                },
                'blob_manager': {
                    'finished_blobs': (int) number of finished blobs in the blob manager,
                },
                'hash_announcer': {
                    'announce_queue_size': (int) number of blobs currently queued to be announced
                },
                'stream_manager': {
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

        connection_code = await self.get_connection_status()

        response = {
            'installation_id': self.installation_id,
            'is_running': all(self.component_manager.get_components_status().values()),
            'skipped_components': self.component_manager.skip_components,
            'startup_status': self.component_manager.get_components_status(),
            'connection_status': {
                'code': connection_code,
                'message': CONNECTION_MESSAGES[connection_code],
            },
        }
        for component in self.component_manager.components:
            status = await component.get_status()
            if status:
                response[component.component_name] = status
        return response

    def jsonrpc_version(self):
        """
        Get lbrynet API server version information

        Usage:
            version

        Options:
            None

        Returns:
            (dict) Dictionary of lbry version information
            {
                'build': (str) build type (e.g. "dev", "rc", "release"),
                'ip': (str) remote ip, if available,
                'lbrynet_version': (str) lbrynet_version,
                'lbryum_version': (str) lbryum_version,
                'lbryschema_version': (str) lbryschema_version,
                'os_release': (str) os release string
                'os_system': (str) os name
                'platform': (str) platform string
                'processor': (str) processor type,
                'python_version': (str) python version,
            }
        """
        platform_info = system_info.get_platform()
        log.info("Get version info: " + json.dumps(platform_info))
        return platform_info

    @requires(WALLET_COMPONENT)
    async def jsonrpc_resolve(self, urls: typing.Union[str, list]):
        """
        Get the claim that a URL refers to.

        Usage:
            resolve <urls>...

        Options:
            --urls=<urls>   : (str, list) one or more urls to resolve

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

        if isinstance(urls, str):
            urls = [urls]

        results = {}

        valid_urls = set()
        for u in urls:
            try:
                URL.parse(u)
                valid_urls.add(u)
            except ValueError:
                results[u] = {"error": f"{u} is not a valid url"}

        resolved = await self.resolve(list(valid_urls))

        for resolved_uri in resolved:
            results[resolved_uri] = resolved[resolved_uri] if resolved[resolved_uri] is not None else \
                                    {"error": f"{resolved_uri} did not resolve to a claim"}

        return results

    @requires(WALLET_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT, BLOB_COMPONENT, DATABASE_COMPONENT,
              STREAM_MANAGER_COMPONENT,
              conditions=[WALLET_IS_UNLOCKED])
    async def jsonrpc_get(self, uri, file_name=None, download_directory=None, timeout=None, save_file=None):
        """
        Download stream from a LBRY name.

        Usage:
            get <uri> [<file_name> | --file_name=<file_name>]
             [<download_directory> | --download_directory=<download_directory>] [<timeout> | --timeout=<timeout>]
             [--save_file=<save_file>]


        Options:
            --uri=<uri>              : (str) uri of the content to download
            --file_name=<file_name>  : (str) specified name for the downloaded file, overrides the stream file name
            --download_directory=<download_directory>  : (str) full path to the directory to download into
            --timeout=<timeout>      : (int) download timeout in number of seconds
            --save_file=<save_file>  : (bool) save the file to the downloads directory

        Returns: {File}
        """
        if download_directory and not os.path.isdir(download_directory):
            return {"error": f"specified download directory \"{download_directory}\" does not exist"}
        try:
            stream = await self.stream_manager.download_stream_from_uri(
                uri, self.exchange_rate_manager, timeout, file_name, download_directory, save_file=save_file
            )
            if not stream:
                raise DownloadSDTimeout(uri)
        except Exception as e:
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
            See ADJUSTABLE_SETTINGS in lbrynet/conf.py for full list of settings
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
            attr: Setting = getattr(type(c), key)
            cleaned = attr.deserialize(value)
            setattr(c, key, cleaned)
        return {key: cleaned}

    ACCOUNT_DOC = """
    Create, modify and inspect wallet accounts.
    """

    @requires("wallet")
    def jsonrpc_account_list(self, account_id=None, confirmations=0,
                             include_claims=False, show_seed=False):
        """
        List details of all of the accounts or a specific account.

        Usage:
            account_list [<account_id>] [--confirmations=<confirmations>]
                         [--include_claims] [--show_seed]

        Options:
            --account_id=<account_id>       : (str) If provided only the balance for this
                                                    account will be given
            --confirmations=<confirmations> : (int) required confirmations (default: 0)
            --include_claims                : (bool) include claims, requires than a
                                                     LBC account is specified (default: false)
            --show_seed                     : (bool) show the seed for the account

        Returns: {List[Account]}
        """
        kwargs = {
            'confirmations': confirmations,
            'show_seed': show_seed
        }
        if account_id:
            return self.get_account_or_error(account_id).get_details(**kwargs)
        else:
            return self.wallet_manager.get_detailed_accounts(**kwargs)

    @requires("wallet")
    async def jsonrpc_account_balance(self, account_id=None, confirmations=0):
        """
        Return the balance of an account

        Usage:
            account_balance [<account_id>] [<address> | --address=<address>]

        Options:
            --account_id=<account_id>       : (str) If provided only the balance for this
                                              account will be given. Otherwise default account.
            --confirmations=<confirmations> : (int) Only include transactions with this many
                                              confirmed blocks.

        Returns:
            (decimal) amount of lbry credits in wallet
        """
        account = self.get_account_or_default(account_id)
        dewies = await account.get_balance(confirmations=confirmations)
        return dewies_to_lbc(dewies)

    @requires("wallet")
    async def jsonrpc_account_add(
            self, account_name, single_key=False, seed=None, private_key=None, public_key=None):
        """
        Add a previously created account from a seed, private key or public key (read-only).
        Specify --single_key for single address or vanity address accounts.

        Usage:
            account_add (<account_name> | --account_name=<account_name>)
                 (--seed=<seed> | --private_key=<private_key> | --public_key=<public_key>)
                 [--single_key]

        Options:
            --account_name=<account_name>  : (str) name of the account to add
            --seed=<seed>                  : (str) seed to generate new account from
            --private_key=<private_key>    : (str) private key for new account
            --public_key=<public_key>      : (str) public key for new account
            --single_key                   : (bool) create single key account, default is multi-key

        Returns: {Account}
        """
        account = LBCAccount.from_dict(
            self.ledger, self.default_wallet, {
                'name': account_name,
                'seed': seed,
                'private_key': private_key,
                'public_key': public_key,
                'address_generator': {
                    'name': SingleKey.name if single_key else HierarchicalDeterministic.name
                }
            }
        )

        if self.ledger.network.is_connected:
            await self.ledger.subscribe_account(account)

        self.default_wallet.save()

        return account

    @requires("wallet")
    async def jsonrpc_account_create(self, account_name, single_key=False):
        """
        Create a new account. Specify --single_key if you want to use
        the same address for all transactions (not recommended).

        Usage:
            account_create (<account_name> | --account_name=<account_name>) [--single_key]

        Options:
            --account_name=<account_name>  : (str) name of the account to create
            --single_key                   : (bool) create single key account, default is multi-key

        Returns: {Account}
        """
        account = LBCAccount.generate(
            self.ledger, self.default_wallet, account_name, {
                'name': SingleKey.name if single_key else HierarchicalDeterministic.name
            }
        )

        if self.ledger.network.is_connected:
            await self.ledger.subscribe_account(account)

        self.default_wallet.save()

        return account

    @requires("wallet")
    def jsonrpc_account_remove(self, account_id):
        """
        Remove an existing account.

        Usage:
            account_remove (<account_id> | --account_id=<account_id>)

        Options:
            --account_id=<account_id>  : (str) id of the account to remove

        Returns: {Account}
        """
        account = self.get_account_or_error(account_id)
        self.default_wallet.accounts.remove(account)
        self.default_wallet.save()
        return account

    @requires("wallet")
    def jsonrpc_account_set(
            self, account_id, default=False, new_name=None,
            change_gap=None, change_max_uses=None, receiving_gap=None, receiving_max_uses=None):
        """
        Change various settings on an account.

        Usage:
            account_set (<account_id> | --account_id=<account_id>)
                [--default] [--new_name=<new_name>]
                [--change_gap=<change_gap>] [--change_max_uses=<change_max_uses>]
                [--receiving_gap=<receiving_gap>] [--receiving_max_uses=<receiving_max_uses>]

        Options:
            --account_id=<account_id>       : (str) id of the account to change
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
        account = self.get_account_or_error(account_id)
        change_made = False

        if account.receiving.name == HierarchicalDeterministic.name:
            address_changes = {
                'change': {'gap': change_gap, 'maximum_uses_per_address': change_max_uses},
                'receiving': {'gap': receiving_gap, 'maximum_uses_per_address': receiving_max_uses},
            }
            for chain_name in address_changes:
                chain = getattr(account, chain_name)
                for attr, value in address_changes[chain_name].items():
                    if value is not None:
                        setattr(chain, attr, value)
                        change_made = True

        if new_name is not None:
            account.name = new_name
            change_made = True

        if default:
            self.default_wallet.accounts.remove(account)
            self.default_wallet.accounts.insert(0, account)
            change_made = True

        if change_made:
            account.modified_on = time.time()
            self.default_wallet.save()

        return account

    @requires(WALLET_COMPONENT)
    def jsonrpc_account_unlock(self, password, account_id=None):
        """
        Unlock an encrypted account

        Usage:
            account_unlock (<password> | --password=<password>) [<account_id> | --account_id=<account_id>]

        Options:
            --password=<password>        : (str) password to use for unlocking
            --account_id=<account_id>    : (str) id for the account to unlock, unlocks default account
                                                 if not provided

        Returns:
            (bool) true if account is unlocked, otherwise false
        """

        return self.wallet_manager.unlock_account(
            password, self.get_account_or_default(account_id, lbc_only=False)
        )

    @requires(WALLET_COMPONENT)
    def jsonrpc_account_lock(self, account_id=None):
        """
        Lock an unlocked account

        Usage:
            account_lock [<account_id> | --account_id=<account_id>]

        Options:
            --account_id=<account_id>        : (str) id for the account to lock

        Returns:
            (bool) true if account is locked, otherwise false
        """

        return self.wallet_manager.lock_account(self.get_account_or_default(account_id, lbc_only=False))

    @requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    def jsonrpc_account_decrypt(self, account_id=None):
        """
        Decrypt an encrypted account, this will remove the wallet password. The account must be unlocked to decrypt it

        Usage:
            account_decrypt [<account_id> | --account_id=<account_id>]

        Options:
            --account_id=<account_id>  : (str) id for the account to decrypt

        Returns:
            (bool) true if wallet is decrypted, otherwise false
        """

        return self.wallet_manager.decrypt_account(self.get_account_or_default(account_id, lbc_only=False))

    @requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    def jsonrpc_account_encrypt(self, new_password, account_id=None):
        """
        Encrypt an unencrypted account with a password

        Usage:
            account_encrypt (<new_password> | --new_password=<new_password>)
                            [<account_id> | --account_id=<account_id>]

        Options:
            --new_password=<new_password>    : (str) password to encrypt account
            --account_id=<account_id>        : (str) id for the account to encrypt, encrypts
                                                     default account if not provided

        Returns:
            (bool) true if wallet is decrypted, otherwise false
        """

        return self.wallet_manager.encrypt_account(
            new_password,
            self.get_account_or_default(account_id, lbc_only=False)
        )

    @requires("wallet")
    def jsonrpc_account_max_address_gap(self, account_id):
        """
        Finds ranges of consecutive addresses that are unused and returns the length
        of the longest such range: for change and receiving address chains. This is
        useful to figure out ideal values to set for 'receiving_gap' and 'change_gap'
        account settings.

        Usage:
            account_max_address_gap (<account_id> | --account_id=<account_id>)

        Options:
            --account_id=<account_id>        : (str) account for which to get max gaps

        Returns:
            (map) maximum gap for change and receiving addresses
        """
        return self.get_account_or_error(account_id).get_max_gap()

    @requires("wallet")
    def jsonrpc_account_fund(self, to_account=None, from_account=None, amount='0.0',
                             everything=False, outputs=1, broadcast=False):
        """
        Transfer some amount (or --everything) to an account from another
        account (can be the same account). Amounts are interpreted as LBC.
        You can also spread the transfer across a number of --outputs (cannot
        be used together with --everything).

        Usage:
            account_fund [<to_account> | --to_account=<to_account>]
                [<from_account> | --from_account=<from_account>]
                (<amount> | --amount=<amount> | --everything)
                [<outputs> | --outputs=<outputs>]
                [--broadcast]

        Options:
            --to_account=<to_account>     : (str) send to this account
            --from_account=<from_account> : (str) spend from this account
            --amount=<amount>             : (str) the amount to transfer lbc
            --everything                  : (bool) transfer everything (excluding claims), default: false.
            --outputs=<outputs>           : (int) split payment across many outputs, default: 1.
            --broadcast                   : (bool) actually broadcast the transaction, default: false.

        Returns: {Transaction}
        """
        to_account = self.get_account_or_default(to_account, 'to_account')
        from_account = self.get_account_or_default(from_account, 'from_account')
        amount = self.get_dewies_or_error('amount', amount) if amount else None
        if not isinstance(outputs, int):
            raise ValueError("--outputs must be an integer.")
        if everything and outputs > 1:
            raise ValueError("Using --everything along with --outputs is not supported.")
        return from_account.fund(
            to_account=to_account, amount=amount, everything=everything,
            outputs=outputs, broadcast=broadcast
        )

    @requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    async def jsonrpc_account_send(self, amount, addresses, account_id=None, preview=False):
        """
        Send the same number of credits to multiple addresses.

        Usage:
            account_send <amount> <addresses>... [--account_id=<account_id>] [--preview]

        Options:
            --account_id=<account_id>  : (str) account to fund the transaction
            --preview                  : (bool) do not broadcast the transaction

        Returns: {Transaction}
        """
        account = self.get_account_or_default(account_id)

        amount = self.get_dewies_or_error("amount", amount)
        if not amount:
            raise NullFundsError
        if amount < 0:
            raise NegativeFundsError()

        if addresses and not isinstance(addresses, list):
            addresses = [addresses]

        outputs = []
        for address in addresses:
            self.valid_address_or_error(address)
            outputs.append(
                Output.pay_pubkey_hash(
                    amount, self.ledger.address_to_hash160(address)
                )
            )

        tx = await Transaction.create(
            [], outputs, [account], account
        )

        if not preview:
            await self.ledger.broadcast(tx)
            await self.analytics_manager.send_credits_sent()
        else:
            await account.ledger.release_tx(tx)

        return tx

    SYNC_DOC = """
    Wallet synchronization.
    """

    @requires("wallet")
    def jsonrpc_sync_hash(self):
        """
        Deterministic hash of the wallet.

        Usage:
            sync_hash

        Options:

        Returns:
            (str) sha256 hash of wallet
        """
        return hexlify(self.default_wallet.hash).decode()

    @requires("wallet")
    def jsonrpc_sync_apply(self, password, data=None, encrypt_password=None):
        """
        Apply incoming synchronization data, if provided, and then produce a sync hash and
        an encrypted wallet.

        Usage:
            sync_apply <password> [--data=<data>] [--encrypt-password=<encrypt_password>]

        Options:
            --password=<password>         : (str) password to decrypt incoming and encrypt outgoing data
            --data=<data>                 : (str) incoming sync data, if any
            --encrypt-password=<encrypt_password> : (str) password to encrypt outgoing data if different
                                                    from the decrypt password, used during password changes

        Returns:
            (map) sync hash and data

        """
        if data is not None:
            decrypted_data = Wallet.unpack(password, data)
            for account_data in decrypted_data['accounts']:
                _, _, pubkey = LBCAccount.keys_from_dict(self.ledger, account_data)
                account_id = pubkey.address
                local_match = None
                for local_account in self.default_wallet.accounts:
                    if account_id == local_account.id:
                        local_match = local_account
                        break
                if local_match is not None:
                    local_match.apply(account_data)
                else:
                    new_account = LBCAccount.from_dict(self.ledger, self.default_wallet, account_data)
                    if self.ledger.network.is_connected:
                        asyncio.create_task(self.ledger.subscribe_account(new_account))
            self.default_wallet.save()

        encrypted = self.default_wallet.pack(encrypt_password or password)
        return {
            'hash': self.jsonrpc_sync_hash(),
            'data': encrypted.decode()
        }

    ADDRESS_DOC = """
    List, generate and verify addresses.
    """

    @requires(WALLET_COMPONENT)
    async def jsonrpc_address_is_mine(self, address, account_id=None):
        """
        Checks if an address is associated with the current wallet.

        Usage:
            address_is_mine (<address> | --address=<address>)
                                   [<account_id> | --account_id=<account_id>]

        Options:
            --address=<address>       : (str) address to check
            --account_id=<account_id> : (str) id of the account to use

        Returns:
            (bool) true, if address is associated with current wallet
        """
        account = self.get_account_or_default(account_id)
        match = await self.ledger.db.get_address(address=address, account=account)
        if match is not None:
            return True
        return False

    @requires(WALLET_COMPONENT)
    def jsonrpc_address_list(self, account_id=None, page=None, page_size=None):
        """
        List account addresses

        Usage:
            address_list [<account_id> | --account_id=<account_id>]
                         [--page=<page>] [--page_size=<page_size>]

        Options:
            --account_id=<account_id>  : (str) id of the account to use
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination

        Returns: {Paginated[Address]}
        """
        account = self.get_account_or_default(account_id)
        return maybe_paginate(
            account.get_addresses,
            account.get_address_count,
            page, page_size
        )

    @requires(WALLET_COMPONENT)
    def jsonrpc_address_unused(self, account_id=None):
        """
        Return an address containing no balance, will create
        a new address if there is none.

        Usage:
            address_unused [--account_id=<account_id>]

        Options:
            --account_id=<account_id> : (str) id of the account to use

        Returns: {Address}
        """
        return self.get_account_or_default(account_id).receiving.get_or_create_usable_address()

    FILE_DOC = """
    File management.
    """

    @requires(STREAM_MANAGER_COMPONENT)
    def jsonrpc_file_list(self, sort=None, reverse=False, comparison=None, **kwargs):
        """
        List files limited by optional filters

        Usage:
            file_list [--sd_hash=<sd_hash>] [--file_name=<file_name>] [--stream_hash=<stream_hash>]
                      [--rowid=<rowid>] [--claim_id=<claim_id>] [--outpoint=<outpoint>] [--txid=<txid>] [--nout=<nout>]
                      [--channel_claim_id=<channel_claim_id>] [--channel_name=<channel_name>]
                      [--claim_name=<claim_name>] [--blobs_in_stream=<blobs_in_stream>]
                      [--blobs_remaining=<blobs_remaining>] [--sort=<sort_by>]
                      [--comparison=<comparison>] [--full_status=<full_status>] [--reverse]

        Options:
            --sd_hash=<sd_hash>                    : (str) get file with matching sd hash
            --file_name=<file_name>                : (str) get file with matching file name in the
                                                     downloads folder
            --stream_hash=<stream_hash>            : (str) get file with matching stream hash
            --rowid=<rowid>                        : (int) get file with matching row id
            --claim_id=<claim_id>                  : (str) get file with matching claim id
            --outpoint=<outpoint>                  : (str) get file with matching claim outpoint
            --txid=<txid>                          : (str) get file with matching claim txid
            --nout=<nout>                          : (int) get file with matching claim nout
            --channel_claim_id=<channel_claim_id>  : (str) get file with matching channel claim id
            --channel_name=<channel_name>          : (str) get file with matching channel name
            --claim_name=<claim_name>              : (str) get file with matching claim name
            --blobs_in_stream<blobs_in_stream>     : (int) get file with matching blobs in stream
            --blobs_remaining=<blobs_remaining>    : (int) amount of remaining blobs to download
            --sort=<sort_by>                       : (str) field to sort by (one of the above filter fields)
            --comparison=<comparison>              : (str) logical comparision, (eq | ne | g | ge | l | le)

        Returns: {List[File]}
        """
        sort = sort or 'rowid'
        comparison = comparison or 'eq'
        return self.stream_manager.get_filtered_streams(
            sort, reverse, comparison, **kwargs
        )

    @requires(STREAM_MANAGER_COMPONENT)
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
            raise Exception('Status must be "start" or "stop".')

        streams = self.stream_manager.get_filtered_streams(**kwargs)
        if not streams:
            raise Exception(f'Unable to find a file for {kwargs}')
        stream = streams[0]
        if status == 'start' and not stream.running:
            await stream.save_file(node=self.stream_manager.node)
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

    @requires(STREAM_MANAGER_COMPONENT)
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

        streams = self.stream_manager.get_filtered_streams(**kwargs)

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
                await self.stream_manager.delete_stream(stream, delete_file=delete_from_download_dir)
                log.info(message)
            result = True
        return result

    @requires(STREAM_MANAGER_COMPONENT)
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

        streams = self.stream_manager.get_filtered_streams(**kwargs)

        if len(streams) > 1:
            log.warning("There are %i matching files, use narrower filters to select one", len(streams))
            return False
        if not streams:
            log.warning("There is no file to save")
            return False
        stream = streams[0]
        await stream.save_file(file_name, download_directory)
        return stream

    CLAIM_DOC = """
    List and search all types of claims.
    """

    @requires(WALLET_COMPONENT)
    def jsonrpc_claim_list(self, account_id=None, page=None, page_size=None):
        """
        List my stream and channel claims.

        Usage:
            claim_list [<account_id> | --account_id=<account_id>]
                       [--page=<page>] [--page_size=<page_size>]

        Options:
            --account_id=<account_id> : (str) id of the account to query
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination

        Returns: {Paginated[Output]}
        """
        account = self.get_account_or_default(account_id)
        return maybe_paginate(
            account.get_claims,
            account.get_claim_count,
            page, page_size
        )

    @requires(WALLET_COMPONENT)
    async def jsonrpc_claim_search(self, **kwargs):
        """
        Search for stream and channel claims on the blockchain.

        Arguments marked with "supports equality constraints" allow prepending the
        value with an equality constraint such as '>', '>=', '<' and '<='
        eg. --height=">400000" would limit results to only claims above 400k block height.

        Usage:
            claim_search [<name> | --name=<name>] [--claim_id=<claim_id>] [--txid=<txid>] [--nout=<nout>]
                         [--channel=<channel> | --channel_ids=<channel_ids>...]
                         [--valid_channel_signatures] [--invalid_channel_signatures]
                         [--is_controlling] [--release_time=<release_time>]
                         [--timestamp=<timestamp>] [--creation_timestamp=<creation_timestamp>]
                         [--height=<height>] [--creation_height=<creation_height>]
                         [--activation_height=<activation_height>] [--expiration_height=<expiration_height>]
                         [--amount=<amount>] [--effective_amount=<effective_amount>]
                         [--support_amount=<support_amount>] [--trending_group=<trending_group>]
                         [--trending_mixed=<trending_mixed>] [--trending_local=<trending_local>]
                         [--trending_global=<trending_global]
                         [--any_tags=<any_tags>...] [--all_tags=<all_tags>...] [--not_tags=<not_tags>...]
                         [--any_languages=<any_languages>...] [--all_languages=<all_languages>...]
                         [--not_languages=<not_languages>...]
                         [--any_locations=<any_locations>...] [--all_locations=<all_locations>...]
                         [--not_locations=<not_locations>...]
                         [--order_by=<order_by>...] [--page=<page>] [--page_size=<page_size>]

        Options:
            --name=<name>                   : (str) claim name (normalized)
            --claim_id=<claim_id>           : (str) full or partial claim id
            --txid=<txid>                   : (str) transaction id
            --nout=<nout>                   : (str) position in the transaction
            --channel=<channel>             : (str) claims signed by this channel (argument is
                                                    a URL which automatically gets resolved),
                                                    see --channel_ids if you need to filter by
                                                    multiple channels at the same time,
                                                    includes claims with invalid signatures,
                                                    use in conjunction with --valid_channel_signatures
            --channel_ids=<channel_ids>     : (str) claims signed by any of these channels
                                                    (arguments must be claim ids of the channels),
                                                    includes claims with invalid signatures,
                                                    use in conjunction with --valid_channel_signatures
            --valid_channel_signatures      : (bool) only return claims with valid channel signatures
            --invalid_channel_signatures    : (bool) only return claims with invalid channel signatures
            --is_controlling                : (bool) only return winning claims of their respective name
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
            --support_amount=<support_amount>: (int) limit by supports and tips recieved (supports
                                                    equality constraints)
            --effective_amount=<effective_amount>: (int) limit by total value (initial claim value plus
                                                     all tips and supports received), this amount is
                                                     blank until claim has reached activation height
                                                     (supports equality constraints)
            --trending_group=<trending_group>: (int) group numbers 1 through 4 representing the
                                                    trending groups of the content: 4 means
                                                    content is trending globally and independently,
                                                    3 means content is not trending globally but is
                                                    trending independently (locally), 2 means it is
                                                    trending globally but not independently and 1
                                                    means it's not trending globally or locally
                                                    (supports equality constraints)
            --trending_mixed=<trending_mixed>: (int) trending amount taken from the global or local
                                                    value depending on the trending group:
                                                    4 - global value, 3 - local value, 2 - global
                                                    value, 1 - local value (supports equality
                                                    constraints)
            --trending_local=<trending_local>: (int) trending value calculated relative only to
                                                    the individual contents past history (supports
                                                    equality constraints)
            --trending_global=<trending_global>: (int) trending value calculated relative to all
                                                    trending content globally (supports
                                                    equality constraints)
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
            --order_by=<order_by>           : (str) field to order by, default is descending order, to do an
                                                    ascending order prepend ^ to the field name, eg. '^amount'
                                                    available fields: 'name', 'height', 'release_time',
                                                    'publish_time', 'amount', 'effective_amount',
                                                    'support_amount', 'trending_group', 'trending_mixed',
                                                    'trending_local', 'trending_global', 'activation_height'

        Returns: {Paginated[Output]}
        """
        if kwargs.pop('valid_channel_signatures', False):
            kwargs['is_channel_signature_valid'] = 1
        elif kwargs.pop('invalid_channel_signatures', False):
            kwargs['is_channel_signature_valid'] = 0
        page_num, page_size = abs(kwargs.pop('page', 1)), min(abs(kwargs.pop('page_size', 10)), 50)
        kwargs.update({'offset': page_size * (page_num-1), 'limit': page_size})
        txos, offset, total = await self.ledger.claim_search(**kwargs)
        return {
            "items": txos, "page": page_num, "page_size": page_size,
            "total_pages": int((total + (page_size-1)) / page_size),
            "total_items": total
        }

    CHANNEL_DOC = """
    Create, update, abandon and list your channel claims.
    """

    @deprecated('channel_create')
    def jsonrpc_channel_new(self):
        """ deprecated """

    @requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    async def jsonrpc_channel_create(
            self, name, bid, allow_duplicate_name=False, account_id=None, claim_address=None,
            preview=False, **kwargs):
        """
        Create a new channel by generating a channel private key and establishing an '@' prefixed claim.

        Usage:
            channel_create (<name> | --name=<name>) (<bid> | --bid=<bid>)
                           [--allow_duplicate_name=<allow_duplicate_name>]
                           [--title=<title>] [--description=<description>] [--email=<email>]
                           [--website_url=<website_url>] [--featured=<featured>...]
                           [--tags=<tags>...] [--languages=<languages>...] [--locations=<locations>...]
                           [--thumbnail_url=<thumbnail_url>] [--cover_url=<cover_url>]
                           [--account_id=<account_id>] [--claim_address=<claim_address>] [--preview]

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
            --account_id=<account_id>      : (str) id of the account to store channel
            --claim_address=<claim_address>: (str) address where the channel is sent to, if not specified
                                                   it will be determined automatically from the account
            --preview                      : (bool) do not broadcast the transaction

        Returns: {Transaction}
        """
        account = self.get_account_or_default(account_id)
        self.valid_channel_name_or_error(name)
        amount = self.get_dewies_or_error('bid', bid, positive_value=True)
        claim_address = await self.get_receiving_address(claim_address, account)

        existing_channels = await account.get_channels(claim_name=name)
        if len(existing_channels) > 0:
            if not allow_duplicate_name:
                raise Exception(
                    f"You already have a channel under the name '{name}'. "
                    f"Use --allow-duplicate-name flag to override."
                )

        claim = Claim()
        claim.channel.update(**kwargs)
        tx = await Transaction.claim_create(
            name, claim, amount, claim_address, [account], account
        )
        txo = tx.outputs[0]
        txo.generate_channel_private_key()

        if not preview:
            await tx.sign([account])
            await account.ledger.broadcast(tx)
            account.add_channel_private_key(txo.private_key)
            self.default_wallet.save()
            await self.storage.save_claims([self._old_get_temp_claim_info(
                tx, txo, claim_address, claim, name, dewies_to_lbc(amount)
            )])
            await self.analytics_manager.send_new_channel()
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    async def jsonrpc_channel_update(
            self, claim_id, bid=None, account_id=None, claim_address=None,
            new_signing_key=False, preview=False, replace=False, **kwargs):
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
                           [--account_id=<account_id>] [--claim_address=<claim_address>] [--new_signing_key]
                           [--preview] [--replace]

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
            --account_id=<account_id>      : (str) id of the account to store channel
            --claim_address=<claim_address>: (str) address where the channel is sent
            --new_signing_key              : (bool) generate a new signing key, will invalidate all previous publishes
            --preview                      : (bool) do not broadcast the transaction
            --replace                      : (bool) instead of modifying specific values on
                                                    the channel, this will clear all existing values
                                                    and only save passed in values, useful for form
                                                    submissions where all values are always set

        Returns: {Transaction}
        """
        account = self.get_account_or_default(account_id)

        existing_channels = await account.get_claims(claim_id=claim_id)
        if len(existing_channels) != 1:
            raise Exception(
                f"Can't find the channel '{claim_id}' in account '{account_id}'."
            )
        old_txo = existing_channels[0]
        if not old_txo.claim.is_channel:
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
            old_txo, claim, amount, claim_address, [account], account
        )
        new_txo = tx.outputs[0]

        if new_signing_key:
            new_txo.generate_channel_private_key()
        else:
            new_txo.private_key = old_txo.private_key

        new_txo.script.generate()

        if not preview:
            await tx.sign([account])
            await account.ledger.broadcast(tx)
            account.add_channel_private_key(new_txo.private_key)
            self.default_wallet.save()
            await self.storage.save_claims([self._old_get_temp_claim_info(
                tx, new_txo, claim_address, new_txo.claim, new_txo.claim_name, dewies_to_lbc(amount)
            )])
            await self.analytics_manager.send_new_channel()
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    async def jsonrpc_channel_abandon(
            self, claim_id=None, txid=None, nout=None, account_id=None,
            preview=False, blocking=True):
        """
        Abandon one of my channel claims.

        Usage:
            channel_abandon [<claim_id> | --claim_id=<claim_id>]
                            [<txid> | --txid=<txid>] [<nout> | --nout=<nout>]
                            [--account_id=<account_id>]
                            [--preview] [--blocking]

        Options:
            --claim_id=<claim_id>     : (str) claim_id of the claim to abandon
            --txid=<txid>             : (str) txid of the claim to abandon
            --nout=<nout>             : (int) nout of the claim to abandon
            --account_id=<account_id> : (str) id of the account to use
            --preview                 : (bool) do not broadcast the transaction
            --blocking                : (bool) wait until abandon is in mempool

        Returns: {Transaction}
        """
        account = self.get_account_or_default(account_id)

        if txid is not None and nout is not None:
            claims = await account.get_claims(**{'txo.txid': txid, 'txo.position': nout})
        elif claim_id is not None:
            claims = await account.get_claims(claim_id=claim_id)
        else:
            raise Exception('Must specify claim_id, or txid and nout')

        if not claims:
            raise Exception('No claim found for the specified claim_id or txid:nout')

        tx = await Transaction.create(
            [Input.spend(txo) for txo in claims], [], [account], account
        )

        if not preview:
            await account.ledger.broadcast(tx)
            await self.analytics_manager.send_claim_action('abandon')
            if blocking:
                await account.ledger.wait(tx)
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT)
    def jsonrpc_channel_list(self, account_id=None, page=None, page_size=None):
        """
        List my channel claims.

        Usage:
            channel_list [<account_id> | --account_id=<account_id>]
                         [--page=<page>] [--page_size=<page_size>]

        Options:
            --account_id=<account_id>  : (str) id of the account to use
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination

        Returns: {Paginated[Output]}
        """
        account = self.get_account_or_default(account_id)
        return maybe_paginate(
            account.get_channels,
            account.get_channel_count,
            page, page_size
        )

    @requires(WALLET_COMPONENT)
    async def jsonrpc_channel_export(self, channel_id=None, channel_name=None, account_id=None):
        """
        Export channel private key.

        Usage:
            channel_export (<channel_id> | --channel_id=<channel_id> | --channel_name=<channel_name>)
                           [--account_id=<account_id>...]

        Options:
            --channel_id=<channel_id>     : (str) claim id of channel to export
            --channel_name=<channel_name> : (str) name of channel to export
            --account_id=<account_id>     : (str) one or more account ids for accounts
                                                  to look in for channels, defaults to
                                                  all accounts.

        Returns:
            (str) serialized channel private key
        """
        channel = await self.get_channel_or_error(account_id, channel_id, channel_name, for_signing=True)
        address = channel.get_address(self.ledger)
        public_key = await self.ledger.get_public_key_for_address(channel.get_address(self.ledger))
        if not public_key:
            raise Exception("Can't find public key for address holding the channel.")
        export = {
            'name': channel.claim_name,
            'channel_id': channel.claim_id,
            'holding_address': address,
            'holding_public_key': public_key.extended_key_string(),
            'signing_private_key': channel.private_key.to_pem().decode()
        }
        return base58.b58encode(json.dumps(export, separators=(',', ':')))

    @requires(WALLET_COMPONENT)
    async def jsonrpc_channel_import(self, channel_data):
        """
        Import serialized channel private key (to allow signing new streams to the channel)

        Usage:
            channel_import (<channel_data> | --channel_data=<channel_data>)

        Options:
            --channel_data=<channel_data> : (str) serialized channel, as exported by channel export

        Returns:
            (dict) Result dictionary
        """
        decoded = base58.b58decode(channel_data)
        data = json.loads(decoded)
        channel_private_key = ecdsa.SigningKey.from_pem(
            data['signing_private_key'], hashfunc=hashlib.sha256
        )
        account: LBCAccount = await self.ledger.get_account_for_address(data['holding_address'])
        if not account:
            account = LBCAccount.from_dict(self.ledger, self.default_wallet, {
                'name': f"Holding Account For Channel {data['name']}",
                'public_key': data['holding_public_key'],
                'address_generator': {'name': 'single-address'}
            })
            if self.ledger.network.is_connected:
                await self.ledger.subscribe_account(account)
        account.add_channel_private_key(channel_private_key)
        self.default_wallet.save()
        return f"Added channel signing key for {data['name']}."

    STREAM_DOC = """
    Create, update, abandon, list and inspect your stream claims.
    """

    @requires(WALLET_COMPONENT, STREAM_MANAGER_COMPONENT, BLOB_COMPONENT, DATABASE_COMPONENT,
              conditions=[WALLET_IS_UNLOCKED])
    async def jsonrpc_publish(self, name, **kwargs):
        """
        Create or replace a stream claim at a given name (use 'stream create/update' for more control).

        Usage:
            publish (<name> | --name=<name>) [--bid=<bid>] [--file_path=<file_path>]
                    [--fee_currency=<fee_currency>] [--fee_amount=<fee_amount>] [--fee_address=<fee_address>]
                    [--title=<title>] [--description=<description>] [--author=<author>]
                    [--tags=<tags>...] [--languages=<languages>...] [--locations=<locations>...]
                    [--license=<license>] [--license_url=<license_url>] [--thumbnail_url=<thumbnail_url>]
                    [--release_time=<release_time>] [--width=<width>] [--height=<height>] [--duration=<duration>]
                    [--channel_id=<channel_id> | --channel_name=<channel_name>]
                    [--channel_account_id=<channel_account_id>...]
                    [--account_id=<account_id>] [--claim_address=<claim_address>] [--preview]

        Options:
            --name=<name>                  : (str) name of the content (can only consist of a-z A-Z 0-9 and -(dash))
            --bid=<bid>                    : (decimal) amount to back the claim
            --file_path=<file_path>        : (str) path to file to be associated with name.
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
            --channel_id=<channel_id>      : (str) claim id of the publisher channel
            --channel_name=<channel_name>  : (str) name of publisher channel
          --channel_account_id=<channel_id>: (str) one or more account ids for accounts to look in
                                                   for channel certificates, defaults to all accounts.
            --account_id=<account_id>      : (str) account to use for funding the transaction
            --claim_address=<claim_address>: (str) address where the claim is sent to, if not specified
                                                   it will be determined automatically from the account
            --preview                      : (bool) do not broadcast the transaction

        Returns: {Transaction}
        """
        log.info("publishing: name: %s params: %s", name, kwargs)
        self.valid_stream_name_or_error(name)
        account = self.get_account_or_default(kwargs.get('account_id'))
        claims = await account.get_claims(claim_name=name)
        if len(claims) == 0:
            if 'bid' not in kwargs:
                raise Exception("'bid' is a required argument for new publishes.")
            if 'file_path' not in kwargs:
                raise Exception("'file_path' is a required argument for new publishes.")
            return await self.jsonrpc_stream_create(name, **kwargs)
        elif len(claims) == 1:
            assert claims[0].claim.is_stream, f"Claim at name '{name}' is not a stream claim."
            return await self.jsonrpc_stream_update(claims[0].claim_id, replace=True, **kwargs)
        raise Exception(
            f"There are {len(claims)} claims for '{name}', please use 'stream update' command "
            f"to update a specific stream claim."
        )

    @requires(WALLET_COMPONENT, STREAM_MANAGER_COMPONENT, BLOB_COMPONENT, DATABASE_COMPONENT,
              conditions=[WALLET_IS_UNLOCKED])
    async def jsonrpc_stream_create(
            self, name, bid, file_path, allow_duplicate_name=False,
            channel_id=None, channel_name=None, channel_account_id=None,
            account_id=None, claim_address=None, preview=False, **kwargs):
        """
        Make a new stream claim and announce the associated file to lbrynet.

        Usage:
            stream_create (<name> | --name=<name>) (<bid> | --bid=<bid>) (<file_path> | --file_path=<file_path>)
                    [--allow_duplicate_name=<allow_duplicate_name>]
                    [--fee_currency=<fee_currency>] [--fee_amount=<fee_amount>] [--fee_address=<fee_address>]
                    [--title=<title>] [--description=<description>] [--author=<author>]
                    [--tags=<tags>...] [--languages=<languages>...] [--locations=<locations>...]
                    [--license=<license>] [--license_url=<license_url>] [--thumbnail_url=<thumbnail_url>]
                    [--release_time=<release_time>] [--width=<width>] [--height=<height>] [--duration=<duration>]
                    [--channel_id=<channel_id> | --channel_name=<channel_name>]
                    [--channel_account_id=<channel_account_id>...]
                    [--account_id=<account_id>] [--claim_address=<claim_address>] [--preview]

        Options:
            --name=<name>                  : (str) name of the content (can only consist of a-z A-Z 0-9 and -(dash))
            --bid=<bid>                    : (decimal) amount to back the claim
            --file_path=<file_path>        : (str) path to file to be associated with name.
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
            --channel_id=<channel_id>      : (str) claim id of the publisher channel
            --channel_name=<channel_name>  : (str) name of the publisher channel
          --channel_account_id=<channel_id>: (str) one or more account ids for accounts to look in
                                                   for channel certificates, defaults to all accounts.
            --account_id=<account_id>      : (str) account to use for funding the transaction
            --claim_address=<claim_address>: (str) address where the claim is sent to, if not specified
                                                   it will be determined automatically from the account
            --preview                      : (bool) do not broadcast the transaction

        Returns: {Transaction}
        """
        self.valid_stream_name_or_error(name)
        account = self.get_account_or_default(account_id)
        channel = await self.get_channel_or_none(channel_account_id, channel_id, channel_name, for_signing=True)
        amount = self.get_dewies_or_error('bid', bid, positive_value=True)
        claim_address = await self.get_receiving_address(claim_address, account)
        kwargs['fee_address'] = self.get_fee_address(kwargs, claim_address)

        claims = await account.get_claims(claim_name=name)
        if len(claims) > 0:
            if not allow_duplicate_name:
                raise Exception(
                    f"You already have a stream claim published under the name '{name}'. "
                    f"Use --allow-duplicate-name flag to override."
                )

        claim = Claim()
        claim.stream.update(file_path=file_path, sd_hash='0'*96, **kwargs)
        tx = await Transaction.claim_create(
            name, claim, amount, claim_address, [account], account, channel
        )
        new_txo = tx.outputs[0]

        file_stream = None
        if not preview:
            file_stream = await self.stream_manager.create_stream(file_path)
            claim.stream.source.sd_hash = file_stream.sd_hash
            new_txo.script.generate()

        if channel:
            new_txo.sign(channel)
        await tx.sign([account])

        if not preview:
            await account.ledger.broadcast(tx)
            await self.storage.save_claims([self._old_get_temp_claim_info(
                tx, new_txo, claim_address, claim, name, dewies_to_lbc(amount)
            )])
            await self.storage.save_content_claim(file_stream.stream_hash, new_txo.id)
            await self.analytics_manager.send_claim_action('publish')
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT, STREAM_MANAGER_COMPONENT, BLOB_COMPONENT, DATABASE_COMPONENT,
              conditions=[WALLET_IS_UNLOCKED])
    async def jsonrpc_stream_update(
            self, claim_id, bid=None, file_path=None,
            channel_id=None, channel_name=None, channel_account_id=None, clear_channel=False,
            account_id=None, claim_address=None,
            preview=False, replace=False, **kwargs):
        """
        Update an existing stream claim and if a new file is provided announce it to lbrynet.

        Usage:
            stream_update (<claim_id> | --claim_id=<claim_id>) [--bid=<bid>] [--file_path=<file_path>]
                    [--file_name=<file_name>] [--file_size=<file_size>] [--file_hash=<file_hash>]
                    [--fee_currency=<fee_currency>] [--fee_amount=<fee_amount>]
                    [--fee_address=<fee_address>] [--clear_fee]
                    [--title=<title>] [--description=<description>] [--author=<author>]
                    [--tags=<tags>...] [--clear_tags]
                    [--languages=<languages>...] [--clear_languages]
                    [--locations=<locations>...] [--clear_locations]
                    [--license=<license>] [--license_url=<license_url>] [--thumbnail_url=<thumbnail_url>]
                    [--release_time=<release_time>] [--width=<width>] [--height=<height>] [--duration=<duration>]
                    [--channel_id=<channel_id> | --channel_name=<channel_name> | --clear_channel]
                    [--channel_account_id=<channel_account_id>...]
                    [--account_id=<account_id>] [--claim_address=<claim_address>]
                    [--preview] [--replace]

        Options:
            --claim_id=<claim_id>          : (str) id of the stream claim to update
            --bid=<bid>                    : (decimal) amount to back the claim
            --file_path=<file_path>        : (str) path to file to be associated with name.
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
            --channel_id=<channel_id>      : (str) claim id of the publisher channel
            --channel_name=<channel_name>  : (str) name of the publisher channel
            --clear_channel                : (bool) remove channel signature
          --channel_account_id=<channel_id>: (str) one or more account ids for accounts to look in
                                                   for channel certificates, defaults to all accounts.
            --account_id=<account_id>      : (str) account to use for funding the transaction
            --claim_address=<claim_address>: (str) address where the claim is sent to, if not specified
                                                   it will be determined automatically from the account
            --preview                      : (bool) do not broadcast the transaction
            --replace                      : (bool) instead of modifying specific values on
                                                    the stream, this will clear all existing values
                                                    and only save passed in values, useful for form
                                                    submissions where all values are always set

        Returns: {Transaction}
        """
        account = self.get_account_or_default(account_id)

        existing_claims = await account.get_claims(claim_id=claim_id)
        if len(existing_claims) != 1:
            raise Exception(
                f"Can't find the claim '{claim_id}' in account '{account.id}'."
            )
        old_txo = existing_claims[0]
        if not old_txo.claim.is_stream:
            raise Exception(
                f"A claim with id '{claim_id}' was found but it is not a stream claim."
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
            channel = await self.get_channel_or_error(channel_account_id, channel_id, channel_name, for_signing=True)
        elif old_txo.claim.is_signed and not clear_channel and not replace:
            channel = old_txo.channel

        if 'fee_address' in kwargs:
            self.valid_address_or_error(kwargs['fee_address'])

        if replace:
            claim = Claim()
            claim.stream.message.source.CopyFrom(
                old_txo.claim.stream.message.source
            )
            stream_type = old_txo.claim.stream.stream_type
            if stream_type:
                old_stream_type = getattr(old_txo.claim.stream.message, stream_type)
                new_stream_type = getattr(claim.stream.message, stream_type)
                new_stream_type.CopyFrom(old_stream_type)
            claim.stream.update(file_path=file_path, **kwargs)
        else:
            claim = Claim.from_bytes(old_txo.claim.to_bytes())
            claim.stream.update(file_path=file_path, **kwargs)
        tx = await Transaction.claim_update(
            old_txo, claim, amount, claim_address, [account], account, channel
        )
        new_txo = tx.outputs[0]

        stream_hash = None
        if not preview:
            old_stream_hash = await self.storage.get_stream_hash_for_sd_hash(old_txo.claim.stream.source.sd_hash)
            if file_path is not None:
                if old_stream_hash:
                    stream_to_delete = self.stream_manager.get_stream_by_stream_hash(old_stream_hash)
                    await self.stream_manager.delete_stream(stream_to_delete, delete_file=False)
                file_stream = await self.stream_manager.create_stream(file_path)
                new_txo.claim.stream.source.sd_hash = file_stream.sd_hash
                new_txo.script.generate()
                stream_hash = file_stream.stream_hash
            else:
                stream_hash = old_stream_hash

        if channel:
            new_txo.sign(channel)
        await tx.sign([account])

        if not preview:
            await account.ledger.broadcast(tx)
            await self.storage.save_claims([self._old_get_temp_claim_info(
                tx, new_txo, claim_address, new_txo.claim, new_txo.claim_name, dewies_to_lbc(amount)
            )])
            if stream_hash:
                await self.storage.save_content_claim(stream_hash, new_txo.id)
            await self.analytics_manager.send_claim_action('publish')
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    async def jsonrpc_stream_abandon(
            self, claim_id=None, txid=None, nout=None, account_id=None,
            preview=False, blocking=True):
        """
        Abandon one of my stream claims.

        Usage:
            stream_abandon [<claim_id> | --claim_id=<claim_id>]
                           [<txid> | --txid=<txid>] [<nout> | --nout=<nout>]
                           [--account_id=<account_id>]
                           [--preview] [--blocking]

        Options:
            --claim_id=<claim_id>     : (str) claim_id of the claim to abandon
            --txid=<txid>             : (str) txid of the claim to abandon
            --nout=<nout>             : (int) nout of the claim to abandon
            --account_id=<account_id> : (str) id of the account to use
            --preview                 : (bool) do not broadcast the transaction
            --blocking                : (bool) wait until abandon is in mempool

        Returns: {Transaction}
        """
        account = self.get_account_or_default(account_id)

        if txid is not None and nout is not None:
            claims = await account.get_claims(**{'txo.txid': txid, 'txo.position': nout})
        elif claim_id is not None:
            claims = await account.get_claims(claim_id=claim_id)
        else:
            raise Exception('Must specify claim_id, or txid and nout')

        if not claims:
            raise Exception('No claim found for the specified claim_id or txid:nout')

        tx = await Transaction.create(
            [Input.spend(txo) for txo in claims], [], [account], account
        )

        if not preview:
            await account.ledger.broadcast(tx)
            await self.analytics_manager.send_claim_action('abandon')
            if blocking:
                await account.ledger.wait(tx)
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT)
    def jsonrpc_stream_list(self, account_id=None, page=None, page_size=None):
        """
        List my stream claims.

        Usage:
            stream_list [<account_id> | --account_id=<account_id>]
                       [--page=<page>] [--page_size=<page_size>]

        Options:
            --account_id=<account_id> : (str) id of the account to query
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination

        Returns: {Paginated[Output]}
        """
        account = self.get_account_or_default(account_id)
        return maybe_paginate(
            account.get_streams,
            account.get_stream_count,
            page, page_size
        )

    @requires(WALLET_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT, BLOB_COMPONENT,
              DHT_COMPONENT, DATABASE_COMPONENT,
              conditions=[WALLET_IS_UNLOCKED])
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

    SUPPORT_DOC = """
    Create, list and abandon all types of supports.
    """

    @requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    async def jsonrpc_support_create(self, claim_id, amount, tip=False, account_id=None, preview=False):
        """
        Create a support or a tip for name claim.

        Usage:
            support_create (<claim_id> | --claim_id=<claim_id>) (<amount> | --amount=<amount>)
                           [--tip] [--account_id=<account_id>] [--preview]

        Options:
            --claim_id=<claim_id>     : (str) claim_id of the claim to support
            --amount=<amount>         : (decimal) amount of support
            --tip                     : (bool) send support to claim owner, default: false.
            --account_id=<account_id> : (str) id of the account to use
            --preview                 : (bool) do not broadcast the transaction

        Returns: {Transaction}
        """
        account = self.get_account_or_default(account_id)
        amount = self.get_dewies_or_error("amount", amount)
        claim = await self.ledger.get_claim_by_claim_id(claim_id)
        claim_address = claim.get_address(self.ledger)
        if not tip:
            claim_address = await account.receiving.get_or_create_usable_address()

        tx = await Transaction.support(
            claim.claim_name, claim_id, amount, claim_address, [account], account
        )

        if not preview:
            await tx.sign([account])
            await account.ledger.broadcast(tx)
            await self.storage.save_supports({claim_id: [{
                'txid': tx.id,
                'nout': tx.position,
                'address': claim_address,
                'claim_id': claim_id,
                'amount': dewies_to_lbc(amount)
            }]})
            await self.analytics_manager.send_claim_action('new_support')
        else:
            await account.ledger.release_tx(tx)

        return tx

    @requires(WALLET_COMPONENT)
    def jsonrpc_support_list(self, account_id=None, page=None, page_size=None):
        """
        List supports and tips in my control.

        Usage:
            support_list [<account_id> | --account_id=<account_id>]
                         [--page=<page>] [--page_size=<page_size>]

        Options:
            --account_id=<account_id> : (str) id of the account to query
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination

        Returns: {Paginated[Output]}
        """
        account = self.get_account_or_default(account_id)
        return maybe_paginate(
            account.get_supports,
            account.get_support_count,
            page, page_size
        )

    @requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    async def jsonrpc_support_abandon(
            self, claim_id=None, txid=None, nout=None, keep=None,
            account_id=None, preview=False, blocking=True):
        """
        Abandon supports, including tips, of a specific claim, optionally
        keeping some amount as supports.

        Usage:
            support_abandon [--claim_id=<claim_id>] [(--txid=<txid> --nout=<nout>)] [--keep=<keep>]
                            [--account_id=<account_id>] [--preview] [--blocking]

        Options:
            --claim_id=<claim_id>     : (str) claim_id of the claim to abandon
            --txid=<txid>             : (str) txid of the claim to abandon
            --nout=<nout>             : (int) nout of the claim to abandon
            --keep=<keep>             : (decimal) amount of lbc to keep as support
            --account_id=<account_id> : (str) id of the account to use
            --preview                 : (bool) do not broadcast the transaction
            --blocking                : (bool) wait until abandon is in mempool

        Returns: {Transaction}
        """
        account = self.get_account_or_default(account_id)

        if txid is not None and nout is not None:
            supports = await account.get_supports(**{'txo.txid': txid, 'txo.position': nout})
        elif claim_id is not None:
            supports = await account.get_supports(claim_id=claim_id)
        else:
            raise Exception('Must specify claim_id, or txid and nout')

        if not supports:
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
            [Input.spend(txo) for txo in supports], outputs, [account], account
        )

        if not preview:
            await account.ledger.broadcast(tx)
            await self.analytics_manager.send_claim_action('abandon')
            if blocking:
                await account.ledger.wait(tx)
        else:
            await account.ledger.release_tx(tx)

        return tx

    TRANSACTION_DOC = """
    Transaction management.
    """

    @requires(WALLET_COMPONENT)
    def jsonrpc_transaction_list(self, account_id=None, page=None, page_size=None):
        """
        List transactions belonging to wallet

        Usage:
            transaction_list [<account_id> | --account_id=<account_id>]
                             [--page=<page>] [--page_size=<page_size>]

        Options:
            --account_id=<account_id> : (str) id of the account to query
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
        account = self.get_account_or_default(account_id)
        return maybe_paginate(
            self.wallet_manager.get_history,
            self.ledger.db.get_transaction_count,
            page, page_size, account=account
        )

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

    UTXO_DOC = """
    Unspent transaction management.
    """

    @requires(WALLET_COMPONENT)
    def jsonrpc_utxo_list(self, account_id=None, page=None, page_size=None):
        """
        List unspent transaction outputs

        Usage:
            utxo_list [<account_id> | --account_id=<account_id>]
                      [--page=<page>] [--page_size=<page_size>]

        Options:
            --account_id=<account_id> : (str) id of the account to query
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination

        Returns: {Paginated[Output]}
        """
        account = self.get_account_or_default(account_id)
        return maybe_paginate(
            account.get_utxos,
            account.get_utxo_count,
            page, page_size
        )

    @requires(WALLET_COMPONENT)
    def jsonrpc_utxo_release(self, account_id=None):
        """
        When spending a UTXO it is locally locked to prevent double spends;
        occasionally this can result in a UTXO being locked which ultimately
        did not get spent (failed to broadcast, spend transaction was not
        accepted by blockchain node, etc). This command releases the lock
        on all UTXOs in your account.

        Usage:
            utxo_release [<account_id> | --account_id=<account_id>]

        Options:
            --account_id=<account_id> : (str) id of the account to query

        Returns:
            None
        """
        return self.get_account_or_default(account_id).release_all_outputs()

    BLOB_DOC = """
    Blob management.
    """

    @requires(WALLET_COMPONENT, DHT_COMPONENT, BLOB_COMPONENT,
              conditions=[WALLET_IS_UNLOCKED])
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
        streams = self.stream_manager.get_filtered_streams(sd_hash=blob_hash)
        if streams:
            await self.stream_manager.delete_stream(streams[0])
        else:
            await self.blob_manager.delete_blobs([blob_hash])
        return "Deleted %s" % blob_hash

    PEER_DOC = """
    DHT / Blob Exchange peer commands.
    """

    @requires(DHT_COMPONENT)
    async def jsonrpc_peer_list(self, blob_hash, search_bottom_out_limit=None):
        """
        Get peers for blob hash

        Usage:
            peer_list (<blob_hash> | --blob_hash=<blob_hash>)
            [<search_bottom_out_limit> | --search_bottom_out_limit=<search_bottom_out_limit>]

        Options:
            --blob_hash=<blob_hash>                                  : (str) find available peers for this blob hash
            --search_bottom_out_limit=<search_bottom_out_limit>      : (int) the number of search probes in a row
                                                                             that don't find any new peers
                                                                             before giving up and returning

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
        async for new_peers in self.dht_node.get_iterative_value_finder(unhexlify(blob_hash.encode()), max_results=1,
                                                                        bottom_out_limit=search_bottom_out_limit):
            peers.extend(new_peers)
        results = [
            {
                "node_id": hexlify(peer.node_id).decode(),
                "address": peer.address,
                "udp_port": peer.udp_port,
                "tcp_port": peer.tcp_port,
            }
            for peer in peers
        ]
        return results

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
                                finished=None, page_size=None, page=None):
        """
        Returns blob hashes. If not given filters, returns all blobs known by the blob manager

        Usage:
            blob_list [--needed] [--finished] [<uri> | --uri=<uri>]
                      [<stream_hash> | --stream_hash=<stream_hash>]
                      [<sd_hash> | --sd_hash=<sd_hash>]
                      [<page_size> | --page_size=<page_size>]
                      [<page> | --page=<page>]

        Options:
            --needed                     : (bool) only return needed blobs
            --finished                   : (bool) only return finished blobs
            --uri=<uri>                  : (str) filter blobs by stream in a uri
            --stream_hash=<stream_hash>  : (str) filter blobs by stream hash
            --sd_hash=<sd_hash>          : (str) filter blobs by sd hash
            --page_size=<page_size>      : (int) results page size
            --page=<page>                : (int) page of results to return

        Returns:
            (list) List of blob hashes
        """

        if uri or stream_hash or sd_hash:
            if uri:
                metadata = (await self.resolve(uri))[uri]
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
        page_size = page_size or len(blobs)
        page = page or 0
        start_index = page * page_size
        stop_index = start_index + page_size
        return blobs[start_index:stop_index]

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

    @requires(STREAM_MANAGER_COMPONENT)
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
            stream.upload_to_reflector(server, port)
            for stream in self.stream_manager.get_filtered_streams(**kwargs)
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
            peer = self.component_manager.peer_manager.get_kademlia_peer(unhexlify(node_id), address,
                                                                         udp_port=int(port))
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
            }
        """
        result = {
            'buckets': {}
        }

        for i in range(len(self.dht_node.protocol.routing_table.buckets)):
            result['buckets'][i] = []
            for peer in self.dht_node.protocol.routing_table.buckets[i].peers:
                host = {
                    "address": peer.address,
                    "udp_port": peer.udp_port,
                    "tcp_port": peer.tcp_port,
                    "node_id": hexlify(peer.node_id).decode(),
                }
                result['buckets'][i].append(host)

        result['node_id'] = hexlify(self.dht_node.protocol.node_id).decode()
        return result

    COMMENT_DOC = """
    Create and list comments.
    """

    @requires(WALLET_COMPONENT)
    async def jsonrpc_comment_list(self, claim_id, parent_comment_id=None, flat=False,
                                   page=1, page_size=None, max_replies_shown=5):
        """
        List comments associated with a claim.

        Usage:
            comment_list <claim_id> [--flat] [(--page=<page> --page_size=<page_size>)]
                         [--parent_comment_id=<parent_comment_id>]
                         [--max_replies_shown=<max_replies_shown>]

        Options:
            --flat  : (bool) Flag to indicate whether or not you want the
                                    replies to be flattened along with the rest of
                                    the comments attached to the claim. Off by default
            --parent_comment_id=<parent_comment_id>  : (int) The ID of an existing
                                                             comment to list replies from
            --max_replies_shown=<max_replies_shown>  : (int) For every comment that we pull replies from,
                                                             only retrieve up to this amount.
                                                             Note: This is not the same as page size.
            --page=<page>  : (int) The page you'd like to see in the comment list.
                             The first page is 1, second page is 2, and so on.
            --page_size=<page_size>  : (int) The amount of comments that you'd like to
                                       retrieve in one request

        Returns:
            (dict)  Dict containing the following schema:
            {
                "page":  (int) The page of comments as provided when limiting response to page_size.
                "page_size":  (int) Number of comments in the given page. -1 if page_size wasn't used
                "comments":  (list) Contains all the comments (as dicts) as provided by the specified parameters
            }
        """
        # Should be like this:
        # comment list [claim_id] [parent_comment_id] --flat --page=1 --page-size=10
        url = self.conf.comment_server
        # The server uses permanent URIs for keys; not claims.
        # This is temporary until we can get that functionality removed
        claim_info = (await self.jsonrpc_claim_search(claim_id=claim_id))
        if 'error' in claim_info:
            raise Exception(claim_info['error'])
        if claim_info["page"] == 0:
            return {'page': 1, 'page_size': 0, 'comments': []}
        claim_uri = claim_info["items"][0].permanent_url
        # These two cases need separation since getting replies requires a bit of magic
        # to reduce request count from O(n^2) to O(1)
        if parent_comment_id:
            # Since we don't directly get all the comment data at once,
            # we have to do a bit more work to get them
            comment_ids = await jsonrpc_post(url, 'get_comment_replies',
                                             comm_index=parent_comment_id, clean=False)
            comment_ids = comment_ids['result']
            if page_size is not None:
                comment_ids = comment_ids[page_size * (page - 1): page_size * page]
            # now we have to just batch request the reply comments
            comments_batch = [
                rpc_body('get_comment_data', index, comm_index=comment_id, better_keys=True)
                for index, comment_id in enumerate(comment_ids)
            ]
            del comment_ids
            comments = await jsonrpc_batch(url, comments_batch, clean=True)
        else:
            # Get the content of the top level comments
            comments = await jsonrpc_post(url, 'get_claim_comments', uri=claim_uri, better_keys=True)
            if page_size is not None:
                comments = comments[page_size * (page - 1): page_size * page]
        # By now comments should be a list containing comment dicts that are supposed to be
        # at the given height that was requested. The parent_id may or may not be present
        # in the dicts, as they may or may not be replies to comments at a higher level
        # However this is dependent purely on whether or not parent_comment_id is None or not
        reply_lists = await jsonrpc_batch(url, [
            rpc_body('get_comment_replies', index, comm_index=comment['comment_id'])
            for index, comment in enumerate(comments)
        ])
        response = {
            'page': page,
            'page_size': -1 if page_size is None else page_size,
            'comments': []
        }
        if flat:
            # If it's flat then we'll need to get the comments into an order such that
            # If an element e in the list has a non-null parent id, the element before it
            # is either also a reply with the same parent id, or has an id that equals e's parent id,
            # in which case it's the comment that is being replied to.
            # Otherwise, if it has a null parent id, then it is a top level comment.

            # To do this, we create a dict that maps the index of the comment in the array
            # to a list containing the comment IDs of the replies
            comment_replies = {resp['id']: resp['result'] for resp in reply_lists if 'result' in resp}

            # Next, we create a batch request for the actual data of all of the replies
            # the id in this batch request is going to be in the form 'X:Y'
            # where X is the index of the parent comment in `comments,
            # and Y is index of the reply's ID within the list X maps to in `comment_replies`
            full_replies_batch = [
                rpc_body('get_comment_data', f'{parent_idx}:{idx}', comm_index=reply_id, better_keys=True)
                for parent_idx, id_list in comment_replies.items()
                for idx, reply_id in enumerate(id_list[0:max_replies_shown])
            ]
            reply_dump = await jsonrpc_batch(url, full_replies_batch)
            del full_replies_batch
            # This neatly orders the response into a dict to aggregate the
            # full comments by the parent comment they're replying to
            #
            # WARNING: The following block is going to be saving the comment dict
            #   objects TO `comment_replies`. This means that the lists
            #   stored in `comments_replies` may not hold just comments, but
            #    the ids of the comments who weren't requested due to the
            #   maximum reply limit. They need to be either cleaned out or stored
            #   somewhere else

            for comment in reply_dump:
                parent_index, reply_index = comment['id'].split(':')
                parent_index, reply_index = int(parent_index), int(reply_index)
                comment_replies[parent_index][reply_index] = comment['result']

            for idx, parent_comment in enumerate(comments):
                if 'parent_id' not in parent_comment:
                    parent_comment['parent_id'] = None
                parent_comment['reply_count'] = len(comment_replies[idx])
                parent_comment['omitted'] = 0
                if len(comment_replies[idx]) > max_replies_shown:
                    parent_comment['omitted'] = len(comment_replies[idx]) - max_replies_shown

                response['comments'].append(parent_comment)
                response['comments'] += comment_replies[idx][0:max_replies_shown]
            response['page_size'] = page_size if page_size is not None else -1
            return response
        else:
            for id_list in reply_lists:
                comments[id_list['id']]['reply_count'] = len(id_list['result'])
                comments[id_list['id']]['omitted'] = len(id_list['result'])
            response['comments'] = comments
        del reply_lists
        return response

    @requires(WALLET_COMPONENT)
    async def jsonrpc_comment_create(self, claim_id: str, channel_id: str,
                                     message: str, parent_comment_id: int = None) -> dict:
        """
        Create and associate a comment with a claim using your channel identity.

        Usage:
            comment_create <claim_id> <channel_id> <message> [--parent_comment_id=<parent_comment_id>]

        Options:
            --parent_comment_id=<parent_comment_id>  : (int) The ID of a comment to make a response to

        Returns:
            (dict) Comment object if successfully made
        """
        if not 1 < len(message) <= 2000:
            raise Exception(f'Message length ({len(message)}) needs to be between 2 and 2000 chars')
        url = self.conf.comment_server
        if parent_comment_id is not None:
            comment_id = await jsonrpc_post(url, 'reply', parent_id=parent_comment_id,
                                            poster=channel_id, message=message)
        else:
            claim_data = await self.jsonrpc_claim_search(claim_id=claim_id)
            if 'error' not in claim_data and claim_data['total_pages'] == 1:
                uri = claim_data['items'][0].permanent_url
                comment_id = await jsonrpc_post(url, 'comment', uri=uri,
                                                poster=channel_id, message=message)
            else:
                raise Exception(f"permanent_url is not in the claim_data {claim_data}\n"
                                f"The given claim_id ({claim_id}) may be invalid")
        return await jsonrpc_post(url, 'get_comment_data', comm_index=comment_id, better_keys=True)

    def valid_address_or_error(self, address):
        try:
            assert self.ledger.is_valid_address(address)
        except:
            raise Exception(f"'{address}' is not a valid address")

    @staticmethod
    def valid_stream_name_or_error(name: str):
        try:
            if not name:
                raise Exception(
                    "Stream name cannot be blank."
                )
            parsed = URL.parse(name)
            if parsed.has_channel:
                raise Exception(
                    "Stream names cannot start with '@' symbol. This is reserved for channels claims."
                )
            if not parsed.has_stream or parsed.stream.name != name:
                raise Exception(
                    "Stream name has invalid characters."
                )
        except (TypeError, ValueError):
            raise Exception("Invalid stream name.")

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

    async def get_receiving_address(self, address: str, account: LBCAccount) -> str:
        if address is None:
            return await account.receiving.get_or_create_usable_address()
        self.valid_address_or_error(address)
        return address

    async def get_channel_or_none(self, account_ids: List[str], channel_id: str = None, channel_name: str = None,
                                  for_signing: bool = False) -> Output:
        if channel_id is not None or channel_name is not None:
            return await self.get_channel_or_error(account_ids, channel_id, channel_name, for_signing)

    async def get_channel_or_error(self, account_ids: List[str], channel_id: str = None, channel_name: str = None,
                                   for_signing: bool = False) -> Output:
        if channel_id:
            key, value = 'id', channel_id
        elif channel_name:
            key, value = 'name', channel_name
        else:
            raise ValueError("Couldn't find channel because a channel_id or channel_name was not provided.")
        for account in self.get_accounts_or_all(account_ids):
            channels = await account.get_channels(**{f'claim_{key}': value}, limit=1)
            if len(channels) == 1:
                if for_signing and channels[0].private_key is None:
                    raise Exception(f"Couldn't find private key for {key} '{value}'. ")
                return channels[0]
            elif len(channels) > 1:
                raise ValueError(
                    f"Multiple channels found with channel_{key} '{value}', "
                    f"pass a channel_id to narrow it down."
                )
        raise ValueError(f"Couldn't find channel with channel_{key} '{value}'.")

    def get_account_or_default(self, account_id: str, argument_name: str = "account", lbc_only=True) -> LBCAccount:
        if account_id is None:
            return self.default_account
        return self.get_account_or_error(account_id, argument_name, lbc_only)

    def get_accounts_or_all(self, account_ids: List[str]) -> List[LBCAccount]:
        return [
            self.get_account_or_error(account_id)
            for account_id in account_ids
        ] if account_ids else self.default_wallet.accounts

    def get_account_or_error(
            self, account_id: str, argument_name: str = "account", lbc_only=True) -> Optional[LBCAccount]:
        for account in self.default_wallet.accounts:
            if account.id == account_id:
                if lbc_only and not isinstance(account, LBCAccount):
                    raise ValueError(
                        "Found '{}', but it's an {} ledger account. "
                        "'{}' requires specifying an LBC ledger account."
                        .format(account_id, account.ledger.symbol, argument_name)
                    )
                return account
        raise ValueError(f"Couldn't find account: {account_id}.")

    @staticmethod
    def get_dewies_or_error(argument: str, lbc: str, positive_value=False):
        try:
            dewies = lbc_to_dewies(lbc)
            if positive_value and dewies <= 0:
                raise ValueError(f"'{argument}' value must be greater than 0.0")
            return dewies
        except ValueError as e:
            raise ValueError(f"Invalid value for '{argument}': {e.args[0]}")

    async def resolve(self, urls):
        results = await self.ledger.resolve(urls)
        if results:
            try:
                claims = self.stream_manager._convert_to_old_resolve_output(results)
                await self.storage.save_claims_for_resolve([
                    value for value in claims.values() if 'error' not in value
                ])
            except DecodeError:
                pass
        return results

    def _old_get_temp_claim_info(self, tx, txo, address, claim_dict, name, bid):
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


def loggly_time_string(dt):
    formatted_dt = dt.strftime("%Y-%m-%dT%H:%M:%S")
    milliseconds = str(round(dt.microsecond * (10.0 ** -5), 3))
    return quote(formatted_dt + milliseconds + "Z")


def get_loggly_query_string(installation_id):
    base_loggly_search_url = "https://lbry.loggly.com/search#"
    now = utils.now()
    yesterday = now - utils.timedelta(days=1)
    params = {
        'terms': 'json.installation_id:{}*'.format(installation_id[:SHORT_ID_LEN]),
        'from': loggly_time_string(yesterday),
        'to': loggly_time_string(now)
    }
    data = urlencode(params)
    return base_loggly_search_url + data
