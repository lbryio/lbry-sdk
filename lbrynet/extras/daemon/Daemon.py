import logging.handlers
import mimetypes
import os
import requests
import urllib
import json
import textwrap

from typing import Callable, Optional, List
from operator import itemgetter
from binascii import hexlify, unhexlify
from copy import deepcopy
from twisted.internet import defer, reactor
from twisted.internet.task import LoopingCall
from twisted.python.failure import Failure

from torba.client.baseaccount import SingleKey, HierarchicalDeterministic

from lbrynet import conf, utils, __version__
from lbrynet.dht.error import TimeoutError
from lbrynet.blob.blob_file import is_valid_blobhash
from lbrynet.extras import system_info
from lbrynet.extras.reflector import reupload
from lbrynet.extras.daemon.Components import d2f, f2d
from lbrynet.extras.daemon.Components import WALLET_COMPONENT, DATABASE_COMPONENT, DHT_COMPONENT, BLOB_COMPONENT
from lbrynet.extras.daemon.Components import FILE_MANAGER_COMPONENT, RATE_LIMITER_COMPONENT
from lbrynet.extras.daemon.Components import EXCHANGE_RATE_MANAGER_COMPONENT, PAYMENT_RATE_COMPONENT, UPNP_COMPONENT
from lbrynet.extras.daemon.ComponentManager import RequiredCondition
from lbrynet.extras.daemon.Downloader import GetStream
from lbrynet.extras.daemon.Publisher import Publisher
from lbrynet.extras.daemon.auth.server import AuthJSONRPCServer
from lbrynet.extras.wallet import LbryWalletManager
from lbrynet.extras.wallet.account import Account as LBCAccount
from lbrynet.extras.wallet.dewies import dewies_to_lbc, lbc_to_dewies
from lbrynet.p2p.StreamDescriptor import download_sd_blob
from lbrynet.p2p.Error import InsufficientFundsError, UnknownNameError, DownloadDataTimeout, DownloadSDTimeout
from lbrynet.p2p.Error import NullFundsError, NegativeFundsError, ResolveError
from lbrynet.p2p.Peer import Peer
from lbrynet.p2p.SinglePeerDownloader import SinglePeerDownloader
from lbrynet.p2p.client.StandaloneBlobDownloader import StandaloneBlobDownloader
from lbrynet.schema.claim import ClaimDict
from lbrynet.schema.uri import parse_lbry_uri
from lbrynet.schema.error import URIParseError, DecodeError
from lbrynet.schema.validator import validate_claim_id
from lbrynet.schema.address import decode_address
from lbrynet.schema.decode import smart_decode

log = logging.getLogger(__name__)
requires = AuthJSONRPCServer.requires

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

DIRECTION_ASCENDING = 'asc'
DIRECTION_DESCENDING = 'desc'
DIRECTIONS = DIRECTION_ASCENDING, DIRECTION_DESCENDING


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


class IterableContainer:
    def __iter__(self):
        for attr in dir(self):
            if not attr.startswith("_"):
                yield getattr(self, attr)

    def __contains__(self, item):
        for attr in self:
            if item == attr:
                return True
        return False


class Checker:
    """The looping calls the daemon runs"""
    INTERNET_CONNECTION = 'internet_connection_checker', 300
    # CONNECTION_STATUS = 'connection_status_checker'


class _FileID(IterableContainer):
    """The different ways a file can be identified"""
    SD_HASH = 'sd_hash'
    FILE_NAME = 'file_name'
    STREAM_HASH = 'stream_hash'
    ROWID = "rowid"
    CLAIM_ID = "claim_id"
    OUTPOINT = "outpoint"
    TXID = "txid"
    NOUT = "nout"
    CHANNEL_CLAIM_ID = "channel_claim_id"
    CLAIM_NAME = "claim_name"
    CHANNEL_NAME = "channel_name"


FileID = _FileID()


# TODO add login credentials in a conf file
# TODO alert if your copy of a lbry file is out of date with the name record


class NoValidSearch(Exception):
    pass


class CheckInternetConnection:
    def __init__(self, daemon):
        self.daemon = daemon

    def __call__(self):
        self.daemon.connected_to_internet = utils.check_connection()


class AlwaysSend:
    def __init__(self, value_generator, *args, **kwargs):
        self.value_generator = value_generator
        self.args = args
        self.kwargs = kwargs

    def __call__(self):
        d = defer.maybeDeferred(self.value_generator, *self.args, **self.kwargs)
        d.addCallback(lambda v: (True, v))
        return d


def sort_claim_results(claims):
    claims.sort(key=lambda d: (d['height'], d['name'], d['claim_id'], d['txid'], d['nout']))
    return claims


def is_first_run():
    if os.path.isfile(conf.settings.get_db_revision_filename()):
        return False
    if os.path.isfile(os.path.join(conf.settings['data_dir'], 'lbrynet.sqlite')):
        return False
    if os.path.isfile(os.path.join(conf.settings['lbryum_wallet_dir'], 'blockchain_headers')):
        return False
    return True


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


class Daemon(AuthJSONRPCServer):
    """
    LBRYnet daemon, a jsonrpc interface to lbry functions
    """

    component_attributes = {
        DATABASE_COMPONENT: "storage",
        DHT_COMPONENT: "dht_node",
        WALLET_COMPONENT: "wallet_manager",
        FILE_MANAGER_COMPONENT: "file_manager",
        EXCHANGE_RATE_MANAGER_COMPONENT: "exchange_rate_manager",
        PAYMENT_RATE_COMPONENT: "payment_rate_manager",
        RATE_LIMITER_COMPONENT: "rate_limiter",
        BLOB_COMPONENT: "blob_manager",
        UPNP_COMPONENT: "upnp"
    }

    def __init__(self, analytics_manager=None, component_manager=None):
        to_skip = conf.settings['components_to_skip']
        if 'reflector' not in to_skip and not conf.settings['run_reflector_server']:
            to_skip.append('reflector')
        looping_calls = {
            Checker.INTERNET_CONNECTION[0]: (LoopingCall(CheckInternetConnection(self)),
                                             Checker.INTERNET_CONNECTION[1])
        }
        AuthJSONRPCServer.__init__(self, analytics_manager=analytics_manager, component_manager=component_manager,
                                   use_authentication=conf.settings['use_auth_http'],
                                   use_https=conf.settings['use_https'], to_skip=to_skip, looping_calls=looping_calls)
        self.is_first_run = is_first_run()

        # TODO: move this to a component
        self.connected_to_internet = True
        self.connection_status_code = None

        # components
        # TODO: delete these, get the components where needed
        self.storage = None
        self.dht_node = None
        self.wallet_manager: LbryWalletManager = None
        self.file_manager = None
        self.exchange_rate_manager = None
        self.payment_rate_manager = None
        self.rate_limiter = None
        self.blob_manager = None
        self.upnp = None

        # TODO: delete this
        self.streams = {}

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

    @defer.inlineCallbacks
    def setup(self):
        log.info("Starting lbrynet-daemon")
        log.info("Platform: %s", json.dumps(system_info.get_platform()))
        yield super().setup()
        log.info("Started lbrynet-daemon")

    def _stop_streams(self):
        """stop pending GetStream downloads"""
        for sd_hash, stream in self.streams.items():
            stream.cancel(reason="daemon shutdown")

    def _shutdown(self):
        self._stop_streams()
        return super()._shutdown()

    def _download_blob(self, blob_hash, rate_manager=None, timeout=None):
        """
        Download a blob

        :param blob_hash (str): blob hash
        :param rate_manager (PaymentRateManager), optional: the payment rate manager to use,
                                                         defaults to session.payment_rate_manager
        :param timeout (int): blob timeout
        :return: BlobFile
        """
        if not blob_hash:
            raise Exception("Nothing to download")

        rate_manager = rate_manager or self.payment_rate_manager
        timeout = timeout or 30
        downloader = StandaloneBlobDownloader(
            blob_hash, self.blob_manager, self.component_manager.peer_finder, self.rate_limiter,
            rate_manager, self.wallet_manager, timeout
        )
        return downloader.download()

    @defer.inlineCallbacks
    def _get_stream_analytics_report(self, claim_dict):
        sd_hash = claim_dict.source_hash.decode()
        try:
            stream_hash = yield self.storage.get_stream_hash_for_sd_hash(sd_hash)
        except Exception:
            stream_hash = None
        report = {
            "sd_hash": sd_hash,
            "stream_hash": stream_hash,
        }
        blobs = {}
        try:
            sd_host = yield self.blob_manager.get_host_downloaded_from(sd_hash)
        except Exception:
            sd_host = None
        report["sd_blob"] = sd_host
        if stream_hash:
            blob_infos = yield self.storage.get_blobs_for_stream(stream_hash)
            report["known_blobs"] = len(blob_infos)
        else:
            blob_infos = []
            report["known_blobs"] = 0
        # for blob_hash, blob_num, iv, length in blob_infos:
        #     try:
        #         host = yield self.session.blob_manager.get_host_downloaded_from(blob_hash)
        #     except Exception:
        #         host = None
        #     if host:
        #         blobs[blob_num] = host
        # report["blobs"] = json.dumps(blobs)
        defer.returnValue(report)

    @defer.inlineCallbacks
    def _download_name(self, name, claim_dict, sd_hash, txid, nout, timeout=None, file_name=None):
        """
        Add a lbry file to the file manager, start the download, and return the new lbry file.
        If it already exists in the file manager, return the existing lbry file
        """

        @defer.inlineCallbacks
        def _download_finished(download_id, name, claim_dict):
            report = yield self._get_stream_analytics_report(claim_dict)
            self.analytics_manager.send_download_finished(download_id, name, report, claim_dict)
            self.analytics_manager.send_new_download_success(download_id, name, claim_dict)

        @defer.inlineCallbacks
        def _download_failed(error, download_id, name, claim_dict):
            report = yield self._get_stream_analytics_report(claim_dict)
            self.analytics_manager.send_download_errored(error, download_id, name, claim_dict,
                                                         report)
            self.analytics_manager.send_new_download_fail(download_id, name, claim_dict, error)

        if sd_hash in self.streams:
            downloader = self.streams[sd_hash]
            result = yield downloader.finished_deferred
            defer.returnValue(result)
        else:
            download_id = utils.random_string()
            self.analytics_manager.send_download_started(download_id, name, claim_dict)
            self.analytics_manager.send_new_download_start(download_id, name, claim_dict)
            self.streams[sd_hash] = GetStream(
                self.file_manager.sd_identifier, self.wallet_manager, self.exchange_rate_manager, self.blob_manager,
                self.component_manager.peer_finder, self.rate_limiter, self.payment_rate_manager, self.storage,
                conf.settings['max_key_fee'], conf.settings['disable_max_key_fee'], conf.settings['data_rate'],
                timeout
            )
            try:
                lbry_file, finished_deferred = yield self.streams[sd_hash].start(
                    claim_dict, name, txid, nout, file_name
                )
                finished_deferred.addCallbacks(
                    lambda _: _download_finished(download_id, name, claim_dict),
                    lambda e: _download_failed(e, download_id, name, claim_dict)
                )
                result = yield self._get_lbry_file_dict(lbry_file)
            except Exception as err:
                yield _download_failed(err, download_id, name, claim_dict)
                if isinstance(err, (DownloadDataTimeout, DownloadSDTimeout)):
                    log.warning('Failed to get %s (%s)', name, err)
                else:
                    log.error('Failed to get %s (%s)', name, err)
                if self.streams[sd_hash].downloader and self.streams[sd_hash].code != 'running':
                    yield self.streams[sd_hash].downloader.stop(err)
                result = {'error': str(err)}
            finally:
                del self.streams[sd_hash]
            defer.returnValue(result)

    async def _publish_stream(self, account, name, bid, claim_dict, file_path=None, certificate=None,
                        claim_address=None, change_address=None):
        publisher = Publisher(
            account, self.blob_manager, self.payment_rate_manager, self.storage,
            self.file_manager, self.wallet_manager, certificate
        )
        parse_lbry_uri(name)
        if not file_path:
            stream_hash = await d2f(self.storage.get_stream_hash_for_sd_hash(
                claim_dict['stream']['source']['source']))
            tx = await publisher.publish_stream(name, bid, claim_dict, stream_hash, claim_address)
        else:
            tx = await publisher.create_and_publish_stream(name, bid, claim_dict, file_path, claim_address)
            if conf.settings['reflect_uploads']:
                d = reupload.reflect_file(publisher.lbry_file)
                d.addCallbacks(lambda _: log.info("Reflected new publication to lbry://%s", name),
                               log.exception)
        self.analytics_manager.send_claim_action('publish')
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

    def _get_or_download_sd_blob(self, blob, sd_hash):
        if blob:
            return self.blob_manager.get_blob(blob[0])
        return download_sd_blob(
            sd_hash.decode(), self.blob_manager, self.component_manager.peer_finder, self.rate_limiter,
            self.payment_rate_manager, self.wallet_manager, timeout=conf.settings['peer_search_timeout'],
            download_mirrors=conf.settings['download_mirrors']
        )

    def get_or_download_sd_blob(self, sd_hash):
        """Return previously downloaded sd blob if already in the blob
        manager, otherwise download and return it
        """
        d = self.blob_manager.completed_blobs([sd_hash.decode()])
        d.addCallback(self._get_or_download_sd_blob, sd_hash)
        return d

    def get_size_from_sd_blob(self, sd_blob):
        """
        Get total stream size in bytes from a sd blob
        """

        d = self.file_manager.sd_identifier.get_metadata_for_sd_blob(sd_blob)
        d.addCallback(lambda metadata: metadata.validator.info_to_show())
        d.addCallback(lambda info: int(dict(info)['stream_size']))
        return d

    def _get_est_cost_from_stream_size(self, size):
        """
        Calculate estimated LBC cost for a stream given its size in bytes
        """

        if self.payment_rate_manager.generous:
            return 0.0
        return size / (10 ** 6) * conf.settings['data_rate']

    async def get_est_cost_using_known_size(self, uri, size):
        """
        Calculate estimated LBC cost for a stream given its size in bytes
        """
        cost = self._get_est_cost_from_stream_size(size)
        resolved = await self.wallet_manager.resolve(uri)

        if uri in resolved and 'claim' in resolved[uri]:
            claim = ClaimDict.load_dict(resolved[uri]['claim']['value'])
            final_fee = self._add_key_fee_to_est_data_cost(claim.source_fee, cost)
            return final_fee

    def get_est_cost_from_sd_hash(self, sd_hash):
        """
        Get estimated cost from a sd hash
        """

        d = self.get_or_download_sd_blob(sd_hash)
        d.addCallback(self.get_size_from_sd_blob)
        d.addCallback(self._get_est_cost_from_stream_size)
        return d

    def _get_est_cost_from_metadata(self, metadata, name):
        d = self.get_est_cost_from_sd_hash(metadata.source_hash)

        def _handle_err(err):
            if isinstance(err, Failure):
                log.warning(
                    "Timeout getting blob for cost est for lbry://%s, using only key fee", name)
                return 0.0
            raise err

        d.addErrback(_handle_err)
        d.addCallback(lambda data_cost: self._add_key_fee_to_est_data_cost(metadata.source_fee,
                                                                           data_cost))
        return d

    def _add_key_fee_to_est_data_cost(self, fee, data_cost):
        fee_amount = 0.0 if not fee else self.exchange_rate_manager.convert_currency(fee.currency,
                                                                                     "LBC",
                                                                                     fee.amount)
        return data_cost + fee_amount

    async def get_est_cost_from_uri(self, uri):
        """
        Resolve a name and return the estimated stream cost
        """

        resolved = await self.wallet_manager.resolve(uri)
        if resolved:
            claim_response = resolved[uri]
        else:
            claim_response = None

        result = None
        if claim_response and 'claim' in claim_response:
            if 'value' in claim_response['claim'] and claim_response['claim']['value'] is not None:
                claim_value = ClaimDict.load_dict(claim_response['claim']['value'])
                cost = await d2f(self._get_est_cost_from_metadata(claim_value, uri))
                result = round(cost, 5)
            else:
                log.warning("Failed to estimate cost for %s", uri)
        return result

    def get_est_cost(self, uri, size=None):
        """Get a cost estimate for a lbry stream, if size is not provided the
        sd blob will be downloaded to determine the stream size

        """
        if size is not None:
            return self.get_est_cost_using_known_size(uri, size)
        return self.get_est_cost_from_uri(uri)

    @defer.inlineCallbacks
    def _get_lbry_file_dict(self, lbry_file):
        key = hexlify(lbry_file.key) if lbry_file.key else None
        full_path = os.path.join(lbry_file.download_directory, lbry_file.file_name)
        mime_type = mimetypes.guess_type(full_path)[0]
        if os.path.isfile(full_path):
            with open(full_path) as written_file:
                written_file.seek(0, os.SEEK_END)
                written_bytes = written_file.tell()
        else:
            written_bytes = 0

        size = yield lbry_file.get_total_bytes()
        file_status = yield lbry_file.status()
        num_completed = file_status.num_completed
        num_known = file_status.num_known
        status = file_status.running_status

        result = {
            'completed': lbry_file.completed,
            'file_name': lbry_file.file_name,
            'download_directory': lbry_file.download_directory,
            'points_paid': lbry_file.points_paid,
            'stopped': lbry_file.stopped,
            'stream_hash': lbry_file.stream_hash,
            'stream_name': lbry_file.stream_name,
            'suggested_file_name': lbry_file.suggested_file_name,
            'sd_hash': lbry_file.sd_hash,
            'download_path': full_path,
            'mime_type': mime_type,
            'key': key,
            'total_bytes': size,
            'written_bytes': written_bytes,
            'blobs_completed': num_completed,
            'blobs_in_stream': num_known,
            'status': status,
            'claim_id': lbry_file.claim_id,
            'txid': lbry_file.txid,
            'nout': lbry_file.nout,
            'outpoint': lbry_file.outpoint,
            'metadata': lbry_file.metadata,
            'channel_claim_id': lbry_file.channel_claim_id,
            'channel_name': lbry_file.channel_name,
            'claim_name': lbry_file.claim_name
        }
        defer.returnValue(result)

    @defer.inlineCallbacks
    def _get_lbry_file(self, search_by, val, return_json=False):
        lbry_file = None
        if search_by in FileID:
            for l_f in self.file_manager.lbry_files:
                if l_f.__dict__.get(search_by) == val:
                    lbry_file = l_f
                    break
        else:
            raise NoValidSearch(f'{search_by} is not a valid search operation')
        if return_json and lbry_file:
            lbry_file = yield self._get_lbry_file_dict(lbry_file)
        defer.returnValue(lbry_file)

    @defer.inlineCallbacks
    def _get_lbry_files(self, return_json=False, **kwargs):
        lbry_files = list(self.file_manager.lbry_files)
        if kwargs:
            for search_type, value in iter_lbry_file_search_values(kwargs):
                lbry_files = [l_f for l_f in lbry_files if l_f.__dict__[search_type] == value]
        if return_json:
            file_dicts = []
            for lbry_file in lbry_files:
                lbry_file_dict = yield self._get_lbry_file_dict(lbry_file)
                file_dicts.append(lbry_file_dict)
            lbry_files = file_dicts
        log.debug("Collected %i lbry files", len(lbry_files))
        defer.returnValue(lbry_files)

    def _sort_lbry_files(self, lbry_files, sort_by):
        for field, direction in sort_by:
            is_reverse = direction == DIRECTION_DESCENDING
            key_getter = create_key_getter(field) if field else None
            lbry_files = sorted(lbry_files, key=key_getter, reverse=is_reverse)
        return lbry_files

    def _parse_lbry_files_sort(self, sort):
        """
        Given a sort string like 'file_name, desc' or 'points_paid',
        parse the string into a tuple of (field, direction).
        Direction defaults to ascending.
        """

        pieces = [p.strip() for p in sort.split(',')]
        field = pieces.pop(0)
        direction = DIRECTION_ASCENDING
        if pieces and pieces[0] in DIRECTIONS:
            direction = pieces[0]
        return field, direction

    def _get_single_peer_downloader(self):
        downloader = SinglePeerDownloader()
        downloader.setup(self.wallet_manager)
        return downloader

    @defer.inlineCallbacks
    def _blob_availability(self, blob_hash, search_timeout, blob_timeout, downloader=None):
        if not downloader:
            downloader = self._get_single_peer_downloader()
        result = {}
        search_timeout = search_timeout or conf.settings['peer_search_timeout']
        blob_timeout = blob_timeout or conf.settings['sd_download_timeout']
        is_available = False
        reachable_peers = []
        unreachable_peers = []
        try:
            peers = yield self.jsonrpc_peer_list(blob_hash, search_timeout)
            peer_infos = [{"peer": Peer(x['host'], x['port']),
                           "blob_hash": blob_hash,
                           "timeout": blob_timeout} for x in peers]
            dl = []
            dl_peers = []
            dl_results = []
            for peer_info in peer_infos:
                d = downloader.download_temp_blob_from_peer(**peer_info)
                dl.append(d)
                dl_peers.append("%s:%i" % (peer_info['peer'].host, peer_info['peer'].port))
            for dl_peer, (success, download_result) in zip(dl_peers,
                                                           (yield defer.DeferredList(dl))):
                if success:
                    if download_result:
                        reachable_peers.append(dl_peer)
                    else:
                        unreachable_peers.append(dl_peer)
                    dl_results.append(download_result)
            is_available = any(dl_results)
        except Exception as err:
            result['error'] = "Failed to get peers for blob: %s" % err

        response = {
            'is_available': is_available,
            'reachable_peers': reachable_peers,
            'unreachable_peers': unreachable_peers,
        }
        defer.returnValue(response)

    ############################################################################
    #                                                                          #
    #                JSON-RPC API methods start here                           #
    #                                                                          #
    ############################################################################

    @AuthJSONRPCServer.deprecated("stop")
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
        reactor.callLater(0.1, reactor.fireSystemEvent, "shutdown")
        return "Shutting down"

    @defer.inlineCallbacks
    def jsonrpc_status(self):
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
                'is_first_run': bool,
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

        connection_code = CONNECTION_STATUS_CONNECTED if self.connected_to_internet else CONNECTION_STATUS_NETWORK
        response = {
            'installation_id': conf.settings.installation_id,
            'is_running': all(self.component_manager.get_components_status().values()),
            'is_first_run': self.is_first_run,
            'skipped_components': self.component_manager.skip_components,
            'startup_status': self.component_manager.get_components_status(),
            'connection_status': {
                'code': connection_code,
                'message': CONNECTION_MESSAGES[connection_code],
            },
        }
        for component in self.component_manager.components:
            status = yield defer.maybeDeferred(component.get_status)
            if status:
                response[component.component_name] = status
        defer.returnValue(response)

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
        return self._render_response(platform_info)

    def jsonrpc_report_bug(self, message=None):
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
        report_bug_to_slack(
            message,
            conf.settings.installation_id,
            platform_name,
            __version__
        )
        return self._render_response(True)

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
        return self._render_response(conf.settings.get_adjustable_settings_dict())

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
        return self._render_response(conf.settings.get_adjustable_settings_dict())

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
            return self._render_response({
                'about': 'This is the LBRY JSON-RPC API',
                'command_help': 'Pass a `command` parameter to this method to see ' +
                                'help for that command (e.g. `help command=resolve_name`)',
                'command_list': 'Get a full list of commands using the `commands` method',
                'more_info': 'Visit https://lbry.io/api for more info',
            })

        fn = self.callable_methods.get(command)
        if fn is None:
            raise Exception(
                f"No help available for '{command}'. It is not a valid command."
            )

        return self._render_response({
            'help': textwrap.dedent(fn.__doc__ or '')
        })

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
        return self._render_response(sorted([command for command in self.callable_methods.keys()]))

    @AuthJSONRPCServer.deprecated("account_balance")
    def jsonrpc_wallet_balance(self, address=None):
        pass

    @AuthJSONRPCServer.deprecated("account_unlock")
    def jsonrpc_wallet_unlock(self, password):
        pass

    @AuthJSONRPCServer.deprecated("account_decrypt")
    def jsonrpc_wallet_decrypt(self):
        pass

    @AuthJSONRPCServer.deprecated("account_encrypt")
    def jsonrpc_wallet_encrypt(self, new_password):
        pass

    @AuthJSONRPCServer.deprecated("address_is_mine")
    def jsonrpc_wallet_is_address_mine(self, address):
        pass

    @AuthJSONRPCServer.deprecated()
    def jsonrpc_wallet_public_key(self, address):
        pass

    @AuthJSONRPCServer.deprecated("address_list")
    def jsonrpc_wallet_list(self):
        pass

    @AuthJSONRPCServer.deprecated("address_unused")
    def jsonrpc_wallet_new_address(self):
        pass

    @AuthJSONRPCServer.deprecated("address_unused")
    def jsonrpc_wallet_unused_address(self):
        pass

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
            self.analytics_manager.send_credits_sent()
        else:
            log.info("This command is deprecated for sending tips, please use the newer claim_tip command")
            result = await self.jsonrpc_claim_tip(claim_id=claim_id, amount=amount, account_id=account_id)
        return result

    @requires(WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    # @AuthJSONRPCServer.deprecated("account_fund"), API has changed as well, so we forward for now
    # marked as deprecated in changelog and will be removed after subsequent release
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
            await self.ledger.update_account(account)

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
            await self.ledger.update_account(account)

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
    def jsonrpc_account_fund(self, to_account, from_account, amount='0.0',
                             everything=False, outputs=1, broadcast=False):
        """
        Transfer some amount (or --everything) to an account from another
        account (can be the same account). Amounts are interpreted as LBC.
        You can also spread the transfer across a number of --outputs (cannot
        be used together with --everything).

        Usage:
            account_fund (<to_account> | --to_account=<to_account>)
                (<from_account> | --from_account=<from_account>)
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
        to_account = self.get_account_or_error(to_account, 'to_account')
        from_account = self.get_account_or_error(from_account, 'from_account')
        amount = self.get_dewies_or_error('amount', amount) if amount else None
        if not isinstance(outputs, int):
            raise ValueError("--outputs must be an integer.")
        if everything and outputs > 1:
            raise ValueError("Using --everything along with --outputs is not supported.")
        return from_account.fund(
            to_account=to_account, amount=amount, everything=everything,
            outputs=outputs, broadcast=broadcast
        )

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

    @requires(FILE_MANAGER_COMPONENT)
    @defer.inlineCallbacks
    def jsonrpc_file_list(self, sort=None, **kwargs):
        """
        List files limited by optional filters

        Usage:
            file_list [--sd_hash=<sd_hash>] [--file_name=<file_name>] [--stream_hash=<stream_hash>]
                      [--rowid=<rowid>] [--claim_id=<claim_id>] [--outpoint=<outpoint>] [--txid=<txid>] [--nout=<nout>]
                      [--channel_claim_id=<channel_claim_id>] [--channel_name=<channel_name>]
                      [--claim_name=<claim_name>] [--sort=<sort_method>...]

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

        result = yield self._get_lbry_files(return_json=True, **kwargs)
        if sort:
            sort_by = [self._parse_lbry_files_sort(s) for s in sort]
            result = self._sort_lbry_files(result, sort_by)
        response = yield self._render_response(result)
        defer.returnValue(response)

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

    @requires(WALLET_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT, BLOB_COMPONENT,
              RATE_LIMITER_COMPONENT, PAYMENT_RATE_COMPONENT, DATABASE_COMPONENT,
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
        if parsed_uri.is_channel and not parsed_uri.path:
            raise Exception("cannot download a channel claim, specify a /path")

        resolved = (await self.wallet_manager.resolve(uri)).get(uri, {})
        resolved = resolved if 'value' in resolved else resolved.get('claim')

        if not resolved:
            raise ResolveError(
                "Failed to resolve stream at lbry://{}".format(uri.replace("lbry://", ""))
            )

        txid, nout, name = resolved['txid'], resolved['nout'], resolved['name']
        claim_dict = ClaimDict.load_dict(resolved['value'])
        sd_hash = claim_dict.source_hash.decode()

        if sd_hash in self.streams:
            log.info("Already waiting on lbry://%s to start downloading", name)
            await d2f(self.streams[sd_hash].data_downloading_deferred)

        lbry_file = await d2f(self._get_lbry_file(FileID.SD_HASH, sd_hash, return_json=False))

        if lbry_file:
            if not os.path.isfile(os.path.join(lbry_file.download_directory, lbry_file.file_name)):
                log.info("Already have lbry file but missing file in %s, rebuilding it",
                         lbry_file.download_directory)
                await d2f(lbry_file.start())
            else:
                log.info('Already have a file for %s', name)
            result = await d2f(self._get_lbry_file_dict(lbry_file))
        else:
            result = await d2f(self._download_name(name, claim_dict, sd_hash, txid, nout,
                                                   timeout=timeout, file_name=file_name))
        return result

    @requires(FILE_MANAGER_COMPONENT)
    @defer.inlineCallbacks
    def jsonrpc_file_set_status(self, status, **kwargs):
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

        search_type, value = get_lbry_file_search_value(kwargs)
        lbry_file = yield self._get_lbry_file(search_type, value, return_json=False)
        if not lbry_file:
            raise Exception(f'Unable to find a file for {search_type}:{value}')

        if status == 'start' and lbry_file.stopped or status == 'stop' and not lbry_file.stopped:
            yield self.file_manager.toggle_lbry_file_running(lbry_file)
            msg = "Started downloading file" if status == 'start' else "Stopped downloading file"
        else:
            msg = (
                "File was already being downloaded" if status == 'start'
                else "File was already stopped"
            )
        response = yield self._render_response(msg)
        defer.returnValue(response)

    @requires(FILE_MANAGER_COMPONENT)
    @defer.inlineCallbacks
    def jsonrpc_file_delete(self, delete_from_download_dir=False, delete_all=False, **kwargs):
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

        lbry_files = yield self._get_lbry_files(return_json=False, **kwargs)

        if len(lbry_files) > 1:
            if not delete_all:
                log.warning("There are %i files to delete, use narrower filters to select one",
                            len(lbry_files))
                response = yield self._render_response(False)
                defer.returnValue(response)
            else:
                log.warning("Deleting %i files",
                            len(lbry_files))

        if not lbry_files:
            log.warning("There is no file to delete")
            result = False
        else:
            for lbry_file in lbry_files:
                file_name, stream_hash = lbry_file.file_name, lbry_file.stream_hash
                if lbry_file.sd_hash in self.streams:
                    del self.streams[lbry_file.sd_hash]
                yield self.file_manager.delete_lbry_file(lbry_file,
                                                         delete_file=delete_from_download_dir)
                log.info("Deleted file: %s", file_name)
            result = True

        response = yield self._render_response(result)
        defer.returnValue(response)

    @requires(WALLET_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT, BLOB_COMPONENT,
              DHT_COMPONENT, RATE_LIMITER_COMPONENT, PAYMENT_RATE_COMPONENT, DATABASE_COMPONENT,
              conditions=[WALLET_IS_UNLOCKED])
    def jsonrpc_stream_cost_estimate(self, uri, size=None):
        """
        Get estimated cost for a lbry stream

        Usage:
            stream_cost_estimate (<uri> | --uri=<uri>) [<size> | --size=<size>]

        Options:
            --uri=<uri>      : (str) uri to use
            --size=<size>  : (float) stream size in bytes. if provided an sd blob won't be
                                     downloaded.

        Returns:
            (float) Estimated cost in lbry credits, returns None if uri is not
                resolvable
        """
        return self.get_est_cost(uri, size)

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
            if not parsed.is_channel:
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
        self.analytics_manager.send_new_channel()
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
    @defer.inlineCallbacks
    def jsonrpc_channel_export(self, claim_id):
        """
        Export serialized channel signing information for a given certificate claim id

        Usage:
            channel_export (<claim_id> | --claim_id=<claim_id>)

        Options:
            --claim_id=<claim_id> : (str) Claim ID to export information about

        Returns:
            (str) Serialized certificate information
        """

        result = yield self.wallet_manager.export_certificate_info(claim_id)
        defer.returnValue(result)

    @requires(WALLET_COMPONENT)
    @defer.inlineCallbacks
    def jsonrpc_channel_import(self, serialized_certificate_info):
        """
        Import serialized channel signing information (to allow signing new claims to the channel)

        Usage:
            channel_import (<serialized_certificate_info> | --serialized_certificate_info=<serialized_certificate_info>)

        Options:
            --serialized_certificate_info=<serialized_certificate_info> : (str) certificate info

        Returns:
            (dict) Result dictionary
        """

        result = yield self.wallet_manager.import_certificate_info(serialized_certificate_info)
        defer.returnValue(result)

    @requires(WALLET_COMPONENT, FILE_MANAGER_COMPONENT, BLOB_COMPONENT, PAYMENT_RATE_COMPONENT, DATABASE_COMPONENT,
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
        self.analytics_manager.send_claim_action('abandon')
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
        self.analytics_manager.send_claim_action('new_support')
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
        self.analytics_manager.send_claim_action('new_support')
        return result

    @AuthJSONRPCServer.deprecated()
    def jsonrpc_claim_renew(self, outpoint=None, height=None):
        pass

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
                if not parsed.is_channel:
                    results[chan_uri] = {"error": "%s is not a channel uri" % parsed.name}
                elif parsed.path:
                    results[chan_uri] = {"error": "%s is a claim in a channel" % parsed.path}
                else:
                    valid_uris += (chan_uri,)
            except URIParseError:
                results[chan_uri] = {"error": "%s is not a valid uri" % chan_uri}

        resolved = await self.wallet_manager.resolve(*valid_uris, page=page, page_size=page_size)
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

    @requires(WALLET_COMPONENT, DHT_COMPONENT, BLOB_COMPONENT, RATE_LIMITER_COMPONENT, PAYMENT_RATE_COMPONENT,
              conditions=[WALLET_IS_UNLOCKED])
    @defer.inlineCallbacks
    def jsonrpc_blob_get(self, blob_hash, timeout=None, encoding=None, payment_rate_manager=None):
        """
        Download and return a blob

        Usage:
            blob_get (<blob_hash> | --blob_hash=<blob_hash>) [--timeout=<timeout>]
                     [--encoding=<encoding>] [--payment_rate_manager=<payment_rate_manager>]

        Options:
        --blob_hash=<blob_hash>                        : (str) blob hash of the blob to get
        --timeout=<timeout>                            : (int) timeout in number of seconds
        --encoding=<encoding>                          : (str) by default no attempt at decoding
                                                         is made, can be set to one of the
                                                         following decoders:
                                                            'json'
        --payment_rate_manager=<payment_rate_manager>  : (str) if not given the default payment rate
                                                         manager will be used.
                                                         supported alternative rate managers:
                                                            'only-free'

        Returns:
            (str) Success/Fail message or (dict) decoded data
        """

        decoders = {
            'json': json.loads
        }

        timeout = timeout or 30
        blob = yield self._download_blob(blob_hash, rate_manager=self.payment_rate_manager, timeout=timeout)
        if encoding and encoding in decoders:
            blob_file = blob.open_for_reading()
            result = decoders[encoding](blob_file.read())
            blob_file.close()
        else:
            result = "Downloaded blob %s" % blob_hash

        return result

    @requires(BLOB_COMPONENT, DATABASE_COMPONENT)
    @defer.inlineCallbacks
    def jsonrpc_blob_delete(self, blob_hash):
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
            stream_hash = yield self.storage.get_stream_hash_for_sd_hash(blob_hash)
            yield self.storage.delete_stream(stream_hash)
        except Exception as err:
            pass
        yield self.blob_manager.delete_blobs([blob_hash])
        return "Deleted %s" % blob_hash

    @requires(DHT_COMPONENT)
    @defer.inlineCallbacks
    def jsonrpc_peer_list(self, blob_hash, timeout=None):
        """
        Get peers for blob hash

        Usage:
            peer_list (<blob_hash> | --blob_hash=<blob_hash>) [<timeout> | --timeout=<timeout>]

        Options:
            --blob_hash=<blob_hash>  : (str) find available peers for this blob hash
            --timeout=<timeout>      : (int) peer search timeout in seconds

        Returns:
            (list) List of contact dictionaries {'host': <peer ip>, 'port': <peer port>, 'node_id': <peer node id>}
        """

        if not is_valid_blobhash(blob_hash):
            raise Exception("invalid blob hash")

        finished_deferred = self.dht_node.iterativeFindValue(unhexlify(blob_hash))

        def trap_timeout(err):
            err.trap(defer.TimeoutError)
            return []

        finished_deferred.addTimeout(timeout or conf.settings['peer_search_timeout'], self.dht_node.clock)
        finished_deferred.addErrback(trap_timeout)
        peers = yield finished_deferred
        results = [
            {
                "node_id": hexlify(node_id).decode(),
                "host": host,
                "port": port
            }
            for node_id, host, port in peers
        ]
        return results

    @requires(DATABASE_COMPONENT)
    @defer.inlineCallbacks
    def jsonrpc_blob_announce(self, blob_hash=None, stream_hash=None, sd_hash=None):
        """
        Announce blobs to the DHT

        Usage:
            blob_announce [<blob_hash> | --blob_hash=<blob_hash>]
                          [<stream_hash> | --stream_hash=<stream_hash>] | [<sd_hash> | --sd_hash=<sd_hash>]

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
                stream_hash = yield self.storage.get_stream_hash_for_sd_hash(sd_hash)
            blobs = yield self.storage.get_blobs_for_stream(stream_hash, only_completed=True)
            blob_hashes.extend(blob.blob_hash for blob in blobs if blob.blob_hash is not None)
        else:
            raise Exception('single argument must be specified')
        yield self.storage.should_single_announce_blobs(blob_hashes, immediate=True)
        return True

    @requires(FILE_MANAGER_COMPONENT)
    @defer.inlineCallbacks
    def jsonrpc_file_reflect(self, **kwargs):
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

        reflector_server = kwargs.get('reflector', None)
        lbry_files = yield self._get_lbry_files(**kwargs)

        if len(lbry_files) > 1:
            raise Exception('Too many (%i) files found, need one' % len(lbry_files))
        elif not lbry_files:
            raise Exception('No file found')
        lbry_file = lbry_files[0]

        results = yield reupload.reflect_file(lbry_file, reflector_server=reflector_server)
        return results

    @requires(BLOB_COMPONENT, WALLET_COMPONENT)
    @defer.inlineCallbacks
    def jsonrpc_blob_list(self, uri=None, stream_hash=None, sd_hash=None, needed=None,
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
                metadata = (yield f2d(self.wallet_manager.resolve(uri)))[uri]
                sd_hash = utils.get_sd_hash(metadata)
                stream_hash = yield self.storage.get_stream_hash_for_sd_hash(sd_hash)
            elif stream_hash:
                sd_hash = yield self.storage.get_sd_blob_hash_for_stream(stream_hash)
            elif sd_hash:
                stream_hash = yield self.storage.get_stream_hash_for_sd_hash(sd_hash)
                sd_hash = yield self.storage.get_sd_blob_hash_for_stream(stream_hash)
            if stream_hash:
                crypt_blobs = yield self.storage.get_blobs_for_stream(stream_hash)
                blobs = yield defer.gatherResults([
                    self.blob_manager.get_blob(crypt_blob.blob_hash, crypt_blob.length)
                    for crypt_blob in crypt_blobs if crypt_blob.blob_hash is not None
                ])
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

    @requires(BLOB_COMPONENT)
    def jsonrpc_blob_reflect(self, blob_hashes, reflector_server=None):
        """
        Reflects specified blobs

        Usage:
            blob_reflect (<blob_hashes>...) [--reflector_server=<reflector_server>]

        Options:
            --reflector_server=<reflector_server>          : (str) reflector address

        Returns:
            (list) reflected blob hashes
        """

        d = reupload.reflect_blob_hashes(blob_hashes, self.blob_manager, reflector_server)
        d.addCallback(lambda r: self._render_response(r))
        return d

    @requires(BLOB_COMPONENT)
    def jsonrpc_blob_reflect_all(self):
        """
        Reflects all saved blobs

        Usage:
            blob_reflect_all

        Options:
            None

        Returns:
            (bool) true if successful
        """

        d = self.blob_manager.get_all_verified_blobs()
        d.addCallback(reupload.reflect_blob_hashes, self.blob_manager)
        d.addCallback(lambda r: self._render_response(r))
        return d

    @requires(DHT_COMPONENT)
    @defer.inlineCallbacks
    def jsonrpc_peer_ping(self, node_id, address=None, port=None):
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

        contact = None
        if node_id and address and port:
            contact = self.dht_node.contact_manager.get_contact(unhexlify(node_id), address, int(port))
            if not contact:
                contact = self.dht_node.contact_manager.make_contact(
                    unhexlify(node_id), address, int(port), self.dht_node._protocol
                )
        if not contact:
            try:
                contact = yield self.dht_node.findContact(unhexlify(node_id))
            except TimeoutError:
                return {'error': 'timeout finding peer'}
        if not contact:
            return {'error': 'peer not found'}
        try:
            result = (yield contact.ping()).decode()
        except TimeoutError:
            result = {'error': 'ping timeout'}
        return result

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
        result = {}
        data_store = self.dht_node._dataStore
        hosts = {}

        for k, v in data_store.items():
            for contact in map(itemgetter(0), v):
                hosts.setdefault(contact, []).append(hexlify(k).decode())

        contact_set = set()
        blob_hashes = set()
        result['buckets'] = {}

        for i in range(len(self.dht_node._routingTable._buckets)):
            for contact in self.dht_node._routingTable._buckets[i]._contacts:
                blobs = list(hosts.pop(contact)) if contact in hosts else []
                blob_hashes.update(blobs)
                host = {
                    "address": contact.address,
                    "port": contact.port,
                    "node_id": hexlify(contact.id).decode(),
                    "blobs": blobs,
                }
                result['buckets'].setdefault(i, []).append(host)
                contact_set.add(hexlify(contact.id).decode())

        result['contacts'] = list(contact_set)
        result['blob_hashes'] = list(blob_hashes)
        result['node_id'] = hexlify(self.dht_node.node_id).decode()
        return self._render_response(result)

    # the single peer downloader needs wallet access
    @requires(DHT_COMPONENT, WALLET_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    def jsonrpc_blob_availability(self, blob_hash, search_timeout=None, blob_timeout=None):
        """
        Get blob availability

        Usage:
            blob_availability (<blob_hash>) [<search_timeout> | --search_timeout=<search_timeout>]
                              [<blob_timeout> | --blob_timeout=<blob_timeout>]

        Options:
            --blob_hash=<blob_hash>           : (str) check availability for this blob hash
            --search_timeout=<search_timeout> : (int) how long to search for peers for the blob
                                                in the dht
            --blob_timeout=<blob_timeout>     : (int) how long to try downloading from a peer

        Returns:
            (dict) {
                "is_available": <bool, true if blob is available from a peer from peer list>
                "reachable_peers": ["<ip>:<port>"],
                "unreachable_peers": ["<ip>:<port>"]
            }
        """

        return self._blob_availability(blob_hash, search_timeout, blob_timeout)

    @requires(UPNP_COMPONENT, WALLET_COMPONENT, DHT_COMPONENT, conditions=[WALLET_IS_UNLOCKED])
    @defer.inlineCallbacks
    def jsonrpc_stream_availability(self, uri, search_timeout=None, blob_timeout=None):
        """
        Get stream availability for lbry uri

        Usage:
            stream_availability (<uri> | --uri=<uri>)
                                [<search_timeout> | --search_timeout=<search_timeout>]
                                [<blob_timeout> | --blob_timeout=<blob_timeout>]

        Options:
            --uri=<uri>                       : (str) check availability for this uri
            --search_timeout=<search_timeout> : (int) how long to search for peers for the blob
                                                in the dht
            --blob_timeout=<blob_timeout>   : (int) how long to try downloading from a peer

        Returns:
            (dict) {
                'is_available': <bool>,
                'did_decode': <bool>,
                'did_resolve': <bool>,
                'is_stream': <bool>,
                'num_blobs_in_stream': <int>,
                'sd_hash': <str>,
                'sd_blob_availability': <dict> see `blob_availability`,
                'head_blob_hash': <str>,
                'head_blob_availability': <dict> see `blob_availability`,
                'use_upnp': <bool>,
                'upnp_redirect_is_set': <bool>,
                'error': <None> | <str> error message
            }
        """

        search_timeout = search_timeout or conf.settings['peer_search_timeout']
        blob_timeout = blob_timeout or conf.settings['sd_download_timeout']

        response = {
            'is_available': False,
            'did_decode': False,
            'did_resolve': False,
            'is_stream': False,
            'num_blobs_in_stream': None,
            'sd_hash': None,
            'sd_blob_availability': {},
            'head_blob_hash': None,
            'head_blob_availability': {},
            'use_upnp': conf.settings['use_upnp'],
            'upnp_redirect_is_set': len(self.upnp.upnp_redirects),
            'error': None
        }

        try:
            resolved_result = (yield self.wallet_manager.resolve(uri))[uri]
            response['did_resolve'] = True
        except UnknownNameError:
            response['error'] = "Failed to resolve name"
            defer.returnValue(response)
        except URIParseError:
            response['error'] = "Invalid URI"
            defer.returnValue(response)

        try:
            claim_obj = smart_decode(resolved_result[uri]['claim']['hex'])
            response['did_decode'] = True
        except DecodeError:
            response['error'] = "Failed to decode claim value"
            defer.returnValue(response)

        response['is_stream'] = claim_obj.is_stream
        if not claim_obj.is_stream:
            response['error'] = "Claim for \"%s\" does not contain a stream" % uri
            defer.returnValue(response)

        sd_hash = claim_obj.source_hash
        response['sd_hash'] = sd_hash
        head_blob_hash = None
        downloader = self._get_single_peer_downloader()
        have_sd_blob = sd_hash in self.blob_manager.blobs
        try:
            sd_blob = yield self.jsonrpc_blob_get(sd_hash, timeout=blob_timeout,
                                                  encoding="json")
            if not have_sd_blob:
                yield self.jsonrpc_blob_delete(sd_hash)
            if sd_blob and 'blobs' in sd_blob:
                response['num_blobs_in_stream'] = len(sd_blob['blobs']) - 1
                head_blob_hash = sd_blob['blobs'][0]['blob_hash']
                head_blob_availability = yield self._blob_availability(head_blob_hash,
                                                                       search_timeout,
                                                                       blob_timeout,
                                                                       downloader)
                response['head_blob_availability'] = head_blob_availability
        except Exception as err:
            response['error'] = err
        response['head_blob_hash'] = head_blob_hash
        response['sd_blob_availability'] = yield self._blob_availability(sd_hash,
                                                                         search_timeout,
                                                                         blob_timeout,
                                                                         downloader)
        response['is_available'] = response['sd_blob_availability'].get('is_available') and \
                                   response['head_blob_availability'].get('is_available')
        defer.returnValue(response)

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
    return urllib.parse.quote(formatted_dt + milliseconds + "Z")


def get_loggly_query_string(installation_id):
    base_loggly_search_url = "https://lbry.loggly.com/search#"
    now = utils.now()
    yesterday = now - utils.timedelta(days=1)
    params = {
        'terms': 'json.installation_id:{}*'.format(installation_id[:SHORT_ID_LEN]),
        'from': loggly_time_string(yesterday),
        'to': loggly_time_string(now)
    }
    data = urllib.parse.urlencode(params)
    return base_loggly_search_url + data


def report_bug_to_slack(message, installation_id, platform_name, app_version):
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
    requests.post(webhook, json.dumps(payload))


def get_lbry_file_search_value(search_fields):
    for searchtype in FileID:
        value = search_fields.get(searchtype, None)
        if value is not None:
            return searchtype, value
    raise NoValidSearch(f'{search_fields} is missing a valid search type')


def iter_lbry_file_search_values(search_fields):
    for searchtype in FileID:
        value = search_fields.get(searchtype, None)
        if value is not None:
            yield searchtype, value


def create_key_getter(field):
    search_path = field.split('.')
    def key_getter(value):
        for key in search_path:
            try:
                value = value[key]
            except KeyError as e:
                errmsg = "Failed to get '{}', key {} was not found."
                raise Exception(errmsg.format(field, str(e)))
        return value
    return key_getter
