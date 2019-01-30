import os
import asyncio
import logging
import json
import inspect
import typing
import aiohttp
import base58
from urllib.parse import urlencode, quote
from typing import Callable, Optional, List
from binascii import hexlify, unhexlify
from copy import deepcopy
from traceback import format_exc
from aiohttp import web
from functools import wraps
from torba.client.baseaccount import SingleKey, HierarchicalDeterministic

from lbrynet import __version__, utils
from lbrynet.conf import Config, Setting, SLACK_WEBHOOK
from lbrynet.blob.blob_file import is_valid_blobhash
from lbrynet.blob_exchange.downloader import download_blob
from lbrynet.error import InsufficientFundsError, DownloadSDTimeout, ComponentsNotStarted
from lbrynet.error import NullFundsError, NegativeFundsError, ResolveError, ComponentStartConditionNotMet
from lbrynet.extras import system_info
from lbrynet.extras.daemon import analytics
from lbrynet.extras.daemon.Components import WALLET_COMPONENT, DATABASE_COMPONENT, DHT_COMPONENT, BLOB_COMPONENT
from lbrynet.extras.daemon.Components import STREAM_MANAGER_COMPONENT
from lbrynet.extras.daemon.Components import EXCHANGE_RATE_MANAGER_COMPONENT, UPNP_COMPONENT
from lbrynet.extras.daemon.ComponentManager import RequiredCondition
from lbrynet.extras.daemon.ComponentManager import ComponentManager
from lbrynet.extras.daemon.json_response_encoder import JSONResponseEncoder
from lbrynet.extras.daemon.undecorated import undecorated
from lbrynet.extras.wallet.account import Account as LBCAccount
from lbrynet.extras.wallet.dewies import dewies_to_lbc, lbc_to_dewies
from lbrynet.schema.claim import ClaimDict
from lbrynet.schema.uri import parse_lbry_uri
from lbrynet.schema.error import URIParseError, DecodeError
from lbrynet.schema.validator import validate_claim_id
from lbrynet.schema.address import decode_address

if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.dht.node import Node
    from lbrynet.extras.daemon.Components import UPnPComponent
    from lbrynet.extras.wallet import LbryWalletManager
    from lbrynet.extras.daemon.exchange_rate_manager import ExchangeRateManager
    from lbrynet.extras.daemon.storage import SQLiteStorage
    from lbrynet.stream.stream_manager import StreamManager

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


async def maybe_paginate(get_records: Callable, get_record_count: Callable,
                         page: Optional[int], page_size: Optional[int], **constraints):
    if None not in (page, page_size):
        constraints.update({
            "offset": page_size * (page-1),
            "limit": page_size
        })
        return {
            "items": await get_records(**constraints),
            "total_pages": int(((await get_record_count(**constraints)) + (page_size-1)) / page_size),
            "page": page, "page_size": page_size
        }
    return await get_records(**constraints)


def sort_claim_results(claims):
    claims.sort(key=lambda d: (d['height'], d['name'], d['claim_id'], d['txid'], d['nout']))
    return claims


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
            trace_lines = traceback.split("\n")
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
        self.analytics_manager = analytics.Manager(conf, self.installation_id, self.session_id)
        self.component_manager = component_manager or ComponentManager(
            conf, analytics_manager=self.analytics_manager,
            skip_components=conf.components_to_skip or []
        )
        self.component_startup_task = None

        logging.getLogger('aiohttp.access').setLevel(logging.WARN)
        app = web.Application()
        app.router.add_get('/lbryapi', self.handle_old_jsonrpc)
        app.router.add_post('/lbryapi', self.handle_old_jsonrpc)
        app.router.add_post('/', self.handle_old_jsonrpc)
        self.runner = web.AppRunner(app)

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
    def blob_manager(self) -> typing.Optional['BlobFileManager']:
        return self.component_manager.get_component(BLOB_COMPONENT)

    @property
    def upnp(self) -> typing.Optional['UPnPComponent']:
        return self.component_manager.get_component(UPNP_COMPONENT)

    @classmethod
    def get_api_definitions(cls):
        prefix = 'jsonrpc_'
        not_grouped = ['block_show', 'report_bug', 'routing_table_get']
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

    async def start(self):
        log.info("Starting LBRYNet Daemon")
        log.debug("Settings: %s", json.dumps(self.conf.settings_dict, indent=2))
        log.info("Platform: %s", json.dumps(system_info.get_platform(), indent=2))
        await self.analytics_manager.send_server_startup()
        await self.runner.setup()

        try:
            site = web.TCPSite(self.runner, self.conf.api_host, self.conf.api_port)
            await site.start()
            log.info('lbrynet API listening on TCP %s:%i', *site._server.sockets[0].getsockname()[:2])
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
            self.analytics_manager.start()
        self.component_startup_task = asyncio.create_task(self.component_manager.start())
        await self.component_startup_task

    async def stop(self):
        if self.component_startup_task is not None:
            if self.component_startup_task.done():
                await self.component_manager.stop()
            else:
                self.component_startup_task.cancel()
        await self.runner.cleanup()
        if self.analytics_manager.is_started:
            self.analytics_manager.stop()

    async def handle_old_jsonrpc(self, request):
        data = await request.json()
        result = await self._process_rpc_call(data)
        ledger = None
        if 'wallet' in self.component_manager.get_components_status():
            # self.ledger only available if wallet component is not skipped
            ledger = self.ledger
        return web.Response(
            text=jsonrpc_dumps_pretty(result, ledger=ledger),
            content_type='application/json'
        )

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
    def default_account(self):
        try:
            return self.wallet_manager.default_account
        except AttributeError:
            return None

    @property
    def ledger(self):
        try:
            return self.wallet_manager.default_account.ledger
        except AttributeError:
            return None

    async def get_est_cost_from_uri(self, uri: str) -> typing.Optional[float]:
        """
        Resolve a name and return the estimated stream cost
        """

        resolved = await self.wallet_manager.resolve(uri)
        if resolved:
            claim_response = resolved[uri]
        else:
            claim_response = None

        if claim_response and 'claim' in claim_response:
            if 'value' in claim_response['claim'] and claim_response['claim']['value'] is not None:
                claim_value = ClaimDict.load_dict(claim_response['claim']['value'])
                if not claim_value.has_fee:
                    return 0.0
                return round(
                    self.exchange_rate_manager.convert_currency(
                        claim_value.source_fee.currency, "LBC", claim_value.source_fee.amount
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
                    'database': (bool),
                    'wallet': (bool),
                    'session': (bool),
                    'dht': (bool),
                    'hash_announcer': (bool),
                    'stream_identifier': (bool),
                    'file_manager': (bool),
                    'blob_manager': (bool),
                    'blockchain_headers': (bool),
                    'peer_protocol_server': (bool),
                    'reflector': (bool),
                    'upnp': (bool),
                    'exchange_rate_manager': (bool),
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
                'file_manager': {
                    'managed_files': (int) count of files in the file manager,
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

        connection_code = CONNECTION_STATUS_NETWORK
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

    async def jsonrpc_report_bug(self, message=None):
        """
        Report a bug to slack

        Usage:
            report_bug (<message> | --message=<message>)

        Options:
            --message=<message> : (str) Description of the bug

        Returns:
            (bool) true if successful
        """

        platform_name = system_info.get_platform()['platform']
        webhook = utils.deobfuscate(SLACK_WEBHOOK)
        payload = json.dumps({
            "text": f"os: {platform_name}\n"
                    f" version: {__version__}\n"
                    f"<{get_loggly_query_string(self.installation_id)}|loggly>\n"
                    f"{message}"
        })
        async with aiohttp.request('post', webhook, data=payload):
            pass
        return True

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
            settings_set <key> <value>

        Returns:
            (dict) Updated dictionary of daemon settings
        """
        with self.conf.update_config() as c:
            attr: Setting = getattr(type(c), key)
            cleaned = attr.deserialize(value)
            setattr(c, key, cleaned)
        return {key: cleaned}

    WALLET_DOC = """
    Wallet management.
    """

    @deprecated("account_balance")
    def jsonrpc_wallet_balance(self, address=None):
        """ deprecated """

    @requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    async def jsonrpc_wallet_send(self, amount, address=None, claim_id=None, account_id=None):
        """
        Send credits. If given an address, send credits to it. If given a claim id, send a tip
        to the owner of a claim specified by uri. A tip is a claim support where the recipient
        of the support is the claim address for the claim being supported.

        Usage:
            wallet_send (<amount> | --amount=<amount>)
                        ((<address> | --address=<address>) | (<claim_id> | --claim_id=<claim_id>))
                        [--account_id=<account_id>]

        Options:
            --amount=<amount>          : (decimal) amount of credit to send
            --address=<address>        : (str) address to send credits to
            --claim_id=<claim_id>      : (str) claim_id of the claim to send to tip to
            --account_id=<account_id>  : (str) account to fund the transaction

        Returns:
            If sending to an address:
            (dict) Dictionary containing the transaction information
            {
                "hex": (str) raw transaction,
                "inputs": (list) inputs(dict) used for the transaction,
                "outputs": (list) outputs(dict) for the transaction,
                "total_fee": (int) fee in dewies,
                "total_input": (int) total of inputs in dewies,
                "total_output": (int) total of outputs in dewies(input - fees),
                "txid": (str) txid of the transaction,
            }

            If sending a claim tip:
            (dict) Dictionary containing the result of the support
            {
                txid : (str) txid of resulting support claim
                nout : (int) nout of the resulting support claim
                fee : (float) fee paid for the transaction
            }
        """

        amount = self.get_dewies_or_error("amount", amount)
        if not amount:
            raise NullFundsError
        elif amount < 0:
            raise NegativeFundsError()

        if address and claim_id:
            raise Exception("Given both an address and a claim id")
        elif not address and not claim_id:
            raise Exception("Not given an address or a claim id")

        if address:
            # raises an error if the address is invalid
            decode_address(address)

            reserved_points = self.wallet_manager.reserve_points(address, amount)
            if reserved_points is None:
                raise InsufficientFundsError()
            account = self.get_account_or_default(account_id)
            result = await self.wallet_manager.send_points_to_address(reserved_points, amount, account)
            await self.analytics_manager.send_credits_sent()
        else:
            log.info("This command is deprecated for sending tips, please use the newer claim_tip command")
            result = await self.jsonrpc_claim_tip(claim_id=claim_id, amount=amount, account_id=account_id)
        return result

    ACCOUNT_DOC = """
    Account management.
    """

    @requires("wallet")
    def jsonrpc_account_list(self, account_id=None, confirmations=6,
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

        Returns:
            (map) balance of account(s)
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

        Returns:
            (map) added account details

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

        result = account.to_dict()
        result['id'] = account.id
        result['status'] = 'added'
        result.pop('certificates', None)
        result['is_default'] = self.default_wallet.accounts[0] == account
        return result

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

        Returns:
            (map) new account details

        """
        account = LBCAccount.generate(
            self.ledger, self.default_wallet, account_name, {
                'name': SingleKey.name if single_key else HierarchicalDeterministic.name
            }
        )

        if self.ledger.network.is_connected:
            await self.ledger.subscribe_account(account)

        self.default_wallet.save()

        result = account.to_dict()
        result['id'] = account.id
        result['status'] = 'created'
        result.pop('certificates', None)
        result['is_default'] = self.default_wallet.accounts[0] == account
        return result

    @requires("wallet")
    def jsonrpc_account_remove(self, account_id):
        """
        Remove an existing account.

        Usage:
            account (<account_id> | --account_id=<account_id>)

        Options:
            --account_id=<account_id>  : (str) id of the account to remove

        Returns:
            (map) details of removed account

        """
        account = self.get_account_or_error(account_id)
        self.default_wallet.accounts.remove(account)
        self.default_wallet.save()
        result = account.to_dict()
        result['id'] = account.id
        result['status'] = 'removed'
        result.pop('certificates', None)
        return result

    @requires("wallet")
    def jsonrpc_account_set(
            self, account_id, default=False, new_name=None,
            change_gap=None, change_max_uses=None, receiving_gap=None, receiving_max_uses=None):
        """
        Change various settings on an account.

        Usage:
            account (<account_id> | --account_id=<account_id>)
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

        Returns:
            (map) updated account details

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
            self.default_wallet.save()

        result = account.to_dict()
        result['id'] = account.id
        result.pop('certificates', None)
        result['is_default'] = self.default_wallet.accounts[0] == account
        return result

    @requires(WALLET_COMPONENT)
    def jsonrpc_account_unlock(self, password, account_id=None):
        """
        Unlock an encrypted account

        Usage:
            account_unlock (<password> | --password=<password>) [<account_id> | --account_id=<account_id>]

        Options:
            --account_id=<account_id>        : (str) id for the account to unlock

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
            wallet_encrypt (<new_password> | --new_password=<new_password>) [<account_id> | --account_id=<account_id>]

        Options:
            --account_id=<account_id>        : (str) id for the account to encrypt

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

        Returns:
            (map) transaction performing requested action

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
    async def jsonrpc_account_send(self, amount, addresses, account_id=None, broadcast=False):
        """
        Send the same number of credits to multiple addresses.

        Usage:
            account_send <amount> <addresses>... [--account_id=<account_id>] [--broadcast]

        Options:
            --account_id=<account_id>  : (str) account to fund the transaction
            --broadcast                : (bool) actually broadcast the transaction, default: false.

        Returns:
        """

        amount = self.get_dewies_or_error("amount", amount)
        if not amount:
            raise NullFundsError
        elif amount < 0:
            raise NegativeFundsError()

        for address in addresses:
            decode_address(address)

        account = self.get_account_or_default(account_id)
        result = await account.send_to_addresses(amount, addresses, broadcast)
        await self.analytics_manager.send_credits_sent()
        return result

    ADDRESS_DOC = """
    Address management.
    """

    @requires(WALLET_COMPONENT)
    def jsonrpc_address_is_mine(self, address, account_id=None):
        """
        Checks if an address is associated with the current wallet.

        Usage:
            wallet_is_address_mine (<address> | --address=<address>)
                                   [<account_id> | --account_id=<account_id>]

        Options:
            --address=<address>       : (str) address to check
            --account_id=<account_id> : (str) id of the account to use

        Returns:
            (bool) true, if address is associated with current wallet
        """
        return self.wallet_manager.address_is_mine(
            address, self.get_account_or_default(account_id)
        )

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

        Returns:
            List of wallet addresses
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

        Returns:
            (str) Unused wallet address in base58
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
                      [--claim_name=<claim_name>] [--sort=<sort_by>] [--reverse] [--comparison=<comparison>]
                      [--full_status=<full_status>]

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
            --channel_name=<channel_name>  : (str) get file with matching channel name
            --claim_name=<claim_name>              : (str) get file with matching claim name
            --sort=<sort_method>                   : (str) sort by any property, like 'file_name'
                                                     or 'metadata.author'; to specify direction
                                                     append ',asc' or ',desc'

        Returns:
            (list) List of files

            [
                {
                    'completed': (bool) true if download is completed,
                    'file_name': (str) name of file,
                    'download_directory': (str) download directory,
                    'points_paid': (float) credit paid to download file,
                    'stopped': (bool) true if download is stopped,
                    'stream_hash': (str) stream hash of file,
                    'stream_name': (str) stream name ,
                    'suggested_file_name': (str) suggested file name,
                    'sd_hash': (str) sd hash of file,
                    'download_path': (str) download path of file,
                    'mime_type': (str) mime type of file,
                    'key': (str) key attached to file,
                    'total_bytes': (int) file size in bytes,
                    'written_bytes': (int) written size in bytes,
                    'blobs_completed': (int) number of fully downloaded blobs,
                    'blobs_in_stream': (int) total blobs on stream,
                    'status': (str) downloader status
                    'claim_id': (str) None if claim is not found else the claim id,
                    'outpoint': (str) None if claim is not found else the tx and output,
                    'txid': (str) None if claim is not found else the transaction id,
                    'nout': (int) None if claim is not found else the transaction output index,
                    'metadata': (dict) None if claim is not found else the claim metadata,
                    'channel_claim_id': (str) None if claim is not found or not signed,
                    'channel_name': (str) None if claim is not found or not signed,
                    'claim_name': (str) None if claim is not found else the claim name
                },
            ]
        """
        sort = sort or 'status'
        comparison = comparison or 'eq'
        return [
            stream.as_dict() for stream in self.stream_manager.get_filtered_streams(
                sort, reverse, comparison, **kwargs
            )
        ]

    CLAIM_DOC = """
    Claim management.
    """

    @requires(WALLET_COMPONENT)
    async def jsonrpc_claim_show(self, txid=None, nout=None, claim_id=None):
        """
        Resolve claim info from txid/nout or with claim ID

        Usage:
            claim_show [<txid> | --txid=<txid>] [<nout> | --nout=<nout>]
                       [<claim_id> | --claim_id=<claim_id>]

        Options:
            --txid=<txid>              : (str) look for claim with this txid, nout must
                                         also be specified
            --nout=<nout>              : (int) look for claim with this nout, txid must
                                         also be specified
            --claim_id=<claim_id>  : (str) look for claim with this claim id

        Returns:
            (dict) Dictionary containing claim info as below,

            {
                'txid': (str) txid of claim
                'nout': (int) nout of claim
                'amount': (float) amount of claim
                'value': (str) value of claim
                'height' : (int) height of claim takeover
                'claim_id': (str) claim ID of claim
                'supports': (list) list of supports associated with claim
            }

            if claim cannot be resolved, dictionary as below will be returned

            {
                'error': (str) reason for error
            }

        """
        if claim_id is not None and txid is None and nout is None:
            claim_results = await self.wallet_manager.get_claim_by_claim_id(claim_id)
        elif txid is not None and nout is not None and claim_id is None:
            claim_results = await self.wallet_manager.get_claim_by_outpoint(txid, int(nout))
        else:
            raise Exception("Must specify either txid/nout, or claim_id")
        return claim_results

    @requires(WALLET_COMPONENT)
    async def jsonrpc_resolve(self, force=False, uri=None, uris=None):
        """
        Resolve given LBRY URIs

        Usage:
            resolve [--force] (<uri> | --uri=<uri>) [<uris>...]

        Options:
            --force  : (bool) force refresh and ignore cache
            --uri=<uri>    : (str) uri to resolve
            --uris=<uris>   : (list) uris to resolve

        Returns:
            Dictionary of results, keyed by uri
            '<uri>': {
                    If a resolution error occurs:
                    'error': Error message

                    If the uri resolves to a channel or a claim in a channel:
                    'certificate': {
                        'address': (str) claim address,
                        'amount': (float) claim amount,
                        'effective_amount': (float) claim amount including supports,
                        'claim_id': (str) claim id,
                        'claim_sequence': (int) claim sequence number,
                        'decoded_claim': (bool) whether or not the claim value was decoded,
                        'height': (int) claim height,
                        'depth': (int) claim depth,
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

                    If the uri resolves to a channel:
                    'claims_in_channel': (int) number of claims in the channel,

                    If the uri resolves to a claim:
                    'claim': {
                        'address': (str) claim address,
                        'amount': (float) claim amount,
                        'effective_amount': (float) claim amount including supports,
                        'claim_id': (str) claim id,
                        'claim_sequence': (int) claim sequence number,
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

        uris = tuple(uris or [])
        if uri is not None:
            uris += (uri,)

        results = {}

        valid_uris = tuple()
        for u in uris:
            try:
                parse_lbry_uri(u)
                valid_uris += (u,)
            except URIParseError:
                results[u] = {"error": "%s is not a valid uri" % u}

        resolved = await self.wallet_manager.resolve(*valid_uris, check_cache=not force)
        for resolved_uri in resolved:
            results[resolved_uri] = resolved[resolved_uri]
        return results

    @requires(WALLET_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT, BLOB_COMPONENT, DATABASE_COMPONENT,
              STREAM_MANAGER_COMPONENT,
              conditions=[WALLET_IS_UNLOCKED])
    async def jsonrpc_get(self, uri, file_name=None, timeout=None):
        """
        Download stream from a LBRY name.

        Usage:
            get <uri> [<file_name> | --file_name=<file_name>] [<timeout> | --timeout=<timeout>]


        Options:
            --uri=<uri>              : (str) uri of the content to download
            --file_name=<file_name>  : (str) specified name for the downloaded file
            --timeout=<timeout>      : (int) download timeout in number of seconds

        Returns:
            (dict) Dictionary containing information about the stream
            {
                'completed': (bool) true if download is completed,
                'file_name': (str) name of file,
                'download_directory': (str) download directory,
                'points_paid': (float) credit paid to download file,
                'stopped': (bool) true if download is stopped,
                'stream_hash': (str) stream hash of file,
                'stream_name': (str) stream name ,
                'suggested_file_name': (str) suggested file name,
                'sd_hash': (str) sd hash of file,
                'download_path': (str) download path of file,
                'mime_type': (str) mime type of file,
                'key': (str) key attached to file,
                'total_bytes': (int) file size in bytes,
                'written_bytes': (int) written size in bytes,
                'blobs_completed': (int) number of fully downloaded blobs,
                'blobs_in_stream': (int) total blobs on stream,
                'status': (str) downloader status,
                'claim_id': (str) claim id,
                'outpoint': (str) claim outpoint string,
                'txid': (str) claim txid,
                'nout': (int) claim nout,
                'metadata': (dict) claim metadata,
                'channel_claim_id': (str) None if claim is not signed
                'channel_name': (str) None if claim is not signed
                'claim_name': (str) claim name
            }
        """

        parsed_uri = parse_lbry_uri(uri)
        if parsed_uri.is_channel:
            raise Exception("cannot download a channel claim, specify a /path")

        resolved = (await self.wallet_manager.resolve(uri)).get(uri, {})
        resolved = resolved if 'value' in resolved else resolved.get('claim')

        if not resolved:
            raise ResolveError(
                "Failed to resolve stream at lbry://{}".format(uri.replace("lbry://", ""))
            )
        if 'error' in resolved:
            raise ResolveError(f"error resolving stream: {resolved['error']}")

        claim = ClaimDict.load_dict(resolved['value'])
        fee_amount, fee_address = None, None
        if claim.has_fee:
            fee_amount = round(self.exchange_rate_manager.convert_currency(
                    claim.source_fee.currency, "LBC", claim.source_fee.amount
                ), 5)
            fee_address = claim.source_fee.address
        outpoint = f"{resolved['txid']}:{resolved['nout']}"
        existing = self.stream_manager.get_filtered_streams(outpoint=outpoint)
        if not existing:
            existing.extend(self.stream_manager.get_filtered_streams(claim_id=resolved['claim_id'],
                                                                     sd_hash=claim.source_hash))
        if existing:
            log.info("already have matching stream for %s", uri)
            stream = existing[0]
        else:
            stream = await self.stream_manager.download_stream_from_claim(
                self.dht_node, resolved, file_name, timeout, fee_amount, fee_address
            )
        if stream:
            return stream.as_dict()
        raise DownloadSDTimeout(resolved['value']['stream']['source']['source'])

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
        if status == 'start' and not stream.running and not stream.finished:
            stream.downloader.download(self.dht_node)
            msg = "Resumed download"
        elif status == 'stop' and stream.running:
            await stream.stop_download()
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
                await self.stream_manager.delete_stream(stream, delete_file=delete_from_download_dir)
                log.info("Deleted file: %s", stream.file_name)
            result = True
        return result

    STREAM_DOC = """
    Stream information.
    """

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

    CHANNEL_DOC = """
    Channel management.
    """

    @requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    async def jsonrpc_channel_new(self, channel_name, amount, account_id=None):
        """
        Generate a publisher key and create a new '@' prefixed certificate claim

        Usage:
            channel_new (<channel_name> | --channel_name=<channel_name>)
                        (<amount> | --amount=<amount>)
                        [--account_id=<account_id>]

        Options:
            --channel_name=<channel_name>    : (str) name of the channel prefixed with '@'
            --amount=<amount>                : (decimal) bid amount on the channel
            --account_id=<account_id>        : (str) id of the account to store channel

        Returns:
            (dict) Dictionary containing result of the claim
            {
                'tx' : (str) hex encoded transaction
                'txid' : (str) txid of resulting claim
                'nout' : (int) nout of the resulting claim
                'fee' : (float) fee paid for the claim transaction
                'claim_id' : (str) claim ID of the resulting claim
            }
        """
        try:
            parsed = parse_lbry_uri(channel_name)
            if not parsed.contains_channel:
                raise Exception("Cannot make a new channel for a non channel name")
            if parsed.path:
                raise Exception("Invalid channel uri")
        except (TypeError, URIParseError):
            raise Exception("Invalid channel name")

        amount = self.get_dewies_or_error("amount", amount)
        if amount <= 0:
            raise Exception("Invalid amount")

        tx = await self.wallet_manager.claim_new_channel(
            channel_name, amount, self.get_account_or_default(account_id)
        )
        self.default_wallet.save()
        await self.analytics_manager.send_new_channel()
        nout = 0
        txo = tx.outputs[nout]
        log.info("Claimed a new channel! lbry://%s txid: %s nout: %d", channel_name, tx.id, nout)
        return {
            "success": True,
            "tx": tx,
            "claim_id": txo.claim_id,
            "claim_address": txo.get_address(self.ledger),
            "output": txo
        }

    @requires(WALLET_COMPONENT)
    def jsonrpc_channel_list(self, account_id=None, page=None, page_size=None):
        """
        Get certificate claim infos for channels that can be published to

        Usage:
            channel_list [<account_id> | --account_id=<account_id>]
                         [--page=<page>] [--page_size=<page_size>]

        Options:
            --account_id=<account_id>  : (str) id of the account to use
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination

        Returns:
            (list) ClaimDict, includes 'is_mine' field to indicate if the certificate claim
            is in the wallet.
        """
        account = self.get_account_or_default(account_id)
        return maybe_paginate(
            account.get_channels,
            account.get_channel_count,
            page, page_size
        )

    @requires(WALLET_COMPONENT)
    async def jsonrpc_channel_export(self, claim_id):
        """
        Export serialized channel signing information for a given certificate claim id

        Usage:
            channel_export (<claim_id> | --claim_id=<claim_id>)

        Options:
            --claim_id=<claim_id> : (str) Claim ID to export information about

        Returns:
            (str) Serialized certificate information
        """

        return await self.wallet_manager.export_certificate_info(claim_id)

    @requires(WALLET_COMPONENT)
    async def jsonrpc_channel_import(self, serialized_certificate_info):
        """
        Import serialized channel signing information (to allow signing new claims to the channel)

        Usage:
            channel_import (<serialized_certificate_info> | --serialized_certificate_info=<serialized_certificate_info>)

        Options:
            --serialized_certificate_info=<serialized_certificate_info> : (str) certificate info

        Returns:
            (dict) Result dictionary
        """

        return await self.wallet_manager.import_certificate_info(serialized_certificate_info)

    @requires(WALLET_COMPONENT, STREAM_MANAGER_COMPONENT, BLOB_COMPONENT, DATABASE_COMPONENT,
              conditions=[WALLET_IS_UNLOCKED])
    async def jsonrpc_publish(
            self, name, bid, metadata=None, file_path=None, fee=None, title=None,
            description=None, author=None, language=None, license=None,
            license_url=None, thumbnail=None, preview=None, nsfw=None, sources=None,
            channel_name=None, channel_id=None, channel_account_id=None, account_id=None,
            claim_address=None, change_address=None):
        """
        Make a new name claim and publish associated data to lbrynet,
        update over existing claim if user already has a claim for name.

        Fields required in the final Metadata are:
            'title'
            'description'
            'author'
            'language'
            'license'
            'nsfw'

        Metadata can be set by either using the metadata argument or by setting individual arguments
        fee, title, description, author, language, license, license_url, thumbnail, preview, nsfw,
        or sources. Individual arguments will overwrite the fields specified in metadata argument.

        Usage:
            publish (<name> | --name=<name>) (<bid> | --bid=<bid>) [--metadata=<metadata>]
                    [--file_path=<file_path>] [--fee=<fee>] [--title=<title>]
                    [--description=<description>] [--author=<author>] [--language=<language>]
                    [--license=<license>] [--license_url=<license_url>] [--thumbnail=<thumbnail>]
                    [--preview=<preview>] [--nsfw=<nsfw>] [--sources=<sources>]
                    [--channel_name=<channel_name>] [--channel_id=<channel_id>]
                    [--channel_account_id=<channel_account_id>...] [--account_id=<account_id>]
                    [--claim_address=<claim_address>] [--change_address=<change_address>]

        Options:
            --name=<name>                  : (str) name of the content (can only consist of a-z A-Z 0-9 and -(dash))
            --bid=<bid>                    : (decimal) amount to back the claim
            --metadata=<metadata>          : (dict) ClaimDict to associate with the claim.
            --file_path=<file_path>        : (str) path to file to be associated with name. If provided,
                                             a lbry stream of this file will be used in 'sources'.
                                             If no path is given but a sources dict is provided,
                                             it will be used. If neither are provided, an
                                             error is raised.
            --fee=<fee>                    : (dict) Dictionary representing key fee to download content:
                                              {
                                                'currency': currency_symbol,
                                                'amount': decimal,
                                                'address': str, optional
                                              }
                                              supported currencies: LBC, USD, BTC
                                              If an address is not provided a new one will be
                                              automatically generated. Default fee is zero.
            --title=<title>                : (str) title of the publication
            --description=<description>    : (str) description of the publication
            --author=<author>              : (str) author of the publication. The usage for this field is not
                                             the same as for channels. The author field is used to credit an author
                                             who is not the publisher and is not represented by the channel. For
                                             example, a pdf file of 'The Odyssey' has an author of 'Homer' but may
                                             by published to a channel such as '@classics', or to no channel at all
            --language=<language>          : (str) language of the publication
            --license=<license>            : (str) publication license
            --license_url=<license_url>    : (str) publication license url
            --thumbnail=<thumbnail>        : (str) thumbnail url
            --preview=<preview>            : (str) preview url
            --nsfw=<nsfw>                  : (bool) whether the content is nsfw
            --sources=<sources>            : (str) {'lbry_sd_hash': sd_hash} specifies sd hash of file
            --channel_name=<channel_name>  : (str) name of the publisher channel name in the wallet
            --channel_id=<channel_id>      : (str) claim id of the publisher channel, does not check
                                             for channel claim being in the wallet. This allows
                                             publishing to a channel where only the certificate
                                             private key is in the wallet.
          --channel_account_id=<channel_id>: (str) one or more account ids for accounts to look in
                                             for channel certificates, defaults to all accounts.
                 --account_id=<account_id> : (str) account to use for funding the transaction
           --claim_address=<claim_address> : (str) address where the claim is sent to, if not specified
                                             new address will automatically be created

        Returns:
            (dict) Dictionary containing result of the claim
            {
                'tx' : (str) hex encoded transaction
                'txid' : (str) txid of resulting claim
                'nout' : (int) nout of the resulting claim
                'fee' : (decimal) fee paid for the claim transaction
                'claim_id' : (str) claim ID of the resulting claim
            }
        """

        try:
            parse_lbry_uri(name)
        except (TypeError, URIParseError):
            raise Exception("Invalid name given to publish")

        amount = self.get_dewies_or_error('bid', bid)
        if amount <= 0:
            raise ValueError("Bid value must be greater than 0.0")

        for address in [claim_address, change_address]:
            if address is not None:
                # raises an error if the address is invalid
                decode_address(address)

        account = self.get_account_or_default(account_id)

        available = await account.get_balance()
        existing_claims = []
        if amount >= available:
            existing_claims = await account.get_claims(claim_name=name)
            if len(existing_claims) == 1:
                available += existing_claims[0].get_estimator(self.ledger).effective_amount
            if amount >= available:
                raise InsufficientFundsError(
                    f"Please lower the bid value, the maximum amount "
                    f"you can specify for this claim is {dewies_to_lbc(available)}."
                )

        metadata = metadata or {}
        if fee is not None:
            metadata['fee'] = fee
        if title is not None:
            metadata['title'] = title
        if description is not None:
            metadata['description'] = description
        if author is not None:
            metadata['author'] = author
        if language is not None:
            metadata['language'] = language
        if license is not None:
            metadata['license'] = license
        if license_url is not None:
            metadata['licenseUrl'] = license_url
        if thumbnail is not None:
            metadata['thumbnail'] = thumbnail
        if preview is not None:
            metadata['preview'] = preview
        if nsfw is not None:
            metadata['nsfw'] = bool(nsfw)

        metadata['version'] = '_0_1_0'

        # check for original deprecated format {'currency':{'address','amount'}}
        # add address, version to fee if unspecified
        if 'fee' in metadata:
            if len(metadata['fee'].keys()) == 1 and isinstance(metadata['fee'].values()[0], dict):
                raise Exception('Old format for fee no longer supported. '
                                'Fee must be specified as {"currency":,"address":,"amount":}')

            if 'amount' in metadata['fee'] and 'currency' in metadata['fee']:
                if not metadata['fee']['amount']:
                    log.warning("Stripping empty fee from published metadata")
                    del metadata['fee']
                elif 'address' not in metadata['fee']:
                    address = await account.receiving.get_or_create_usable_address()
                    metadata['fee']['address'] = address
            if 'fee' in metadata and 'version' not in metadata['fee']:
                metadata['fee']['version'] = '_0_0_1'

        claim_dict = {
            'version': '_0_0_1',
            'claimType': 'streamType',
            'stream': {
                'metadata': metadata,
                'version': '_0_0_1'
            }
        }

        # this will be used to verify the format with lbrynet.schema
        claim_copy = deepcopy(claim_dict)
        if sources is not None:
            claim_dict['stream']['source'] = sources
            claim_copy['stream']['source'] = sources
        elif file_path is not None:
            if not os.path.isfile(file_path):
                raise Exception("invalid file path to publish")
            # since the file hasn't yet been made into a stream, we don't have
            # a valid Source for the claim when validating the format, we'll use a fake one
            claim_copy['stream']['source'] = {
                'version': '_0_0_1',
                'sourceType': 'lbry_sd_hash',
                'source': '0' * 96,
                'contentType': ''
            }
        else:
            # there is no existing source to use, and a file was not provided to make a new one
            raise Exception("no source provided to publish")
        try:
            ClaimDict.load_dict(claim_copy)
            # the metadata to use in the claim can be serialized by lbrynet.schema
        except DecodeError as err:
            # there was a problem with a metadata field, raise an error here rather than
            # waiting to find out when we go to publish the claim (after having made the stream)
            raise Exception(f"invalid publish metadata: {err}")

        certificate = None
        if channel_id or channel_name:
            certificate = await self.get_channel_or_error(
                self.get_accounts_or_all(channel_account_id), channel_id, channel_name
            )

        log.info("Publish: %s", {
            'name': name,
            'file_path': file_path,
            'bid': dewies_to_lbc(amount),
            'claim_address': claim_address,
            'change_address': change_address,
            'claim_dict': claim_dict,
            'channel_id': channel_id,
            'channel_name': channel_name
        })

        from lbrynet.extras.daemon.mime_types import guess_media_type

        if file_path:
            if not os.path.isfile(file_path):
                raise Exception(f"File {file_path} not found")
            if os.path.getsize(file_path) == 0:
                raise Exception(f"Cannot publish empty file {file_path}")
            claim_dict['stream']['source'] = {}

            stream = await self.stream_manager.create_stream(file_path)
            stream_hash = stream.stream_hash
            await self.storage.save_published_file(stream_hash, os.path.basename(file_path),
                                                   os.path.dirname(file_path), 0)
            claim_dict['stream']['source']['source'] = stream.sd_hash
            claim_dict['stream']['source']['sourceType'] = 'lbry_sd_hash'
            claim_dict['stream']['source']['contentType'] = guess_media_type(file_path)
            claim_dict['stream']['source']['version'] = "_0_0_1"  # need current version here
        else:
            if not ('source' not in claim_dict['stream'] and existing_claims):
                raise Exception("no previous stream to update")
            claim_dict['stream']['source'] = existing_claims[-1].claim_dict['stream']['source']
            stream_hash = await self.storage.get_stream_hash_for_sd_hash(claim_dict['stream']['source']['source'])
        tx = await self.wallet_manager.claim_name(
            account, name, amount, claim_dict, certificate, claim_address
        )
        await self.storage.save_content_claim(
            stream_hash, tx.outputs[0].id
        )
        await self.analytics_manager.send_claim_action('publish')
        nout = 0
        txo = tx.outputs[nout]
        log.info("Success! Published to lbry://%s txid: %s nout: %d", name, tx.id, nout)
        return {
            "success": True,
            "tx": tx,
            "claim_id": txo.claim_id,
            "claim_address": self.ledger.hash160_to_address(txo.script.values['pubkey_hash']),
            "output": tx.outputs[nout]
        }

    @requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    async def jsonrpc_claim_abandon(self, claim_id=None, txid=None, nout=None, account_id=None, blocking=True):
        """
        Abandon a name and reclaim credits from the claim

        Usage:
            claim_abandon [<claim_id> | --claim_id=<claim_id>]
                          [<txid> | --txid=<txid>] [<nout> | --nout=<nout>]
                          [--account_id=<account_id>]
                          [--blocking]

        Options:
            --claim_id=<claim_id>     : (str) claim_id of the claim to abandon
            --txid=<txid>             : (str) txid of the claim to abandon
            --nout=<nout>             : (int) nout of the claim to abandon
            --account_id=<account_id> : (str) id of the account to use
            --blocking                : (bool) wait until abandon is in mempool

        Returns:
            (dict) Dictionary containing result of the claim
            {
                success: (bool) True if txn is successful
                txid : (str) txid of resulting transaction
            }
        """
        account = self.get_account_or_default(account_id)

        if claim_id is None and txid is None and nout is None:
            raise Exception('Must specify claim_id, or txid and nout')
        if txid is None and nout is not None:
            raise Exception('Must specify txid')
        if nout is None and txid is not None:
            raise Exception('Must specify nout')

        tx = await self.wallet_manager.abandon_claim(claim_id, txid, nout, account)
        await self.analytics_manager.send_claim_action('abandon')
        if blocking:
            await self.ledger.wait(tx)
        return {"success": True, "tx": tx}

    @requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    async def jsonrpc_claim_new_support(self, name, claim_id, amount, account_id=None):
        """
        Support a name claim

        Usage:
            claim_new_support (<name> | --name=<name>) (<claim_id> | --claim_id=<claim_id>)
                              (<amount> | --amount=<amount>) [--account_id=<account_id>]

        Options:
            --name=<name>             : (str) name of the claim to support
            --claim_id=<claim_id>     : (str) claim_id of the claim to support
            --amount=<amount>         : (decimal) amount of support
            --account_id=<account_id> : (str) id of the account to use

        Returns:
            (dict) Dictionary containing the transaction information
            {
                "hex": (str) raw transaction,
                "inputs": (list) inputs(dict) used for the transaction,
                "outputs": (list) outputs(dict) for the transaction,
                "total_fee": (int) fee in dewies,
                "total_input": (int) total of inputs in dewies,
                "total_output": (int) total of outputs in dewies(input - fees),
                "txid": (str) txid of the transaction,
            }
        """
        account = self.get_account_or_default(account_id)
        amount = self.get_dewies_or_error("amount", amount)
        result = await self.wallet_manager.support_claim(name, claim_id, amount, account)
        await self.analytics_manager.send_claim_action('new_support')
        return result

    @requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    async def jsonrpc_claim_tip(self, claim_id, amount, account_id=None):
        """
        Tip the owner of the claim

        Usage:
            claim_tip (<claim_id> | --claim_id=<claim_id>) (<amount> | --amount=<amount>)
                      [--account_id=<account_id>]

        Options:
            --claim_id=<claim_id>     : (str) claim_id of the claim to support
            --amount=<amount>         : (decimal) amount of support
            --account_id=<account_id> : (str) id of the account to use

        Returns:
            (dict) Dictionary containing the transaction information
            {
                "hex": (str) raw transaction,
                "inputs": (list) inputs(dict) used for the transaction,
                "outputs": (list) outputs(dict) for the transaction,
                "total_fee": (int) fee in dewies,
                "total_input": (int) total of inputs in dewies,
                "total_output": (int) total of outputs in dewies(input - fees),
                "txid": (str) txid of the transaction,
            }
        """
        account = self.get_account_or_default(account_id)
        amount = self.get_dewies_or_error("amount", amount)
        validate_claim_id(claim_id)
        result = await self.wallet_manager.tip_claim(amount, claim_id, account)
        await self.analytics_manager.send_claim_action('new_support')
        return result

    @requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    def jsonrpc_claim_send_to_address(self, claim_id, address, amount=None):
        """
        Send a name claim to an address

        Usage:
            claim_send_to_address (<claim_id> | --claim_id=<claim_id>)
                                  (<address> | --address=<address>)
                                  [<amount> | --amount=<amount>]

        Options:
            --claim_id=<claim_id>   : (str) claim_id to send
            --address=<address>     : (str) address to send the claim to
            --amount=<amount>       : (int) Amount of credits to claim name for,
                                      defaults to the current amount on the claim

        Returns:
            (dict) Dictionary containing result of the claim
            {
                'tx' : (str) hex encoded transaction
                'txid' : (str) txid of resulting claim
                'nout' : (int) nout of the resulting claim
                'fee' : (float) fee paid for the claim transaction
                'claim_id' : (str) claim ID of the resulting claim
            }

        """
        decode_address(address)
        return self.wallet_manager.send_claim_to_address(
            claim_id, address, self.get_dewies_or_error("amount", amount) if amount else None
        )

    @requires(WALLET_COMPONENT)
    def jsonrpc_claim_list_mine(self, account_id=None, page=None, page_size=None):
        """
        List my name claims

        Usage:
            claim_list_mine [<account_id> | --account_id=<account_id>]
                            [--page=<page>] [--page_size=<page_size>]

        Options:
            --account_id=<account_id> : (str) id of the account to query
            --page=<page>              : (int) page to return during paginating
            --page_size=<page_size>    : (int) number of items on page during pagination

        Returns:
            (list) List of name claims owned by user
            [
                {
                    'address': (str) address that owns the claim
                    'amount': (float) amount assigned to the claim
                    'blocks_to_expiration': (int) number of blocks until it expires
                    'category': (str) "claim", "update" , or "support"
                    'claim_id': (str) claim ID of the claim
                    'confirmations': (int) number of blocks of confirmations for the claim
                    'expiration_height': (int) the block height which the claim will expire
                    'expired': (bool) true if expired, false otherwise
                    'height': (int) height of the block containing the claim
                    'is_spent': (bool) true if claim is abandoned, false otherwise
                    'name': (str) name of the claim
                    'permanent_url': (str) permanent url of the claim,
                    'txid': (str) txid of the claim
                    'nout': (int) nout of the claim
                    'value': (str) value of the claim
                },
           ]
        """
        account = self.get_account_or_default(account_id)
        return maybe_paginate(
            account.get_claims,
            account.get_claim_count,
            page, page_size
        )

    @requires(WALLET_COMPONENT)
    async def jsonrpc_claim_list(self, name):
        """
        List current claims and information about them for a given name

        Usage:
            claim_list (<name> | --name=<name>)

        Options:
            --name=<name> : (str) name of the claim to list info about

        Returns:
            (dict) State of claims assigned for the name
            {
                'claims': (list) list of claims for the name
                [
                    {
                    'amount': (float) amount assigned to the claim
                    'effective_amount': (float) total amount assigned to the claim,
                                        including supports
                    'claim_id': (str) claim ID of the claim
                    'height': (int) height of block containing the claim
                    'txid': (str) txid of the claim
                    'nout': (int) nout of the claim
                    'permanent_url': (str) permanent url of the claim,
                    'supports': (list) a list of supports attached to the claim
                    'value': (str) the value of the claim
                    },
                ]
                'supports_without_claims': (list) supports without any claims attached to them
                'last_takeover_height': (int) the height of last takeover for the name
            }
        """
        claims = await self.wallet_manager.get_claims_for_name(name)  # type: dict
        sort_claim_results(claims['claims'])
        return claims

    @requires(WALLET_COMPONENT)
    async def jsonrpc_claim_list_by_channel(self, page=0, page_size=10, uri=None, uris=[]):
        """
        Get paginated claims in a channel specified by a channel uri

        Usage:
            claim_list_by_channel (<uri> | --uri=<uri>) [<uris>...] [--page=<page>]
                                   [--page_size=<page_size>]

        Options:
            --uri=<uri>              : (str) uri of the channel
            --uris=<uris>            : (list) uris of the channel
            --page=<page>            : (int) which page of results to return where page 1 is the first
                                             page, defaults to no pages
            --page_size=<page_size>  : (int) number of results in a page, default of 10

        Returns:
            {
                 resolved channel uri: {
                    If there was an error:
                    'error': (str) error message

                    'claims_in_channel': the total number of results for the channel,

                    If a page of results was requested:
                    'returned_page': page number returned,
                    'claims_in_channel': [
                        {
                            'absolute_channel_position': (int) claim index number in sorted list of
                                                         claims which assert to be part of the
                                                         channel
                            'address': (str) claim address,
                            'amount': (float) claim amount,
                            'effective_amount': (float) claim amount including supports,
                            'claim_id': (str) claim id,
                            'claim_sequence': (int) claim sequence number,
                            'decoded_claim': (bool) whether or not the claim value was decoded,
                            'height': (int) claim height,
                            'depth': (int) claim depth,
                            'has_signature': (bool) included if decoded_claim
                            'name': (str) claim name,
                            'supports: (list) list of supports [{'txid': (str) txid,
                                                                 'nout': (int) nout,
                                                                 'amount': (float) amount}],
                            'txid': (str) claim txid,
                            'nout': (str) claim nout,
                            'signature_is_valid': (bool), included if has_signature,
                            'value': ClaimDict if decoded, otherwise hex string
                        }
                    ],
                }
            }
        """

        uris = tuple(uris)
        page = int(page)
        page_size = int(page_size)
        if uri is not None:
            uris += (uri,)

        results = {}

        valid_uris = tuple()
        for chan_uri in uris:
            try:
                parsed = parse_lbry_uri(chan_uri)
                if not parsed.contains_channel:
                    results[chan_uri] = {"error": "%s is not a channel uri" % parsed.name}
                elif parsed.path:
                    results[chan_uri] = {"error": "%s is a claim in a channel" % parsed.path}
                else:
                    valid_uris += (chan_uri,)
            except URIParseError:
                results[chan_uri] = {"error": "%s is not a valid uri" % chan_uri}

        resolved = await self.wallet_manager.resolve(*valid_uris, page=page, page_size=page_size)
        if 'error' in resolved:
            return {'error': resolved['error']}
        for u in resolved:
            if 'error' in resolved[u]:
                results[u] = resolved[u]
            else:
                results[u] = {
                    'claims_in_channel': resolved[u]['claims_in_channel']
                }
                if page:
                    results[u]['returned_page'] = page
                    results[u]['claims_in_channel'] = resolved[u].get('claims_in_channel', [])
        return results

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

        Returns:
            (dict) JSON formatted transaction
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

        Returns:
            (list) List of unspent transaction outputs (UTXOs)
            [
                {
                    "address": (str) the output address
                    "amount": (float) unspent amount
                    "height": (int) block height
                    "is_claim": (bool) is the tx a claim
                    "is_coinbase": (bool) is the tx a coinbase tx
                    "is_support": (bool) is the tx a support
                    "is_update": (bool) is the tx an update
                    "nout": (int) nout of the output
                    "txid": (str) txid of the output
                },
                ...
            ]
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

    @requires(WALLET_COMPONENT)
    def jsonrpc_block_show(self, blockhash=None, height=None):
        """
        Get contents of a block

        Usage:
            block_show (<blockhash> | --blockhash=<blockhash>) | (<height> | --height=<height>)

        Options:
            --blockhash=<blockhash>  : (str) hash of the block to look up
            --height=<height>        : (int) height of the block to look up

        Returns:
            (dict) Requested block
        """
        return self.wallet_manager.get_block(blockhash, height)

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
            with open(blob.file_path, 'rb') as handle:
                return handle.read().decode()
        else:
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
                metadata = (await self.wallet_manager.resolve(uri))[uri]
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
                blobs.extend([b.blob_hash for b in await self.storage.get_blobs_for_stream(stream_hash)])
        else:
            blobs = list(self.blob_manager.completed_blob_hashes)
        if needed:
            blobs = [blob_hash for blob_hash in blobs if not self.blob_manager.get_blob(blob_hash).get_is_verified()]
        if finished:
            blobs = [blob_hash for blob_hash in blobs if self.blob_manager.get_blob(blob_hash).get_is_verified()]
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

        raise NotImplementedError()

    @requires(DHT_COMPONENT)
    async def jsonrpc_peer_ping(self, node_id, address, port):
        """
        Send a kademlia ping to the specified peer. If address and port are provided the peer is directly pinged,
        if not provided the peer is located first.

        Usage:
            peer_ping (<node_id> | --node_id=<node_id>) (<address> | --address=<address>) (<port> | --port=<port>)

        Returns:
            (str) pong, or {'error': <error message>} if an error is encountered
        """
        peer = None
        if node_id and address and port:
            peer = self.component_manager.peer_manager.get_peer(address, unhexlify(node_id), udp_port=int(port))
            if not peer:
                peer = self.component_manager.peer_manager.make_peer(
                    address, unhexlify(node_id), udp_port=int(port)
                )
        if not peer:
            return {'error': 'peer not found'}
        try:
            result = await peer.ping()
            return result.decode()
        except asyncio.TimeoutError:
            return {'error': 'ping timeout'}

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

    async def get_channel_or_error(
            self, accounts: List[LBCAccount], channel_id: str = None, channel_name: str = None):
        if channel_id is not None:
            certificates = await self.wallet_manager.get_certificates(
                private_key_accounts=accounts, claim_id=channel_id)
            if not certificates:
                raise ValueError("Couldn't find channel with claim_id '{}'." .format(channel_id))
            return certificates[0]
        if channel_name is not None:
            certificates = await self.wallet_manager.get_certificates(
                private_key_accounts=accounts, claim_name=channel_name)
            if not certificates:
                raise ValueError(f"Couldn't find channel with name '{channel_name}'.")
            return certificates[0]
        raise ValueError("Couldn't find channel because a channel name or channel_id was not provided.")

    def get_account_or_default(self, account_id: str, argument_name: str = "account", lbc_only=True):
        if account_id is None:
            return self.default_account
        return self.get_account_or_error(account_id, argument_name, lbc_only)

    def get_accounts_or_all(self, account_ids: List[str]):
        return [
            self.get_account_or_error(account_id)
            for account_id in account_ids
        ] if account_ids else self.default_wallet.accounts

    def get_account_or_error(self, account_id: str, argument_name: str = "account", lbc_only=True):
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
    def get_dewies_or_error(argument: str, lbc: str):
        try:
            return lbc_to_dewies(lbc)
        except ValueError as e:
            raise ValueError("Invalid value for '{}': {}".format(argument, e.args[0]))


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
