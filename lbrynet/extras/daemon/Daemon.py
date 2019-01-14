import os
from urllib.parse import urlencode, quote
import aiohttp
import textwrap
import typing
from typing import Callable, Optional, List
from binascii import hexlify, unhexlify
from copy import deepcopy
from traceback import format_exc
from torba.client.baseaccount import SingleKey, HierarchicalDeterministic
from lbrynet import __version__
from lbrynet.blob.blob_file import is_valid_blobhash
from lbrynet.extras import system_info
from lbrynet.extras.daemon.Components import WALLET_COMPONENT, DATABASE_COMPONENT, DHT_COMPONENT, BLOB_COMPONENT
from lbrynet.extras.daemon.Components import STREAM_MANAGER_COMPONENT
from lbrynet.extras.daemon.Components import EXCHANGE_RATE_MANAGER_COMPONENT, UPNP_COMPONENT
from lbrynet.extras.daemon.ComponentManager import RequiredCondition
from lbrynet.extras.wallet.account import Account as LBCAccount
from lbrynet.extras.wallet.dewies import dewies_to_lbc, lbc_to_dewies
from lbrynet.error import InsufficientFundsError, UnknownNameError, DownloadSDTimeout, ComponentsNotStarted
from lbrynet.error import NullFundsError, NegativeFundsError, ResolveError, ComponentStartConditionNotMet
from lbrynet.schema.claim import ClaimDict
from lbrynet.schema.uri import parse_lbry_uri
from lbrynet.schema.error import URIParseError, DecodeError
from lbrynet.schema.validator import validate_claim_id
from lbrynet.schema.address import decode_address
from lbrynet.extras.daemon.ComponentManager import ComponentManager
from lbrynet.extras.daemon.json_response_encoder import JSONResponseEncoder

import asyncio
import logging
import json
import inspect
import signal
from functools import wraps

from lbrynet import utils
from lbrynet.extras.daemon.undecorated import undecorated
from lbrynet import conf

from aiohttp import web


if typing.TYPE_CHECKING:
    from lbrynet.extras.daemon.Components import UPnPComponent
    from lbrynet.extras.wallet import LbryWalletManager
    from lbrynet.extras.daemon.exchange_rate_manager import ExchangeRateManager
    from lbrynet.stream.stream_manager import StreamManager, ManagedStream
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.storage import SQLiteStorage
    from lbrynet.dht.node import Node

log = logging.getLogger(__name__)


#
# async def download_single_blob(node: 'Node', blob_manager: 'BlobFileManager'):
#     async with node.pe


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
    allowed_during_startup = []

    def __init__(self, component_manager: typing.Optional[ComponentManager] = None):
        to_skip = conf.settings['components_to_skip']
        use_authentication = conf.settings['use_auth_http']
        use_https = conf.settings['use_https']
        self.component_manager = component_manager or ComponentManager(
            skip_components=to_skip or [],
        )
        self._use_authentication = use_authentication or conf.settings['use_auth_http']
        self._use_https = use_https or conf.settings['use_https']
        self.listening_port = None
        self._component_setup_task = None

        logging.getLogger('aiohttp.access').setLevel(logging.WARN)
        self.app = web.Application()
        self.app.router.add_get('/lbryapi', self.handle_old_jsonrpc)
        self.app.router.add_post('/lbryapi', self.handle_old_jsonrpc)
        self.app.router.add_post('/', self.handle_old_jsonrpc)
        self.handler = self.app.make_handler()
        self.server: asyncio.AbstractServer = None

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

    async def start_listening(self):
        try:
            self.server = await asyncio.get_event_loop().create_server(
                self.handler, conf.settings['api_host'], conf.settings['api_port']
            )
            log.info('lbrynet API listening on TCP %s:%i', *self.server.sockets[0].getsockname()[:2])
            await self.setup()
        except OSError:
            log.error('lbrynet API failed to bind TCP %s:%i for listening. Daemon is already running or this port is '
                      'already in use by another application.', conf.settings['api_host'], conf.settings['api_port'])
        except asyncio.CancelledError:
            log.info("shutting down before finished starting")
        except Exception as err:
            log.exception('Failed to start lbrynet-daemon')
            await self.component_manager.analytics_manager.send_server_startup_error(str(err))

    async def setup(self):
        log.info("Starting lbrynet-daemon")
        log.info("Platform: %s", json.dumps(system_info.get_platform()))
        self.component_manager.analytics_manager.start()
        self._component_setup_task = self.component_manager.setup()
        await self._component_setup_task

        log.info("Started lbrynet-daemon")
        await self.component_manager.analytics_manager.send_server_startup()

    @staticmethod
    def _already_shutting_down(sig_num, frame):
        log.info("Already shutting down")

    async def shutdown(self):
        # ignore INT/TERM signals once shutdown has started
        signal.signal(signal.SIGINT, self._already_shutting_down)
        signal.signal(signal.SIGTERM, self._already_shutting_down)
        if self.listening_port:
            self.listening_port.stopListening()
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            await self.app.shutdown()
            await self.handler.shutdown(60.0)
            await self.app.cleanup()
        self.component_manager.analytics_manager.shutdown()
        try:
            self._component_setup_task.cancel()
        except (AttributeError, asyncio.CancelledError):
            pass
        if self.component_manager is not None:
            await self.component_manager.stop()

    async def handle_old_jsonrpc(self, request):
        data = await request.json()
        result = await self._process_rpc_call(data)
        return web.Response(
            text=jsonrpc_dumps_pretty(result, ledger=self.ledger),
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

    # async def _download_blob(self, blob_hash, rate_manager=None, timeout=None):
    #     """
    #     Download a blob
    #
    #     :param blob_hash (str): blob hash
    #     :param rate_manager (PaymentRateManager), optional: the payment rate manager to use,
    #                                                      defaults to session.payment_rate_manager
    #     :param timeout (int): blob timeout
    #     :return: BlobFile
    #     """
    #     if not blob_hash:
    #         raise Exception("Nothing to download")
    #
    #     rate_manager = rate_manager or self.payment_rate_manager
    #     timeout = timeout or 30
    #     downloader = StandaloneBlobDownloader(
    #         blob_hash, self.blob_manager, self.component_manager.peer_finder, self.rate_limiter,
    #         rate_manager, self.wallet_manager, timeout
    #     )
    #     return await d2f(downloader.download())
    #
    # async def _get_stream_analytics_report(self, claim_dict):
    #     sd_hash = claim_dict.source_hash.decode()
    #     try:
    #         stream_hash = await self.storage.get_stream_hash_for_sd_hash(sd_hash)
    #     except Exception:
    #         stream_hash = None
    #     report = {
    #         "sd_hash": sd_hash,
    #         "stream_hash": stream_hash,
    #     }
    #     blobs = {}
    #     try:
    #         sd_host = await d2f(self.blob_manager.get_host_downloaded_from(sd_hash))
    #     except Exception:
    #         sd_host = None
    #     report["sd_blob"] = sd_host
    #     if stream_hash:
    #         blob_infos = await self.storage.get_blobs_for_stream(stream_hash)
    #         report["known_blobs"] = len(blob_infos)
    #     else:
    #         blob_infos = []
    #         report["known_blobs"] = 0
    #     # for blob_hash, blob_num, iv, length in blob_infos:
    #     #     try:
    #     #         host = yield self.session.blob_manager.get_host_downloaded_from(blob_hash)
    #     #     except Exception:
    #     #         host = None
    #     #     if host:
    #     #         blobs[blob_num] = host
    #     # report["blobs"] = json.dumps(blobs)
    #     return report
    #
    # async def _download_name(self, name, claim_dict, sd_hash, txid, nout, timeout=None, file_name=None):
    #     """
    #     Add a lbry file to the file manager, start the download, and return the new lbry file.
    #     If it already exists in the file manager, return the existing lbry file
    #     """
    #
    #     async def _download_finished(download_id, name, claim_dict):
    #         report = await self._get_stream_analytics_report(claim_dict)
    #        self.component_manager.analytics_manager.send_download_finished(download_id, name, report, claim_dict)
    #        self.component_manager.analytics_manager.send_new_download_success(download_id, name, claim_dict)
    #
    #     async def _download_failed(error, download_id, name, claim_dict):
    #         report = await self._get_stream_analytics_report(claim_dict)
    #        self.component_manager.analytics_manager.send_download_errored(error, download_id, name, claim_dict,
    #                                                      report)
    #        self.component_manager.analytics_manager.send_new_download_fail(download_id, name, claim_dict, error)
    #
    #     if sd_hash in self.streams:
    #         downloader = self.streams[sd_hash]
    #         return await d2f(downloader.finished_deferred)
    #     else:
    #         download_id = utils.random_string()
    #        self.component_manager.analytics_manager.send_download_started(download_id, name, claim_dict)
    #        self.component_manager.analytics_manager.send_new_download_start(download_id, name, claim_dict)
    #         self.streams[sd_hash] = GetStream(
    #             self.file_manager.sd_identifier, self.wallet_manager, self.exchange_rate_manager, self.blob_manager,
    #             self.component_manager.peer_finder, self.rate_limiter, self.payment_rate_manager, self.storage,
    #             conf.settings['max_key_fee'], conf.settings['disable_max_key_fee'], conf.settings['data_rate'],
    #             timeout
    #         )
    #         try:
    #             lbry_file, finished_deferred = await d2f(self.streams[sd_hash].start(
    #                 claim_dict, name, txid, nout, file_name
    #             ))
    #             finished_deferred.addCallbacks(
    #                 lambda _: asyncio.create_task(_download_finished(download_id, name, claim_dict)),
    #                 lambda e: asyncio.create_task(_download_failed(e, download_id, name, claim_dict))
    #             )
    #             result = await self._get_lbry_file_dict(lbry_file)
    #         except Exception as err:
    #             await _download_failed(err, download_id, name, claim_dict)
    #             if isinstance(err, (DownloadDataTimeout, DownloadSDTimeout)):
    #                 log.warning('Failed to get %s (%s)', name, err)
    #             else:
    #                 log.error('Failed to get %s (%s)', name, err)
    #             if self.streams[sd_hash].downloader and self.streams[sd_hash].code != 'running':
    #                 await d2f(self.streams[sd_hash].downloader.stop(err))
    #             result = {'error': str(err)}
    #         finally:
    #             del self.streams[sd_hash]
    #         return result
    #
    # async def _publish_stream(self, account, name, bid, claim_dict, file_path=None, certificate=None,
    #                     claim_address=None, change_address=None):
    #     publisher = Publisher(
    #         account, self.blob_manager, self.payment_rate_manager, self.storage,
    #         self.file_manager, self.wallet_manager, certificate
    #     )
    #     parse_lbry_uri(name)
    #     if not file_path:
    #         stream_hash = await self.storage.get_stream_hash_for_sd_hash(
    #             claim_dict['stream']['source']['source'])
    #         tx = await publisher.publish_stream(name, bid, claim_dict, stream_hash, claim_address)
    #     else:
    #         tx = await publisher.create_and_publish_stream(name, bid, claim_dict, file_path, claim_address)
    #         if conf.settings['reflect_uploads']:
    #             d = reupload.reflect_file(publisher.lbry_file)
    #             d.addCallbacks(lambda _: log.info("Reflected new publication to lbry://%s", name),
    #                            log.exception)
    #    self.component_manager.analytics_manager.send_claim_action('publish')
    #     nout = 0
    #     txo = tx.outputs[nout]
    #     log.info("Success! Published to lbry://%s txid: %s nout: %d", name, tx.id, nout)
    #     return {
    #         "success": True,
    #         "tx": tx,
    #         "claim_id": txo.claim_id,
    #         "claim_address": self.ledger.hash160_to_address(txo.script.values['pubkey_hash']),
    #         "output": tx.outputs[nout]
    #     }
    #
    # async def _get_or_download_sd_blob(self, blob, sd_hash):
    #     if blob:
    #         return self.blob_manager.get_blob(blob[0])
    #     return await d2f(download_sd_blob(
    #         sd_hash.decode(), self.blob_manager, self.component_manager.peer_finder, self.rate_limiter,
    #         self.payment_rate_manager, self.wallet_manager, timeout=conf.settings['peer_search_timeout'],
    #         download_mirrors=conf.settings['download_mirrors']
    #     ))
    #
    # def get_or_download_sd_blob(self, sd_hash):
    #     """Return previously downloaded sd blob if already in the blob
    #     manager, otherwise download and return it
    #     """
    #     return self._get_or_download_sd_blob(
    #         self.blob_manager.completed_blobs([sd_hash.decode()]), sd_hash
    #     )

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

    @deprecated("stop")
    def jsonrpc_daemon_stop(self):
        pass

    def jsonrpc_stop(self):
        """
        Stop lbrynet

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
            'installation_id': conf.settings.installation_id,
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
        Get lbry version information

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
        await report_bug_to_slack(
            message,
            conf.settings.installation_id,
            platform_name,
            __version__
        )
        return True

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
        return conf.settings.get_adjustable_settings_dict()

    def jsonrpc_settings_set(self, **kwargs):
        """
        Set daemon settings

        Usage:
            settings_set [--download_directory=<download_directory>]
                         [--data_rate=<data_rate>]
                         [--download_timeout=<download_timeout>]
                         [--peer_port=<peer_port>]
                         [--max_key_fee=<max_key_fee>]
                         [--disable_max_key_fee=<disable_max_key_fee>]
                         [--use_upnp=<use_upnp>]
                         [--run_reflector_server=<run_reflector_server>]
                         [--cache_time=<cache_time>]
                         [--reflect_uploads=<reflect_uploads>]
                         [--share_usage_data=<share_usage_data>]
                         [--peer_search_timeout=<peer_search_timeout>]
                         [--sd_download_timeout=<sd_download_timeout>]
                         [--auto_renew_claim_height_delta=<auto_renew_claim_height_delta>]

        Options:
            --download_directory=<download_directory>  : (str) path of download directory
            --data_rate=<data_rate>                    : (float) 0.0001
            --download_timeout=<download_timeout>      : (int) 180
            --peer_port=<peer_port>                    : (int) 3333
            --max_key_fee=<max_key_fee>                : (dict) maximum key fee for downloads,
                                                          in the format:
                                                          {
                                                            'currency': <currency_symbol>,
                                                            'amount': <amount>
                                                          }.
                                                          In the CLI, it must be an escaped JSON string
                                                          Supported currency symbols: LBC, USD, BTC
            --disable_max_key_fee=<disable_max_key_fee> : (bool) False
            --use_upnp=<use_upnp>            : (bool) True
            --run_reflector_server=<run_reflector_server>  : (bool) False
            --cache_time=<cache_time>  : (int) 150
            --reflect_uploads=<reflect_uploads>  : (bool) True
            --share_usage_data=<share_usage_data>  : (bool) True
            --peer_search_timeout=<peer_search_timeout>  : (int) 3
            --sd_download_timeout=<sd_download_timeout>  : (int) 3
            --auto_renew_claim_height_delta=<auto_renew_claim_height_delta> : (int) 0
                claims set to expire within this many blocks will be
                automatically renewed after startup (if set to 0, renews
                will not be made automatically)


        Returns:
            (dict) Updated dictionary of daemon settings
        """

        # TODO: improve upon the current logic, it could be made better
        new_settings = kwargs

        setting_types = {
            'download_directory': str,
            'data_rate': float,
            'download_timeout': int,
            'peer_port': int,
            'max_key_fee': dict,
            'use_upnp': bool,
            'run_reflector_server': bool,
            'cache_time': int,
            'reflect_uploads': bool,
            'share_usage_data': bool,
            'disable_max_key_fee': bool,
            'peer_search_timeout': int,
            'sd_download_timeout': int,
            'auto_renew_claim_height_delta': int
        }

        for key, setting_type in setting_types.items():
            if key in new_settings:
                if isinstance(new_settings[key], setting_type):
                    conf.settings.update({key: new_settings[key]},
                                         data_types=(conf.TYPE_RUNTIME, conf.TYPE_PERSISTED))
                elif setting_type is dict and isinstance(new_settings[key], str):
                    decoded = json.loads(str(new_settings[key]))
                    conf.settings.update({key: decoded},
                                         data_types=(conf.TYPE_RUNTIME, conf.TYPE_PERSISTED))
                else:
                    converted = setting_type(new_settings[key])
                    conf.settings.update({key: converted},
                                         data_types=(conf.TYPE_RUNTIME, conf.TYPE_PERSISTED))
        conf.settings.save_conf_file_settings()
        return conf.settings.get_adjustable_settings_dict()

    def jsonrpc_help(self, command=None):
        """
        Return a useful message for an API command

        Usage:
            help [<command> | --command=<command>]

        Options:
            --command=<command>  : (str) command to retrieve documentation for

        Returns:
            (str) Help message
        """

        if command is None:
            return {
                'about': 'This is the LBRY JSON-RPC API',
                'command_help': 'Pass a `command` parameter to this method to see ' +
                                'help for that command (e.g. `help command=resolve_name`)',
                'command_list': 'Get a full list of commands using the `commands` method',
                'more_info': 'Visit https://lbry.io/api for more info',
            }

        fn = self.callable_methods.get(command)
        if fn is None:
            raise Exception(
                f"No help available for '{command}'. It is not a valid command."
            )

        return {
            'help': textwrap.dedent(fn.__doc__ or '')
        }

    def jsonrpc_commands(self):
        """
        Return a list of available commands

        Usage:
            commands

        Options:
            None

        Returns:
            (list) list of available commands
        """
        return sorted([command for command in self.callable_methods.keys()])

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
        else:
            log.info("This command is deprecated for sending tips, please use the newer claim_tip command")
            result = await self.jsonrpc_claim_tip(claim_id=claim_id, amount=amount, account_id=account_id)
        try:
            return result
        finally:
            await self.component_manager.analytics_manager.send_credits_sent()

    @requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    def jsonrpc_wallet_prefill_addresses(self, num_addresses, amount, no_broadcast=False):
        """
        Create new UTXOs, each containing `amount` credits

        Usage:
            wallet_prefill_addresses [--no_broadcast]
                                     (<num_addresses> | --num_addresses=<num_addresses>)
                                     (<amount> | --amount=<amount>)

        Options:
            --no_broadcast                    : (bool) whether to broadcast or not
            --num_addresses=<num_addresses>   : (int) num of addresses to create
            --amount=<amount>                 : (decimal) initial amount in each address

        Returns:
            (dict) the resulting transaction
        """
        broadcast = not no_broadcast
        return self.jsonrpc_account_fund(
            self.default_account.id,
            self.default_account.id,
            amount=amount,
            outputs=num_addresses,
            broadcast=broadcast
        )

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
        Decrypt an encrypted account, this will remove the wallet password

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
        try:
            return result
        finally:
            await self.component_manager.analytics_manager.send_credits_sent()

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

    @requires(STREAM_MANAGER_COMPONENT)
    def jsonrpc_file_list(self, sort=None, reverse=False, comparison=None, **kwargs):
        """
        List files limited by optional filters

        Usage:
            file_list [--sd_hash=<sd_hash>] [--file_name=<file_name>] [--stream_hash=<stream_hash>]
                      [--rowid=<rowid>] [--claim_id=<claim_id>] [--outpoint=<outpoint>] [--txid=<txid>] [--nout=<nout>]
                      [--channel_claim_id=<channel_claim_id>] [--channel_name=<channel_name>]
                      [--claim_name=<claim_name>] [--sort=<sort_by>] [--reverse] [--comparison=<comparison>]

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

    @requires(WALLET_COMPONENT)
    async def jsonrpc_resolve_name(self, name, force=False):
        """
        Resolve stream info from a LBRY name

        Usage:
            resolve_name (<name> | --name=<name>) [--force]

        Options:
            --name=<name> : (str) the name to resolve
            --force       : (bool) force refresh and do not check cache

        Returns:
            (dict) Metadata dictionary from name claim, None if the name is not
                    resolvable
        """

        try:
            name = parse_lbry_uri(name).name
            metadata = await self.wallet_manager.resolve(name, check_cache=not force)
            if name in metadata:
                metadata = metadata[name]
            return metadata
        except UnknownNameError:
            log.info('Name %s is not known', name)

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

        timeout = timeout if timeout is not None else conf.settings['download_timeout']

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

        stream = await self.stream_manager.download_stream_from_claim(
            self.dht_node, conf.settings.download_dir, resolved, file_name, timeout, fee_amount, fee_address
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

        # streams = self.stream_manager.get_filtered_streams(**kwargs)
        # if not streams:
        #     raise Exception('Unable to find a file')
        # stream = streams[0]
        #
        # if status == 'start' and not stream.running and not stream.finished:
        #     self.stream_manager.load_streams_from_database()
        #
        #
        #
        #     or status == 'stop' and not lbry_file.stopped:
        #     await d2f(self.stream_manager.(lbry_file))
        #     msg = "Started downloading file" if status == 'start' else "Stopped downloading file"
        # else:
        #     msg = (
        #         "File was already being downloaded" if status == 'start'
        #         else "File was already stopped"
        #     )
        # return msg

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
        nout = 0
        txo = tx.outputs[nout]
        log.info("Claimed a new channel! lbry://%s txid: %s nout: %d", channel_name, tx.id, nout)
        try:
            return {
                "success": True,
                "tx": tx,
                "claim_id": txo.claim_id,
                "claim_address": txo.get_address(self.ledger),
                "output": txo
            }
        finally:
           await self.component_manager.analytics_manager.send_new_channel()

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

        return await self._publish_stream(
            account, name, amount, claim_dict, file_path,
            certificate, claim_address, change_address
        )

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
        if blocking:
            await self.ledger.wait(tx)
        try:
            return {"success": True, "tx": tx}
        finally:
            await self.component_manager.analytics_manager.send_claim_action('abandon')

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
        self.component_manager.analytics_manager.send_claim_action('new_support')
        try:
            return result
        finally:
            await self.component_manager.analytics_manager.send_claim_action('abandon')

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
        try:
            return result
        finally:
            await self.component_manager.analytics_manager.send_claim_action('new_support')

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

    @requires(WALLET_COMPONENT, DHT_COMPONENT, BLOB_COMPONENT,
              conditions=[WALLET_IS_UNLOCKED])
    async def jsonrpc_blob_get(self, blob_hash, timeout=None):
        """
        Download and return a blob

        Usage:
            blob_get (<blob_hash> | --blob_hash=<blob_hash>) [--timeout=<timeout>]

        Options:
        --blob_hash=<blob_hash>                        : (str) blob hash of the blob to get
        --timeout=<timeout>                            : (int) timeout in number of seconds

        Returns:
            (str) Success/Fail message or (dict) decoded data
        """

        decoders = {
            'json': json.loads
        }

        timeout = timeout or 30
        blob = await self._download_blob(
            blob_hash, rate_manager=self.payment_rate_manager, timeout=timeout
        )
        if encoding and encoding in decoders:
            blob_file = blob.open_for_reading()
            result = decoders[encoding](blob_file.read())
            blob_file.close()
        else:
            result = "Downloaded blob %s" % blob_hash

        return result

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

        if blob_hash not in self.blob_manager.blobs:
            return "Don't have that blob"
        try:
            stream_hash = await self.storage.get_stream_hash_for_sd_hash(blob_hash)
            await self.storage.delete_stream(stream_hash)
        except Exception as err:
            pass
        await d2f(self.blob_manager.delete_blobs([blob_hash]))
        return "Deleted %s" % blob_hash

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

    # @requires(STREAM_MANAGER_COMPONENT)
    # async def jsonrpc_file_reflect(self, **kwargs):
    #     """
    #     Reflect all the blobs in a file matching the filter criteria
    #
    #     Usage:
    #         file_reflect [--sd_hash=<sd_hash>] [--file_name=<file_name>]
    #                      [--stream_hash=<stream_hash>] [--rowid=<rowid>]
    #                      [--reflector=<reflector>]
    #
    #     Options:
    #         --sd_hash=<sd_hash>          : (str) get file with matching sd hash
    #         --file_name=<file_name>      : (str) get file with matching file name in the
    #                                        downloads folder
    #         --stream_hash=<stream_hash>  : (str) get file with matching stream hash
    #         --rowid=<rowid>              : (int) get file with matching row id
    #         --reflector=<reflector>      : (str) reflector server, ip address or url
    #                                        by default choose a server from the config
    #
    #     Returns:
    #         (list) list of blobs reflected
    #     """
    #
    #     reflector_server = kwargs.get('reflector', None)
    #     lbry_files = self._get_lbry_files(**kwargs)
    #
    #     if len(lbry_files) > 1:
    #         raise Exception('Too many (%i) files found, need one' % len(lbry_files))
    #     elif not lbry_files:
    #         raise Exception('No file found')
    #     return await d2f(reupload.reflect_file(
    #         lbry_files[0], reflector_server=kwargs.get('reflector', None)
    #     ))

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
            if stream_hash:
                crypt_blobs = await self.storage.get_blobs_for_stream(stream_hash)
                blobs = await d2f(defer.gatherResults([
                    self.blob_manager.get_blob(crypt_blob.blob_hash, crypt_blob.length)
                    for crypt_blob in crypt_blobs if crypt_blob.blob_hash is not None
                ]))
            else:
                blobs = []
            # get_blobs_for_stream does not include the sd blob, so we'll add it manually
            if sd_hash in self.blob_manager.blobs:
                blobs = [self.blob_manager.blobs[sd_hash]] + blobs
        else:
            blobs = self.blob_manager.blobs.values()

        if needed:
            blobs = [blob for blob in blobs if not blob.get_is_verified()]
        if finished:
            blobs = [blob for blob in blobs if blob.get_is_verified()]

        blob_hashes = [blob.blob_hash for blob in blobs if blob.blob_hash]
        page_size = page_size or len(blob_hashes)
        page = page or 0
        start_index = page * page_size
        stop_index = start_index + page_size
        return blob_hashes[start_index:stop_index]

    # @requires(BLOB_COMPONENT)
    # async def jsonrpc_blob_reflect(self, blob_hashes, reflector_server=None):
    #     """
    #     Reflects specified blobs
    #
    #     Usage:
    #         blob_reflect (<blob_hashes>...) [--reflector_server=<reflector_server>]
    #
    #     Options:
    #         --reflector_server=<reflector_server>          : (str) reflector address
    #
    #     Returns:
    #         (list) reflected blob hashes
    #     """
    #     result = await d2f(reupload.reflect_blob_hashes(blob_hashes, self.blob_manager, reflector_server))
    #     return result

    # @requires(BLOB_COMPONENT)
    # async def jsonrpc_blob_reflect_all(self):
    #     """
    #     Reflects all saved blobs
    #
    #     Usage:
    #         blob_reflect_all
    #
    #     Options:
    #         None
    #
    #     Returns:
    #         (bool) true if successful
    #     """
    #     blob_hashes = await d2f(self.blob_manager.get_all_verified_blobs())
    #     return await d2f(reupload.reflect_blob_hashes(blob_hashes, self.blob_manager))

    @requires(DHT_COMPONENT)
    async def jsonrpc_peer_ping(self, node_id, address=None, port=None):
        """
        Send a kademlia ping to the specified peer. If address and port are provided the peer is directly pinged,
        if not provided the peer is located first.

        Usage:
            peer_ping (<node_id> | --node_id=<node_id>) [<address> | --address=<address>] [<port> | --port=<port>]

        Options:
            --address=<address>     : (str) ip address of the peer
            --port=<port>           : (int) udp port of the peer


        Returns:
            (str) pong, or {'error': <error message>} if an error is encountered
        """
        peer = None
        log.info("%s %s %s", node_id, address, port)
        if node_id and address and port:
            peer = self.component_manager.peer_manager.get_peer(address, unhexlify(node_id), udp_port=int(port))
            if not peer:
                peer = self.component_manager.peer_manager.make_peer(
                    address, unhexlify(node_id), udp_port=int(port)
                )
        # if not contact:
        #     try:
        #         contact = await d2f(self.dht_node.findContact(unhexlify(node_id)))
        #     except TimeoutError:
        #         return {'error': 'timeout finding peer'}
        if not peer:
            return {'error': 'peer not found'}
        try:
            result = await peer.ping()
            return result.decode()
        except TimeoutError:
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
            (dict) dictionary containing routing and contact information
            {
                "buckets": {
                    <bucket index>: [
                        {
                            "address": (str) peer address,
                            "port": (int) peer udp port
                            "node_id": (str) peer node id,
                            "blobs": (list) blob hashes announced by peer
                        }
                    ]
                },
                "contacts": (list) contact node ids,
                "blob_hashes": (list) all of the blob hashes stored by peers in the list of buckets,
                "node_id": (str) the local dht node id
            }
        """
        result = {
            'buckets': {}
        }

        for i in range(len(self.dht_node.protocol.routing_table._buckets)):
            result['buckets'][i] = []
            for contact in self.dht_node.protocol.routing_table._buckets[i]._contacts:
                host = {
                    "address": contact.address,
                    "udp_port": contact.udp_port,
                    "tcp_port": contact.tcp_port,
                    "node_id": hexlify(contact.node_id).decode(),
                }
                result['buckets'][i].append(host)

        result['node_id'] = hexlify(self.dht_node.protocol.node_id).decode()
        return result

    # # the single peer downloader needs wallet access
    # @requires(DHT_COMPONENT, WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    # def jsonrpc_blob_availability(self, blob_hash, search_timeout=None, blob_timeout=None):
    #     """
    #     Get blob availability
    #
    #     Usage:
    #         blob_availability (<blob_hash>) [<search_timeout> | --search_timeout=<search_timeout>]
    #                           [<blob_timeout> | --blob_timeout=<blob_timeout>]
    #
    #     Options:
    #         --blob_hash=<blob_hash>           : (str) check availability for this blob hash
    #         --search_timeout=<search_timeout> : (int) how long to search for peers for the blob
    #                                             in the dht
    #         --blob_timeout=<blob_timeout>     : (int) how long to try downloading from a peer
    #
    #     Returns:
    #         (dict) {
    #             "is_available": <bool, true if blob is available from a peer from peer list>
    #             "reachable_peers": ["<ip>:<port>"],
    #             "unreachable_peers": ["<ip>:<port>"]
    #         }
    #     """
    #     return self._blob_availability(blob_hash, search_timeout, blob_timeout)
    #
    # @requires(UPNP_COMPONENT, WALLET_COMPONENT, DHT_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    # async def jsonrpc_stream_availability(self, uri, search_timeout=None, blob_timeout=None):
    #     """
    #     Get stream availability for lbry uri
    #
    #     Usage:
    #         stream_availability (<uri> | --uri=<uri>)
    #                             [<search_timeout> | --search_timeout=<search_timeout>]
    #                             [<blob_timeout> | --blob_timeout=<blob_timeout>]
    #
    #     Options:
    #         --uri=<uri>                       : (str) check availability for this uri
    #         --search_timeout=<search_timeout> : (int) how long to search for peers for the blob
    #                                             in the dht
    #         --blob_timeout=<blob_timeout>   : (int) how long to try downloading from a peer
    #
    #     Returns:
    #         (dict) {
    #             'is_available': <bool>,
    #             'did_decode': <bool>,
    #             'did_resolve': <bool>,
    #             'is_stream': <bool>,
    #             'num_blobs_in_stream': <int>,
    #             'sd_hash': <str>,
    #             'sd_blob_availability': <dict> see `blob_availability`,
    #             'head_blob_hash': <str>,
    #             'head_blob_availability': <dict> see `blob_availability`,
    #             'use_upnp': <bool>,
    #             'upnp_redirect_is_set': <bool>,
    #             'error': <None> | <str> error message
    #         }
    #     """
    #
    #     search_timeout = search_timeout or conf.settings['peer_search_timeout']
    #     blob_timeout = blob_timeout or conf.settings['sd_download_timeout']
    #
    #     response = {
    #         'is_available': False,
    #         'did_decode': False,
    #         'did_resolve': False,
    #         'is_stream': False,
    #         'num_blobs_in_stream': None,
    #         'sd_hash': None,
    #         'sd_blob_availability': {},
    #         'head_blob_hash': None,
    #         'head_blob_availability': {},
    #         'use_upnp': conf.settings['use_upnp'],
    #         'upnp_redirect_is_set': len(self.upnp.upnp_redirects),
    #         'error': None
    #     }
    #
    #     try:
    #         resolved_result = (await self.wallet_manager.resolve(uri))[uri]
    #         response['did_resolve'] = True
    #     except UnknownNameError:
    #         response['error'] = "Failed to resolve name"
    #         return response
    #     except URIParseError:
    #         response['error'] = "Invalid URI"
    #         return response
    #
    #     try:
    #         claim_obj = smart_decode(resolved_result[uri]['claim']['hex'])
    #         response['did_decode'] = True
    #     except DecodeError:
    #         response['error'] = "Failed to decode claim value"
    #         return response
    #
    #     response['is_stream'] = claim_obj.is_stream
    #     if not claim_obj.is_stream:
    #         response['error'] = "Claim for \"%s\" does not contain a stream" % uri
    #         return response
    #
    #     sd_hash = claim_obj.source_hash
    #     response['sd_hash'] = sd_hash
    #     head_blob_hash = None
    #     downloader = self._get_single_peer_downloader()
    #     have_sd_blob = sd_hash in self.blob_manager.blobs
    #     try:
    #         sd_blob = await self.jsonrpc_blob_get(sd_hash, timeout=blob_timeout, encoding="json")
    #         if not have_sd_blob:
    #             await self.jsonrpc_blob_delete(sd_hash)
    #         if sd_blob and 'blobs' in sd_blob:
    #             response['num_blobs_in_stream'] = len(sd_blob['blobs']) - 1
    #             head_blob_hash = sd_blob['blobs'][0]['blob_hash']
    #             head_blob_availability = await self._blob_availability(
    #                 head_blob_hash, search_timeout, blob_timeout, downloader)
    #             response['head_blob_availability'] = head_blob_availability
    #     except Exception as err:
    #         response['error'] = err
    #     response['head_blob_hash'] = head_blob_hash
    #     response['sd_blob_availability'] = await self._blob_availability(
    #         sd_hash, search_timeout, blob_timeout, downloader)
    #     response['is_available'] = response['sd_blob_availability'].get('is_available') and \
    #                                response['head_blob_availability'].get('is_available')
    #     return response



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


async def report_bug_to_slack(message, installation_id, platform_name, app_version):
    webhook = utils.deobfuscate(conf.settings['SLACK_WEBHOOK'])
    payload_template = "os: %s\n version: %s\n<%s|loggly>\n%s"
    payload_params = (
        platform_name,
        app_version,
        get_loggly_query_string(installation_id),
        message
    )
    payload = {
        "text": payload_template % payload_params
    }
    async with aiohttp.request('post', webhook, data=json.dumps(payload)) as response:
        pass
