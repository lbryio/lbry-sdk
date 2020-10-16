import json
import time
import hashlib
import inspect
import asyncio
from typing import Union, Tuple, Callable, Optional, List, Dict
from binascii import hexlify, unhexlify
from functools import partial

import ecdsa
import base58
from aiohttp import ClientSession

from lbry.conf import Setting, NOT_SET
from lbry.db import TXO_TYPES
from lbry.db.utils import constrain_single_or_list
from lbry.wallet import Wallet, Account, SingleKey, HierarchicalDeterministic
from lbry.blockchain import Transaction, Output, dewies_to_lbc, dict_values_to_lbc
from lbry.stream.managed_stream import ManagedStream
from lbry.event import EventController, EventStream
from lbry.crypto.hash import hex_str_to_hash

from .base import Service
from .json_encoder import Paginated


DEFAULT_PAGE_SIZE = 20


async def paginate_rows(get_records: Callable, page: Optional[int], page_size: Optional[int], **constraints):
    page = max(1, page or 1)
    page_size = max(1, page_size or DEFAULT_PAGE_SIZE)
    constraints.update({
        "offset": page_size * (page - 1),
        "limit": page_size
    })
    return Paginated(await get_records(**constraints), page, page_size)


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


StrOrList = Union[str, list]
Address = Dict


kwarg_expanders = {}


def expander(m):
    assert m.__name__.startswith("extract_"), "Argument expanders must start with 'extract_'."
    name = m.__name__[len("extract_"):]
    dict_name = f"_{name}_dict"

    template = {
        k: v.default
        for (k, v) in inspect.signature(m).parameters.items()
        if v.kind != inspect.Parameter.VAR_KEYWORD
    }

    sub_expanders = {}
    for k in inspect.signature(m).parameters:
        if k.endswith('_kwargs'):
            sub_expanders = {
                f'{e}_expander': f'_{e}_dict'
                for e in k[:-7].split('_and_')
            }
            break

    def expand(**kwargs):
        d = kwargs.pop(dict_name, None)
        if d is None:
            d = template.copy()
            d.update({k: v for k, v in kwargs.items() if k in d})
        _kwargs = {k: v for k, v in kwargs.items() if k not in d}
        for expander_name, expander_dict_name in sub_expanders.items():
            _kwargs = kwarg_expanders[expander_name](**_kwargs)
            d.update(_kwargs.pop(expander_dict_name))
        return {dict_name: d, **_kwargs}

    kwarg_expanders[f'{name}_original'] = m
    kwarg_expanders[f'{name}_expander'] = expand
    return expand


def remove_nulls(d):
    return {key: val for key, val in d.items() if val is not None}


def pop_kwargs(k, d) -> Tuple[dict, dict]:
    return d.pop(f'_{k}_dict'), d


def assert_consumed_kwargs(d):
    if d:
        raise ValueError(f"Unknown argument passed: {d}")


@expander
def extract_pagination(
    page: int = None,       # page to return for paginating
    page_size: int = None,  # number of items on page for pagination
    include_total=False,    # calculate total number of items and pages
):
    pass


@expander
def extract_tx(
    wallet_id: str = None,              # restrict operation to specific wallet
    change_account_id: str = None,      # account to send excess change (LBC)
    fund_account_id: StrOrList = None,  # accounts to fund the transaction
    preview=False,                      # do not broadcast the transaction
    no_wait=False,                      # do not wait for mempool confirmation
):
    pass


@expander
def extract_claim(
    title: str = None,
    description: str = None,
    thumbnail_url: str = None,   # url to thumbnail image
    tag: StrOrList = None,
    language: StrOrList = None,  # languages used by the channel,
                                 #   using RFC 5646 format, eg:
                                 #   for English `--language=en`
                                 #   for Spanish (Spain) `--language=es-ES`
                                 #   for Spanish (Mexican) `--language=es-MX`
                                 #   for Chinese (Simplified) `--language=zh-Hans`
                                 #   for Chinese (Traditional) `--language=zh-Hant`
    location: StrOrList = None,  # locations of the channel, consisting of 2 letter
                                 #   `country` code and a `state`, `city` and a postal
                                 #   `code` along with a `latitude` and `longitude`.
                                 #   for JSON RPC: pass a dictionary with aforementioned
                                 #       attributes as keys, eg:
                                 #       ...
                                 #       "locations": [{'country': 'US', 'state': 'NH'}]
                                 #       ...
                                 #   for command line: pass a colon delimited list
                                 #       with values in the following order:
                                 #         "COUNTRY:STATE:CITY:CODE:LATITUDE:LONGITUDE"
                                 #       making sure to include colon for blank values, for
                                 #       example to provide only the city:
                                 #         ...--locations="::Manchester"
                                 #       with all values set:
                                 #        ...--locations="US:NH:Manchester:03101:42.990605:-71.460989"
                                 #       optionally, you can just pass the "LATITUDE:LONGITUDE":
                                 #         ...--locations="42.990605:-71.460989"
                                 #       finally, you can also pass JSON string of dictionary
                                 #       on the command line as you would via JSON RPC
                                 #         ...--locations="{'country': 'US', 'state': 'NH'}"
    account_id: str = None,      # account to hold the claim
    claim_address: str = None,   # specific address where the claim is held, if not specified
                                 # it will be determined automatically from the account
):
    pass


@expander
def extract_claim_edit(
    replace=False,          # instead of modifying specific values on
                            # the claim, this will clear all existing values
                            # and only save passed in values, useful for form
                            # submissions where all values are always set
    clear_tags=False,       # clear existing tags (prior to adding new ones)
    clear_languages=False,  # clear existing languages (prior to adding new ones)
    clear_locations=False,  # clear existing locations (prior to adding new ones)
):
    pass


@expander
def extract_signed(
    channel_id: str = None,    # claim id of the publishing channel
    channel_name: str = None,  # name of publishing channel
):
    pass


@expander
def extract_stream(
    file_path: str = None,      # path to file to be associated with name.
    validate_file=False,        # validate that the video container and encodings match
                                # common web browser support or that optimization succeeds if specified.
                                # FFmpeg is required
    optimize_file=False,        # transcode the video & audio if necessary to ensure
                                # common web browser support. FFmpeg is required
    fee_currency: str = None,   # specify fee currency
    fee_amount: str = None,     # content download fee
    fee_address: str = None,    # address where to send fee payments, will use
                                # the claim holding address by default
    author: str = None,         # author of the publication. The usage for this field is not
                                # the same as for channels. The author field is used to credit an author
                                # who is not the publisher and is not represented by the channel. For
                                # example, a pdf file of 'The Odyssey' has an author of 'Homer' but may
                                # by published to a channel such as '@classics', or to no channel at all
    license: str = None,        # publication license
    license_url: str = None,    # publication license url
    release_time: int = None,   # original public release of content, seconds since UNIX epoch
    width: int = None,          # image/video width, automatically calculated from media file
    height: int = None,         # image/video height, automatically calculated from media file
    duration: int = None,       # audio/video duration in seconds, automatically calculated
    **claim_and_signed_kwargs
):
    pass


@expander
def extract_stream_edit(
    clear_fee=False,      # clear fee
    clear_channel=False,  # clear channel signature
    **stream_and_claim_edit_kwargs
):
    pass


@expander
def extract_channel(
    email: str = None,           # email of channel owner
    website_url: str = None,     # website url
    cover_url: str = None,       # url to cover image
    featured: StrOrList = None,  # claim_id(s) of featured content in channel
    **claim_and_signed_kwargs
):
    pass


@expander
def extract_channel_edit(
    new_signing_key=False,  # generate a new signing key, will invalidate all previous publishes
    clear_featured=False,   # clear existing featured content (prior to adding new ones)
    **channel_and_claim_edit_kwargs
):
    pass


@expander
def extract_abandon(
    claim_id: str = None,    # claim_id of the claim to abandon
    txid: str = None,        # txid of the claim to abandon
    nout: int = 0,           # nout of the claim to abandon
    account_id: str = None,  # restrict operation to specific account, otherwise all accounts in wallet
):
    pass


@expander
def extract_claim_filter(
    name: StrOrList = None,          # claim name (normalized)
    claim_id: StrOrList = None,      # full or partial claim id
    text: str = None,                # full text search
    txid: str = None,                # transaction id
    nout: int = None,                # position in the transaction
    height: int = None,              # last updated block height (supports equality constraints)
    timestamp: int = None,           # last updated timestamp (supports equality constraints)
    creation_height: int = None,     # created at block height (supports equality constraints)
    creation_timestamp: int = None,  # created at timestamp (supports equality constraints)
    amount: str = None,              # claim amount (supports equality constraints)
    any_tag: StrOrList = None,       # containing any of the tags
    all_tag: StrOrList = None,       # containing every tag
    not_tag: StrOrList = None,       # not containing any of these tags
    any_language: StrOrList = None,  # containing any of the languages
    all_language: StrOrList = None,  # containing every language
    not_language: StrOrList = None,  # not containing any of these languages
    any_location: StrOrList = None,  # containing any of the locations
    all_location: StrOrList = None,  # containing every location
    not_location: StrOrList = None,  # not containing any of these locations
    release_time: int = None,        # limit to claims self-described as having been released
                                     # to the public on or after this UTC timestamp, when claim
                                     # does not provide a release time the publish time is used
                                     # instead (supports equality constraints)
):
    pass


@expander
def extract_signed_filter(
    channel: str = None,               # signed by this channel (argument is
                                       # a URL which automatically gets resolved),
                                       # see --channel_id if you need to filter by
                                       # multiple channels at the same time,
                                       # includes results with invalid signatures,
                                       # use in conjunction with "--valid_channel_signature"
    channel_id: StrOrList = None,      # signed by any of these channels including invalid signatures,
                                       # implies --has_channel_signature,
                                       # use in conjunction with "--valid_channel_signature"
    not_channel_id: StrOrList = None,  # exclude everything signed by any of these channels
    has_channel_signature=False,       # results with a channel signature (valid or invalid)
    valid_channel_signature=False,     # results with a valid channel signature or no signature,
                                       # use in conjunction with --has_channel_signature to
                                       # only get results with valid signatures
    invalid_channel_signature=False,   # results with invalid channel signature or no signature,
                                       # use in conjunction with --has_channel_signature to
                                       # only get results with invalid signatures
):
    pass


@expander
def extract_stream_filter(
    stream_type: StrOrList = None,  # filter by 'video', 'image', 'document', etc
    media_type: StrOrList = None,   # filter by 'video/mp4', 'image/png', etc
    fee_currency: str = None,       # specify fee currency# LBC, BTC, USD
    fee_amount: str = None,         # content download fee (supports equality constraints)
    duration: int = None,           # duration of video or audio in seconds (supports equality constraints)
    **signed_filter_kwargs
):
    pass


@expander
def extract_file_filter(
    sd_hash: str = None,           # filter by sd hash
    file_name: str = None,         # filter by file name
    stream_hash: str = None,       # filter by stream hash
    rowid: int = None,             # filter by row id
    added_on: int = None,          # filter by time of insertion
    claim_id: str = None,          # filter by claim id
    outpoint: str = None,          # filter by claim outpoint
    txid: str = None,              # filter by claim txid
    nout: int = None,              # filter by claim nout
    channel_claim_id: str = None,  # filter by channel claim id
    channel_name: str = None,      # filter by channel name
    claim_name: str = None,        # filter by claim name
    blobs_in_stream: int = None,   # filter by blobs in stream
    blobs_remaining: int = None,   # filter by number of remaining blobs to download
):
    pass


@expander
def extract_txo_filter(
    type: StrOrList = None,            # claim type: stream, channel, support, purchase, collection, repost, other
    txid: StrOrList = None,            # transaction id of outputs
    claim_id: StrOrList = None,        # claim id
    channel_id: StrOrList = None,      # claims in this channel
    name: StrOrList = None,            # claim name
    is_spent=False,                    # only show spent txos
    is_not_spent=False,                # only show not spent txos
    is_my_input_or_output=False,       # txos which have your inputs or your outputs,
                                       # if using this flag the other related flags
                                       # are ignored. ("--is_my_output", "--is_my_input", etc)
    is_my_output=False,                # show outputs controlled by you
    is_not_my_output=False,            # show outputs not controlled by you
    is_my_input=False,                 # show outputs created by you
    is_not_my_input=False,             # show outputs not created by you
    exclude_internal_transfers=False,  # excludes any outputs that are exactly this combination:
                                       # "--is_my_input" + "--is_my_output" + "--type=other"
                                       # this allows to exclude "change" payments, this
                                       # flag can be used in combination with any of the other flags
    account_id: StrOrList = None,      # id(s) of the account(s) to query
    wallet_id: str = None,             # restrict results to specific wallet
):
    pass


@expander
def extract_support_filter(
    claim_id: StrOrList = None,      # full claim id
    txid: str = None,                # transaction id
    nout: int = None,                # position in the transaction
    height: int = None,              # last updated block height (supports equality constraints)
    timestamp: int = None,           # last updated timestamp (supports equality constraints)
    amount: str = None,              # claim amount (supports equality constraints)
):
    pass


class API:
    """
    The high-level interface for the Service (either wallet server or client)
    This is hte "public" api, for CLI and stuff.
    """

    def __init__(self, service: Service):
        self.service = service
        self.wallets = service.wallets
        self.ledger = service.ledger

    async def stop(self) -> str:  # Shutdown message
        """ Stop lbrynet API server. """
        return await self.service.stop()

    async def ffmpeg_find(self) -> dict:  # ffmpeg information
        """
        Get ffmpeg installation information

        Returns:
            {
                'available': (bool) found ffmpeg,
                'which': (str) path to ffmpeg,
                'analyze_audio_volume': (bool) should ffmpeg analyze audio
            }
        """
        return await self.service.find_ffmpeg()

    async def status(self) -> dict:  # lbrynet daemon status
        """
        Get daemon status

        Returns:
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
                        'time': (float) timestamp
                    }
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
        return await self.service.get_status()

    async def version(self) -> dict:  # lbrynet version information
        """
        Get lbrynet API server version information

        Returns:
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
        return await self.service.get_version()

    async def resolve(
        self,
        urls: StrOrList,                 # one or more urls to resolve
        wallet_id: str = None,           # wallet to check for claim purchase reciepts
        include_purchase_receipt=False,  # lookup and include a receipt if this wallet
                                         # has purchased the claim being resolved
        include_is_my_output=False,      # lookup and include a boolean indicating
                                         # if claim being resolved is yours
        include_sent_supports=False,     # lookup and sum the total amount
                                         # of supports you've made to this claim
        include_sent_tips=False,         # lookup and sum the total amount
                                         # of tips you've made to this claim
        include_received_tips=False,     # lookup and sum the total amount
                                         # of tips you've received to this claim
        protobuf=False,                  # protobuf encoded result
    ) -> dict:  # resolve results, keyed by url
        """
        Get the claim that a URL refers to.

        Usage:
            resolve <urls>... [--wallet_id=<wallet_id>]
                    [--include_purchase_receipt]
                    [--include_is_my_output]
                    [--include_sent_supports]
                    [--include_sent_tips]
                    [--include_received_tips]
                    [--protobuf]

        Returns:
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
        if protobuf:
            return await self.service.protobuf_resolve(urls)
        return await self.service.resolve(
            urls, wallet=None,#self.wallets.get_or_default(wallet_id),
            include_purchase_receipt=include_purchase_receipt,
            include_is_my_output=include_is_my_output,
            include_sent_supports=include_sent_supports,
            include_sent_tips=include_sent_tips,
            include_received_tips=include_received_tips
        )

    async def get(
        self,
        uri: str,                        # uri of the content to download
        file_name: str = None,           # specified name for the downloaded file, overrides the stream file name
        download_directory: str = None,  # full path to the directory to download into
        timeout: int = None,             # download timeout in number of seconds
        save_file: bool = None,          # save the file to the downloads directory
        wallet_id: str = None            # wallet to check for claim purchase reciepts
    ) -> ManagedStream:
        """
        Download stream from a LBRY name.

        Usage:
            get <uri> [<file_name> | --file_name=<file_name>]
             [<download_directory> | --download_directory=<download_directory>]
             [<timeout> | --timeout=<timeout>]
             [--save_file] [--wallet_id=<wallet_id>]

        """
        return await self.service.get(
            uri, file_name=file_name, download_directory=download_directory,
            timeout=timeout, save_file=save_file, wallet=self.wallets.get_or_default(wallet_id)
        )

    SETTINGS_DOC = """
    Settings management.
    """

    async def settings_get(self) -> dict:  # daemon settings
        """ Get daemon settings """
        return self.service.ledger.conf.settings_dict

    async def settings_set(self, key: str, value: str) -> dict:  # updated daemon setting
        """
        Set daemon settings

        Usage:
            settings set <key> <value>

        """
        with self.service.ledger.conf.update_config() as c:
            if value and isinstance(value, str) and value[0] in ('[', '{'):
                value = json.loads(value)
            attr: Setting = getattr(type(c), key)
            cleaned = attr.deserialize(value)
            setattr(c, key, cleaned)
        return {key: cleaned}

    async def settings_clear(self, key: str) -> dict:  # updated daemon setting
        """
        Clear daemon settings

        Usage:
            settings clear (<key>)

        """
        with self.service.ledger.conf.update_config() as c:
            setattr(c, key, NOT_SET)
        return {key: self.service.ledger.conf.settings_dict[key]}

    PREFERENCE_DOC = """
    Preferences management.
    """

    async def preference_get(
        self,
        key: str = None,       # key associated with value
        wallet_id: str = None  # restrict operation to specific wallet
    ) -> dict:  # preferences
        """
        Get preference value for key or all values if not key is passed in.

        Usage:
            preference get [<key>] [--wallet_id=<wallet_id>]

        """
        wallet = self.wallets.get_or_default(wallet_id)
        if key:
            if key in wallet.preferences:
                return {key: wallet.preferences[key]}
            return {}
        return wallet.preferences.to_dict_without_ts()

    async def preference_set(
        self,
        key: str,              # key for the value
        value: str,            # the value itself
        wallet_id: str = None  # restrict operation to specific wallet
    ) -> dict:  # updated user preference
        """
        Set preferences

        Usage:
            preference set (<key>) (<value>) [--wallet_id=<wallet_id>]

        """
        wallet = self.wallets.get_or_default(wallet_id)
        if value and isinstance(value, str) and value[0] in ('[', '{'):
            value = json.loads(value)
        wallet.preferences[key] = value
        wallet.save()
        return {key: value}

    WALLET_DOC = """
    Create, modify and inspect wallets.
    """

    async def wallet_list(
        self,
        wallet_id: str = None,  # show specific wallet only
        **pagination_kwargs
    ) -> Paginated[Wallet]:
        """
        List wallets.

        Usage:
            wallet list [--wallet_id=<wallet_id>] [--page=<page>] [--page_size=<page_size>]

        """
        if wallet_id:
            return paginate_list([self.wallets.get_wallet_or_error(wallet_id)], 1, 1)
        return paginate_list(self.wallets.wallets, **pagination_kwargs)

    async def wallet_reconnect(self):
        """ Reconnects ledger network client, applying new configurations. """
        return self.wallets.reset()

    async def wallet_create(
        self,
        wallet_id: str,         # wallet file name
        skip_on_startup=False,  # don't add wallet to daemon_settings.yml
        create_account=False,   # generates the default account
        single_key=False        # used with --create_account, creates single-key account
    ) -> Wallet:  # newly created wallet
        """
        Create a new wallet.

        Usage:
            wallet create (<wallet_id> | --wallet_id=<wallet_id>) [--skip_on_startup]
                          [--create_account] [--single_key]

        """
        wallet_path = os.path.join(self.conf.wallet_dir, 'wallets', wallet_id)
        for wallet in self.wallets.wallets:
            if wallet.id == wallet_id:
                raise Exception(f"Wallet at path '{wallet_path}' already exists and is loaded.")
        if os.path.exists(wallet_path):
            raise Exception(f"Wallet at path '{wallet_path}' already exists, use 'wallet_add' to load wallet.")

        wallet = self.wallets.import_wallet(wallet_path)
        if not wallet.accounts and create_account:
            account = Account.generate(
                self.ledger, wallet, address_generator={
                    'name': SingleKey.name if single_key else HierarchicalDeterministic.name
                }
            )
            if self.ledger.sync.network.is_connected:
                await self.ledger.subscribe_account(account)
        wallet.save()
        if not skip_on_startup:
            with self.conf.update_config() as c:
                c.wallets += [wallet_id]
        return wallet

    async def wallet_add(
        self,
        wallet_id: str  # wallet file name
    ) -> Wallet:  # added wallet
        """
        Add existing wallet.

        Usage:
            wallet add (<wallet_id> | --wallet_id=<wallet_id>)

        """
        wallet_path = os.path.join(self.conf.wallet_dir, 'wallets', wallet_id)
        for wallet in self.wallets.wallets:
            if wallet.id == wallet_id:
                raise Exception(f"Wallet at path '{wallet_path}' is already loaded.")
        if not os.path.exists(wallet_path):
            raise Exception(f"Wallet at path '{wallet_path}' was not found.")
        wallet = self.wallets.import_wallet(wallet_path)
        if self.ledger.sync.network.is_connected:
            for account in wallet.accounts:
                await self.ledger.subscribe_account(account)
        return wallet

    async def wallet_remove(
        self,
        wallet_id: str  # id of wallet to remove
    ) -> Wallet:  # removed wallet
        """
        Remove an existing wallet.

        Usage:
            wallet remove (<wallet_id> | --wallet_id=<wallet_id>)

        """
        wallet = self.wallets.get_wallet_or_error(wallet_id)
        self.wallets.wallets.remove(wallet)
        for account in wallet.accounts:
            await self.ledger.unsubscribe_account(account)
        return wallet

    async def wallet_balance(
        self,
        wallet_id: str = None,  # balance for specific wallet, other than default wallet
        confirmations=0         # only include transactions with this many confirmed blocks.
    ) -> dict:
        """
        Return the balance of a wallet

        Usage:
            wallet balance [<wallet_id>] [--confirmations=<confirmations>]

        """
        wallet = self.wallets.get_or_default(wallet_id)
        balance = await self.ledger.get_detailed_balance(
            accounts=wallet.accounts, confirmations=confirmations
        )
        return dict_values_to_lbc(balance)

    async def wallet_status(
        self,
        wallet_id: str = None  # status of specific wallet
    ) -> dict:  # status of the wallet
        """
        Status of wallet including encryption/lock state.

        Usage:
            wallet status [<wallet_id> | --wallet_id=<wallet_id>]

        Returns:
            {'is_encrypted': (bool), 'is_syncing': (bool), 'is_locked': (bool)}
        """
        if self.wallets is None:
            return {'is_encrypted': None, 'is_syncing': None, 'is_locked': None}
        wallet = self.wallets.get_or_default(wallet_id)
        return {
            'is_encrypted': wallet.is_encrypted,
            'is_syncing': len(self.ledger._update_tasks) > 0,
            'is_locked': wallet.is_locked
        }

    async def wallet_unlock(
        self,
        password: str,         # password to use for unlocking
        wallet_id: str = None  # restrict operation to specific wallet
    ) -> bool:  # true if wallet has become unlocked
        """
        Unlock an encrypted wallet

        Usage:
            wallet unlock (<password> | --password=<password>) [--wallet_id=<wallet_id>]

        """
        return self.wallets.get_or_default(wallet_id).unlock(password)

    async def wallet_lock(
        self,
        wallet_id: str = None  # restrict operation to specific wallet
    ) -> bool:  # true if wallet has become locked
        """
        Lock an unlocked wallet

        Usage:
            wallet lock [--wallet_id=<wallet_id>]

        """
        return self.wallets.get_or_default(wallet_id).lock()

    async def wallet_decrypt(
        self,
        wallet_id: str = None  # restrict operation to specific wallet
    ) -> bool:  # true if wallet has been decrypted
        """
        Decrypt an encrypted wallet, this will remove the wallet password. The wallet must be unlocked to decrypt it

        Usage:
            wallet decrypt [--wallet_id=<wallet_id>]

        """
        return await self.wallets.get_or_default(wallet_id).decrypt()

    async def wallet_encrypt(
        self,
        new_password: str,     # password to encrypt account
        wallet_id: str = None  # restrict operation to specific wallet
    ) -> bool:  # true if wallet has been encrypted
        """
        Encrypt an unencrypted wallet with a password

        Usage:
            wallet encrypt (<new_password> | --new_password=<new_password>)
                           [--wallet_id=<wallet_id>]

        """
        return await self.wallets.get_or_default(wallet_id).encrypt(new_password)

    async def wallet_send(
        self,
        amount: str,           # amount to send to each address
        addresses: StrOrList,  # addresses to send amounts to
        **tx_kwargs
    ) -> Transaction:
        """
        Send the same number of credits to multiple addresses using all accounts in wallet to
        fund the transaction and the default account to receive any change.

        Usage:
            wallet send <amount> <addresses>...
                        {kwargs}

        """
        args = transaction(**transaction_kwargs)
        wallet = self.wallets.get_or_default_for_spending(args['wallet_id'])
        account = wallet.accounts.get_or_default(args['change_account_id'])
        accounts = wallet.accounts.get_or_all(args['funding_account_id'])
        amount = self.ledger.get_dewies_or_error("amount", amount)
        if addresses and not isinstance(addresses, list):
            addresses = [addresses]
        outputs = []
        for address in addresses:
            self.ledger.valid_address_or_error(address)
            outputs.append(
                Output.pay_pubkey_hash(
                    amount, self.ledger.address_to_hash160(address)
                )
            )
        tx = await wallet.create_transaction([], outputs, accounts, account)
        await wallet.sign(tx)
        await self.service.maybe_broadcast_or_release(tx, args['blocking'], args['preview'])
        return tx

    ACCOUNT_DOC = """
    Create, modify and inspect wallet accounts.
    """

    async def account_list(
        self,
        account_id: str = None,  # show specific wallet only
        wallet_id: str = None,   # restrict operation to specific wallet
        confirmations=0,         # required confirmations for account balance
        include_seed=False,      # include the seed phrase of the accounts
        **pagination_kwargs
    ) -> Paginated[Account]:  # paginated accounts
        """
        List details of all of the accounts or a specific account.

        Usage:
            account list [<account_id>] [--wallet_id=<wallet_id>]
                         [--confirmations=<confirmations>] [--include_seed]
                         {kwargs}

        """
        kwargs = {'confirmations': confirmations, 'show_seed': include_seed}
        wallet = self.wallets.get_or_default(wallet_id)
        if account_id:
            return paginate_list([await wallet.get_account_or_error(account_id).get_details(**kwargs)], 1, 1)
        else:
            return paginate_list(await wallet.get_detailed_accounts(**kwargs), **pagination_kwargs)

    async def account_balance(
        self,
        account_id: str = None,  # balance for specific account, default otherwise
        wallet_id: str = None,   # restrict operation to specific wallet
        confirmations=0          # required confirmations of transactions included
    ) -> dict:
        """
        Return the balance of an account

        Usage:
            account balance [<account_id>] [--wallet_id=<wallet_id>] [--confirmations=<confirmations>]

        """
        wallet = self.wallets.get_or_default(wallet_id)
        account = wallet.accounts.get_or_default(account_id)
        balance = await account.get_detailed_balance(
            confirmations=confirmations, reserved_subtotals=True,
        )
        return dict_values_to_lbc(balance)

    async def account_add(
        self,
        account_name: str,        # name of the account being add
        wallet_id: str = None,    # add account to specific wallet
        single_key=False,         # create single key account, default is multi-key
        seed: str = None,         # seed to generate account from
        private_key: str = None,  # private key of account
        public_key: str = None    # public key of account
    ) -> Account:  # added account
        """
        Add a previously created account from a seed, private key or public key (read-only).
        Specify --single_key for single address or vanity address accounts.

        Usage:
            account add (<account_name> | --account_name=<account_name>)
                 (--seed=<seed> | --private_key=<private_key> | --public_key=<public_key>)
                 [--single_key] [--wallet_id=<wallet_id>]

        """
        wallet = self.wallets.get_or_default(wallet_id)
        account = await Account.from_dict(
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
        if self.ledger.sync.network.is_connected:
            await self.ledger.subscribe_account(account)
        return account

    async def account_create(
        self,
        account_name: str,     # name of the account being created
        language='en',         # language to use for seed phrase words,
                               # available languages: en, fr, it, ja, es, zh
        single_key=False,      # create single key account, default is multi-key
        wallet_id: str = None  # create account in specific wallet
    ) -> Account:  # created account
        """
        Create a new account. Specify --single_key if you want to use
        the same address for all transactions (not recommended).

        Usage:
            account create (<account_name> | --account_name=<account_name>)
                           [--language=<language>]
                           [--single_key] [--wallet_id=<wallet_id>]

        """
        wallet = self.wallets.get_or_default(wallet_id)
        account = await wallet.accounts.generate(account_name, language, {
            'name': SingleKey.name if single_key else HierarchicalDeterministic.name
        })
        await wallet.save()
        # TODO: fix
        #if self.ledger.sync.network.is_connected:
        #    await self.ledger.sync.subscribe_account(account)
        return account

    async def account_remove(
        self,
        account_id: str,       # id of account to remove
        wallet_id: str = None  # remove account from specific wallet
    ) -> Account:  # removed account
        """
        Remove an existing account.

        Usage:
            account remove (<account_id> | --account_id=<account_id>) [--wallet_id=<wallet_id>]

        """
        wallet = self.wallets.get_or_default(wallet_id)
        account = wallet.accounts.get_account_or_error(account_id)
        wallet.accounts.remove(account)
        await wallet.save()
        return account

    async def account_set(
        self,
        account_id: str,                # id of account to modify
        wallet_id: str = None,          # restrict operation to specific wallet
        default=False,                  # make this account the default
        new_name: str = None,           # new name for the account
        change_gap: int = None,         # set the gap for change addresses
        change_max_uses: int = None,    # set the maximum number of times to
        receiving_gap: int = None,      # set the gap for receiving addresses use a change address
        receiving_max_uses: int = None  # set the maximum number of times to use a receiving address
    ) -> Account:  # modified account
        """
        Change various settings on an account.

        Usage:
            account set (<account_id> | --account_id=<account_id>) [--wallet_id=<wallet_id>]
                [--default] [--new_name=<new_name>]
                [--change_gap=<change_gap>] [--change_max_uses=<change_max_uses>]
                [--receiving_gap=<receiving_gap>] [--receiving_max_uses=<receiving_max_uses>]

        """
        wallet = self.wallets.get_or_default(wallet_id)
        account = wallet.get_account_or_error(account_id)
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

        if default and wallet.default_account != account:
            wallet.accounts.remove(account)
            wallet.accounts.insert(0, account)
            change_made = True

        if change_made:
            account.modified_on = time.time()
            await wallet.save()

        return account

    async def account_max_address_gap(
        self,
        account_id: str,       # account for which to get max gaps
        wallet_id: str = None  # restrict operation to specific wallet
    ) -> dict:  # maximum gap for change and receiving addresses
        """
        Finds ranges of consecutive addresses that are unused and returns the length
        of the longest such range: for change and receiving address chains. This is
        useful to figure out ideal values to set for 'receiving_gap' and 'change_gap'
        account settings.

        Usage:
            account max_address_gap (<account_id> | --account_id=<account_id>)
                                    [--wallet_id=<wallet_id>]

        Returns:
            {
                'max_change_gap': (int),
                'max_receiving_gap': (int),
            }
        """
        return await self.wallets.get_or_default(wallet_id).accounts[account_id].get_max_gap()

    async def account_fund(
        self,
        to_account: str = None,    # send to this account
        from_account: str = None,  # spend from this account
        amount='0.0',              # the amount of LBC to transfer
        everything=False,          # transfer everything (excluding claims)
        outputs=1,                 # split payment across many outputs
        broadcast=False,           # broadcast the transaction
        wallet_id: str = None      # restrict operation to specific wallet
    ) -> Transaction:
        """
        Transfer some amount (or --everything) to an account from another
        account (can be the same account). Amounts are interpreted as LBC.
        You can also spread the transfer across a number of --outputs (cannot
        be used together with --everything).

        Usage:
            account fund [<to_account> | --to_account=<to_account>]
                [<from_account> | --from_account=<from_account>]
                (<amount> | --amount=<amount> | --everything)
                [<outputs> | --outputs=<outputs>] [--wallet_id=<wallet_id>]
                [--broadcast]

        """
        wallet = self.wallets.get_or_default(wallet_id)
        to_account = wallet.accounts.get_or_default(to_account)
        from_account = wallet.accounts.get_or_default(from_account)
        amount = self.ledger.get_dewies_or_error('amount', amount) if amount else None
        if not isinstance(outputs, int):
            raise ValueError("--outputs must be an integer.")
        if everything and outputs > 1:
            raise ValueError("Using --everything along with --outputs is not supported.")
        return await from_account.fund(
            to_account=to_account, amount=amount, everything=everything,
            outputs=outputs, broadcast=broadcast
        )

    SYNC_DOC = """
    Wallet synchronization.
    """

    async def sync_hash(
        self,
        wallet_id: str = None  # wallet for which to generate hash
    ) -> str:  # sha256 hash of wallet
        """
        Deterministic hash of the wallet.

        Usage:
            sync hash [<wallet_id> | --wallet_id=<wallet_id>]

        """
        wallet = self.wallets.get_or_default(wallet_id)
        return hexlify(wallet.hash).decode()

    async def sync_apply(
        self,
        password: str,          # password to decrypt incoming and encrypt outgoing data
        data: str = None,       # incoming sync data, if any
        wallet_id: str = None,  # wallet being sync'ed
        blocking=False          # wait until any new accounts have sync'ed
    ) -> dict:  # sync hash and data
        """
        Apply incoming synchronization data, if provided, and return a sync hash and update wallet data.

        Wallet must be unlocked to perform this operation.

        If "encrypt-on-disk" preference is True and supplied password is different from local password,
        or there is no local password (because local wallet was not encrypted), then the supplied password
        will be used for local encryption (overwriting previous local encryption password).

        Usage:
            sync apply <password> [--data=<data>] [--wallet_id=<wallet_id>] [--blocking]

        Returns:
            {
                'hash': (str) hash of wallet,
                'data': (str) encrypted wallet
            }
        """
        wallet = self.wallets.get_or_default(wallet_id)
        wallet_changed = False
        if data is not None:
            added_accounts = await wallet.merge(self.wallets, password, data)
            if added_accounts and self.ledger.sync.network.is_connected:
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
            'hash': self.sync_hash(wallet_id),
            'data': encrypted.decode()
        }

    ADDRESS_DOC = """
    List, generate and verify addresses. Golomb-Rice coding filters for addresses.
    """

    async def address_is_mine(
        self,
        address: str,            # address to check
        account_id: str = None,  # id of the account to use
        wallet_id: str = None    # restrict operation to specific wallet
    ) -> bool:  # if address is associated with current wallet
        """
        Checks if an address is associated with the current wallet.

        Usage:
            address is_mine (<address> | --address=<address>)
                            [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]

        """
        wallet = self.wallets.get_or_default(wallet_id)
        account = wallet.accounts.get_or_default(account_id)
        match = await self.ledger.db.get_address(address=address, accounts=[account])
        if match is not None:
            return True
        return False

    async def address_list(
        self,
        address: str = None,     # just show details for single address
        account_id: str = None,  # id of the account to use
        wallet_id: str = None,   # restrict operation to specific wallet
        **pagination_kwargs
    ) -> Paginated[Address]:
        """
        List account addresses or details of single address.

        Usage:
            address list [--address=<address>] [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                         {kwargs}

        """
        wallet = self.wallets.get_or_default(wallet_id)
        constraints = {}
        if address:
            constraints['address'] = address
        if account_id:
            constraints['accounts'] = [wallet.get_account_or_error(account_id)]
        else:
            constraints['accounts'] = wallet.accounts
        return await paginate_rows(
            self.ledger.get_addresses,
            **pagination_kwargs, **constraints
        )

    async def address_unused(
        self,
        account_id: str = None,  # id of the account to use
        wallet_id: str = None    # restrict operation to specific wallet
    ) -> str:  # unused address
        """
        Return an address containing no balance, will create
        a new address if there is none.

        Usage:
            address_unused [--account_id=<account_id>] [--wallet_id=<wallet_id>]

        """
        return await (
            self.wallets.get_or_default(wallet_id)
            .accounts.get_or_default(account_id)
            .receiving.get_or_create_usable_address()
        )

    async def address_block_filters(self):
        return await self.service.get_block_address_filters()

    async def address_transaction_filters(self, block_hash: str):
        return await self.service.get_transaction_address_filters(block_hash)

    FILE_DOC = """
    File management.
    """

    async def file_list(
        self,
        wallet_id: str = None,   # add purchase receipts from this wallet
        sort: str = None,        # field to sort by
        reverse=False,           # reverse sort order
        comparison: str = None,  # logical comparison, (eq|ne|g|ge|l|le)
        **file_filter_and_pagination_kwargs
    ) -> Paginated[ManagedStream]:
        """
        List files limited by optional filters

        Usage:
            file list [--wallet_id=<wallet_id>]
                      [--sort=<sort_by>] [--reverse] [--comparison=<comparison>]
                      {kwargs}

        """
        kwargs = file_filter_and_pagination_kwargs
        page, page_size = kwargs.pop('page', None), kwargs.pop('page', None)
        wallet = self.wallets.get_or_default(wallet_id)
        sort = sort or 'rowid'
        comparison = comparison or 'eq'
        paginated = paginate_list(
            self.stream_manager.get_filtered_streams(sort, reverse, comparison, **kwargs), page, page_size
        )
        if paginated['items']:
            receipts = {
                txo.purchased_claim_id: txo for txo in
                await self.ledger.db.get_purchases(
                    accounts=wallet.accounts,
                    purchased_claim_hash__in=[unhexlify(s.claim_id)[::-1] for s in paginated['items']]
                )
            }
            for stream in paginated['items']:
                stream.purchase_receipt = receipts.get(stream.claim_id)
        return paginated

    async def file_set_status(
        self,
        status: str,  # one of "start" or "stop"
        **file_filter_kwargs
    ) -> str:  # confirmation message
        """
        Start or stop downloading a file

        Usage:
            file set_status (<status> | --status=<status>)
                            {kwargs}

        """
        if status not in ['start', 'stop']:
            raise Exception('Status must be "start" or "stop".')

        streams = self.stream_manager.get_filtered_streams(**file_filter_kwargs)
        if not streams:
            raise Exception(f'Unable to find a file for {file_filter_kwargs}')
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

    async def file_delete(
        self,
        delete_from_download_dir=False,  # delete file from download directory, instead of just deleting blobs
        delete_all=False,                # if there are multiple matching files, allow the deletion of multiple files.
                                         # otherwise do not delete anything.
        **file_filter_kwargs
    ) -> bool:  # true if deletion was successful
        """
        Delete a LBRY file

        Usage:
            file delete [--delete_from_download_dir] [--delete_all]
                        {kwargs}

        """

        streams = self.stream_manager.get_filtered_streams(**file_filter_kwargs)

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

    async def file_save(
        self,
        download_directory: str = None,
        **file_filter_kwargs
    ) -> ManagedStream:  # file being saved to disk
        """
        Start saving a file to disk.

        Usage:
            file save [--download_directory=<download_directory>]
                      {kwargs}

        """

        streams = self.stream_manager.get_filtered_streams(**file_filter_kwargs)

        if len(streams) > 1:
            log.warning("There are %i matching files, use narrower filters to select one", len(streams))
            return
        if not streams:
            log.warning("There is no file to save")
            return
        stream = streams[0]
        await stream.save_file(file_filter_kwargs.get('file_name'), download_directory)
        return stream

    PURCHASE_DOC = """
    List and make purchases of claims.
    """

    async def purchase_list(
        self,
        claim_id: str = None,    # purchases for specific claim
        resolve=False,           # include resolved claim information
        account_id: str = None,  # restrict operation to specific account, otherwise all accounts in wallet
        wallet_id: str = None,   # restrict operation to specific wallet
        **pagination_kwargs
    ) -> Paginated[Output]:  # purchase outputs
        """
        List my claim purchases.

        Usage:
            purchase list [<claim_id> | --claim_id=<claim_id>] [--resolve]
                          [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                          {kwargs}

        """
        wallet = self.wallets.get_or_default(wallet_id)
        constraints = {
            "wallet": wallet,
            "accounts": [wallet.get_account_or_error(account_id)] if account_id else wallet.accounts,
            "resolve": resolve,
        }
        if claim_id:
            constraints["purchased_claim_id"] = claim_id
        return await paginate_rows(
            self.ledger.get_purchases,
            page, page_size, **constraints
        )

    async def purchase_create(
        self,
        claim_id: str = None,            # claim id of claim to purchase
        url: str = None,                 # lookup claim to purchase by url
        allow_duplicate_purchase=False,  # allow purchasing claim_id you already own
        override_max_key_fee=False,      # ignore max key fee for this purchase
        **tx_kwargs
    ) -> Transaction:  # purchase transaction
        """
        Purchase a claim.

        Usage:
            purchase create (--claim_id=<claim_id> | --url=<url>)
                            [--allow_duplicate_purchase] [--override_max_key_fee]
                            {kwargs}

        """
        wallet = self.wallets.get_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        accounts = wallet.accounts.get_or_all(fund_account_id)
        txo = None
        if claim_id:
            txo = await self.ledger.get_claim_by_claim_id(accounts, claim_id, include_purchase_receipt=True)
            if not isinstance(txo, Output) or not txo.is_claim:
                raise Exception(f"Could not find claim with claim_id '{claim_id}'. ")
        elif url:
            txo = (await self.ledger.resolve(accounts, [url], include_purchase_receipt=True))[url]
            if not isinstance(txo, Output) or not txo.is_claim:
                raise Exception(f"Could not find claim with url '{url}'. ")
        else:
            raise Exception(f"Missing argument claim_id or url. ")
        if not allow_duplicate_purchase and txo.purchase_receipt:
            raise Exception(
                f"You already have a purchase for claim_id '{claim_id}'. "
                f"Use --allow-duplicate-purchase flag to override."
            )
        claim = txo.claim
        if not claim.is_stream or not claim.stream.has_fee:
            raise Exception(f"Claim '{claim_id}' does not have a purchase price.")
        tx = await self.wallets.create_purchase_transaction(
            accounts, txo, self.exchange_rate_manager, override_max_key_fee
        )
        await self.service.maybe_broadcast_or_release(tx, blocking, preview)
        return tx

    CLAIM_DOC = """
    List and search all types of claims.
    """

    async def claim_list(
        self,
        claim_type: str = None,       # claim type: channel, stream, repost, collection
        account_id: str = None,       # restrict operation to specific account, otherwise all accounts in wallet
        wallet_id: str = None,        # restrict operation to specific wallet
        is_spent=False,               # shows previous claim updates and abandons
        resolve=False,                # resolves each claim to provide additional metadata
        include_received_tips=False,  # calculate the amount of tips recieved for claim outputs
        **claim_filter_and_stream_filter_and_pagination_kwargs
    ) -> Paginated[Output]:  # streams and channels in wallet
        """
        List my stream and channel claims.

        Usage:
            claim list [--account_id=<account_id>] [--wallet_id=<wallet_id>]
                       [--is_spent] [--resolve] [--include_received_tips]
                       {kwargs}

        """
        kwargs = claim_filter_and_and_signed_filter_and_stream_filter_and_channel_filter_and_pagination_kwargs
        kwargs['type'] = claim_type or CLAIM_TYPE_NAMES
        if 'is_spent' not in kwargs:
            kwargs['is_not_spent'] = True
        return await self.txo_list(**kwargs)

    async def claim_search(
        self,
        wallet_id: str = None,           # wallet to check for claim purchase reciepts
        claim_type: str = None,          # claim type: channel, stream, repost, collection
        include_purchase_receipt=False,  # lookup and include a receipt if this wallet has purchased the claim
        include_is_my_output=False,      # lookup and include a boolean indicating if claim being resolved is yours
        is_controlling=False,            # winning claims of their respective name
        activation_height: int = None,   # height at which claim starts competing for name
                                         # (supports equality constraints)
        expiration_height: int = None,   # height at which claim will expire (supports equality constraints)
        support_amount: str = None,      # limit by supports and tips received (supports equality constraints)
        effective_amount: str = None,    # limit by total value (initial claim value plus all tips and supports
                                         # received), this amount is blank until claim has reached activation
                                         # height (supports equality constraints)
        trending_group: int = None,      # group numbers 1 through 4 representing the trending groups of the
                                         # content: 4 means content is trending globally and independently,
                                         # 3 means content is not trending globally but is trending
                                         # independently (locally), 2 means it is trending globally but not
                                         # independently and 1 means it's not trending globally or locally (supports
                                         # equality constraints)
        trending_mixed: int = None,      # trending amount taken from the global or local value depending on the
                                         # trending group: 4 - global value, 3 - local value, 2 - global value,
                                         # 1 - local value (supports equality constraints)
        trending_local: int = None,      # trending value calculated relative only to the individual contents past
                                         # history (supports equality constraints)
        trending_global: int = None,     # trending value calculated relative to all trending content globally
                                         # (supports equality constraints)
        public_key_id: str = None,       # only return channels having this public key id, this is the same key
                                         # as used in the wallet file to map channel certificate private keys:
                                         # {'public_key_id': 'private key'}
        reposted_claim_id: str = None,   # all reposts of the specified original claim id
        reposted: int = None,            # claims reposted this many times (supports equality constraints)
        order_by: StrOrList = None,      # field to order by, default is descending order, to do an ascending order
                                         # prepend ^ to the field name, eg. '^amount' available fields: 'name',
                                         # 'height', 'release_time', 'publish_time', 'amount', 'effective_amount',
                                         # 'support_amount', 'trending_group', 'trending_mixed', 'trending_local',
                                         # 'trending_global', 'activation_height'
        protobuf=False,                  # protobuf encoded result
        **claim_filter_and_stream_filter_and_pagination_kwargs
    ) -> Paginated[Output]:  # search results
        """
        Search for stream and channel claims on the blockchain.

        Arguments marked with "supports equality constraints" allow prepending the
        value with an equality constraint such as '>', '>=', '<' and '<='
        eg. --height=">400000" would limit results to only claims above 400k block height.

        Usage:
            claim search
                         [--is_controlling] [--public_key_id=<public_key_id>]
                         [--creation_height=<creation_height>]
                         [--activation_height=<activation_height>] [--expiration_height=<expiration_height>]
                         [--effective_amount=<effective_amount>]
                         [--support_amount=<support_amount>] [--trending_group=<trending_group>]
                         [--trending_mixed=<trending_mixed>] [--trending_local=<trending_local>]
                         [--trending_global=<trending_global]
                         [--reposted_claim_id=<reposted_claim_id>] [--reposted=<reposted>]
                         [--claim_type=<claim_type>] [--order_by=<order_by>...]
                         [--wallet_id=<wallet_id>] [--include_purchase_receipt] [--include_is_my_output]
                         [--protobuf]
                         {kwargs}

        """
        claim_filter_dict, kwargs = pop_kwargs('claim_filter', extract_claim_filter(
            **claim_filter_and_stream_filter_and_pagination_kwargs
        ))
        pagination, kwargs = pop_kwargs('pagination', extract_pagination(**kwargs))
        wallet = self.wallets.get_or_default(wallet_id)
#        if {'claim_id', 'claim_ids'}.issubset(kwargs):
#            raise ValueError("Only 'claim_id' or 'claim_ids' is allowed, not both.")
#        if kwargs.pop('valid_channel_signature', False):
#            kwargs['signature_valid'] = 1
#        if kwargs.pop('invalid_channel_signature', False):
#            kwargs['signature_valid'] = 0
        page_num = abs(pagination['page'] or 1)
        page_size = min(abs(pagination['page_size'] or DEFAULT_PAGE_SIZE), 50)
        claim_filter_dict.update({
            'offset': page_size * (page_num - 1), 'limit': page_size,
            'include_total': pagination['include_total'],
            'order_by': order_by
        })
        if protobuf:
            return await self.service.protobuf_search_claims(**remove_nulls(claim_filter_dict))
        result = await self.service.search_claims(
            wallet.accounts, **remove_nulls(claim_filter_dict)
        )
        d = {
            "items": result.rows,
            #"blocked": censored,
            "page": page_num,
            "page_size": page_size
        }
        if pagination['include_total']:
            d['total_pages'] = int((result.total + (page_size - 1)) / page_size)
            d['total_items'] = result.total
        return d

    CHANNEL_DOC = """
    Create, update, abandon and list your channel claims.
    """

    async def channel_create(
        self,
        name: str,                   # name of the channel prefixed with '@'
        bid: str,                    # amount to back the channel
        allow_duplicate_name=False,  # create new channel even if one already exists with given name
        **channel_and_tx_kwargs
    ) -> Transaction:  # new channel transaction
        """
        Create a new channel by generating a channel private key and establishing an '@' prefixed claim.

        Usage:
            channel create (<name>) (<bid> | --bid=<bid>) [--allow_duplicate_name]
                           {kwargs}

        """
        channel_dict, kwargs = pop_kwargs('channel', extract_channel(**channel_and_tx_kwargs))
        tx_dict, kwargs = pop_kwargs('tx', extract_tx(**kwargs))
        assert_consumed_kwargs(kwargs)
        self.ledger.valid_channel_name_or_error(name)
        wallet = self.wallets.get_or_default_for_spending(tx_dict.pop('wallet_id'))
        amount = self.ledger.get_dewies_or_error('bid', bid, positive_value=True)
        holding_account = wallet.accounts.get_or_default(channel_dict.pop('account_id'))
        funding_accounts = wallet.accounts.get_or_all(tx_dict.pop('fund_account_id'))
        await wallet.verify_duplicate(name, allow_duplicate_name)
        tx = await wallet.channels.create(
            name=name, amount=amount, holding_account=holding_account, funding_accounts=funding_accounts,
            save_key=not tx_dict['preview'], **remove_nulls(channel_dict)
        )
        await self.service.maybe_broadcast_or_release(tx, tx_dict['preview'], tx_dict['no_wait'])
        return tx

    async def channel_update(
        self,
        claim_id: str,            # claim_id of the channel to update
        bid: str = None,          # update amount backing the channel
        **channel_edit_and_tx_kwargs
    ) -> Transaction:  # transaction updating the channel
        """
        Update an existing channel claim.

        Usage:
            channel update (<claim_id> | --claim_id=<claim_id>) [<bid> | --bid=<bid>]
                           [--new_signing_key] [--clear_featured]
                           {kwargs}

        """
        channel_edit_dict, kwargs = pop_kwargs(
            'channel_edit', extract_channel_edit(**channel_edit_and_tx_kwargs))
        tx_dict, kwargs = pop_kwargs('tx', extract_tx(**kwargs))
        assert_consumed_kwargs(kwargs)
        wallet = self.wallets.get_or_default_for_spending(tx_dict.pop('wallet_id'))
        holding_account = wallet.accounts.get_or_none(channel_edit_dict.pop('account_id'))
        funding_accounts = wallet.accounts.get_or_all(tx_dict.pop('fund_account_id'))

        old = await wallet.claims.get(claim_id=claim_id)
        if not old.claim.is_channel:
            raise Exception(
                f"A claim with id '{claim_id}' was found but "
                f"it is not a channel."
            )

        if bid is not None:
            amount = self.ledger.get_dewies_or_error('bid', bid, positive_value=True)
        else:
            amount = old.amount

        tx = await wallet.channels.update(
            old=old, amount=amount, holding_account=holding_account, funding_accounts=funding_accounts,
            save_key=not tx_dict['preview'], **remove_nulls(channel_edit_dict)
        )

        await self.service.maybe_broadcast_or_release(tx, tx_dict['blocking'], tx_dict['preview'])

        return tx

    async def channel_abandon(
        self, **abandon_and_tx_kwargs
    ) -> Transaction:  # transaction abandoning the channel
        """
        Abandon one of my channel claims.

        Usage:
            channel abandon
                            {kwargs}

        """
        wallet = self.wallets.get_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        if account_id:
            account = wallet.get_account_or_error(account_id)
            accounts = [account]
        else:
            account = wallet.default_account
            accounts = wallet.accounts

        if txid is not None and nout is not None:
            claims = await self.ledger.get_claims(
                wallet=wallet, accounts=accounts, tx_hash=unhexlify(txid)[::-1], position=nout
            )
        elif claim_id is not None:
            claims = await self.ledger.get_claims(
                wallet=wallet, accounts=accounts, claim_id=claim_id
            )
        else:
            raise Exception('Must specify claim_id, or txid and nout')

        if not claims:
            raise Exception('No claim found for the specified claim_id or txid:nout')

        tx = await Transaction.create(
            [Input.spend(txo) for txo in claims], [], [account], account
        )
        await self.service.maybe_broadcast_or_release(tx, blocking, preview)
        return tx

    async def channel_list(
        self,
        account_id: str = None,  # restrict operation to specific account
        wallet_id: str = None,   # restrict operation to specific wallet
        is_spent=False,          # shows previous channel updates and abandons
        resolve=False,           # resolves each channel to provide additional metadata
        **claim_filter_and_pagination_kwargs
    ) -> Paginated[Output]:
        """
        List my channel claims.

        Usage:
            channel list [--account_id=<account_id>] [--wallet_id=<wallet_id>] [--is_spent] [--resolve]
                         {kwargs}

        """
        claim_filter_and_pagination_kwargs['type'] = 'channel'
        if 'is_spent' not in claim_filter_and_pagination_kwargs:
            claim_filter_and_pagination_kwargs['is_not_spent'] = True
        return await self.txo_list(
            account_id=account_id, wallet_id=wallet_id,
            is_spent=is_spent, resolve=resolve,
            **claim_filter_and_pagination_kwargs
        )

    async def channel_export(
        self,
        channel_id: str = None,    # claim id of channel to export
        channel_name: str = None,  # name of channel to export
        wallet_id: str = None,     # restrict operation to specific wallet
    ) -> str:  # serialized channel private key
        """
        Export channel private key.

        Usage:
            channel export (<channel_id> | --channel_id=<channel_id> | --channel_name=<channel_name>)
                           [--wallet_id=<wallet_id>]

        """
        wallet = self.wallets.get_or_default(wallet_id)
        channel = await wallet.channels.get_for_signing(channel_id, channel_name)
        address = channel.get_address(self.ledger)
        public_key = await wallet.get_public_key_for_address(address)
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

    async def channel_import(
        self,
        channel_data: str,     # serialized channel, as exported by channel export
        wallet_id: str = None  # import into specific wallet
    ) -> str:  # result message
        """
        Import serialized channel private key (to allow signing new streams to the channel)

        Usage:
            channel import (<channel_data> | --channel_data=<channel_data>) [--wallet_id=<wallet_id>]

        """
        wallet = self.wallets.get_or_default(wallet_id)

        decoded = base58.b58decode(channel_data)
        data = json.loads(decoded)
        channel_private_key = ecdsa.SigningKey.from_pem(
            data['signing_private_key'], hashfunc=hashlib.sha256
        )
        public_key_der = channel_private_key.get_verifying_key().to_der()

        # check that the holding_address hasn't changed since the export was made
        holding_address = data['holding_address']
        channels, _, _ = await self.service.search_claims(
            wallet.accounts, public_key_id=self.ledger.public_key_to_address(public_key_der)
        )
        if channels and channels[0].get_address(self.ledger) != holding_address:
            holding_address = channels[0].get_address(self.ledger)

        account = await wallet.get_account_for_address(holding_address)
        if account:
            # Case 1: channel holding address is in one of the accounts we already have
            #         simply add the certificate to existing account
            pass
        else:
            # Case 2: channel holding address hasn't changed and thus is in the bundled read-only account
            #         create a single-address holding account to manage the channel
            if holding_address == data['holding_address']:
                account = await wallet.accounts.add_from_dict({
                    'name': f"Holding Account For Channel {data['name']}",
                    'public_key': data['holding_public_key'],
                    'address_generator': {'name': 'single-address'}
                })
                # TODO: fix
                #if self.ledger.sync.network.is_connected:
                #    await self.ledger.subscribe_account(account)
                #    await self.ledger.sync._update_tasks.done.wait()
            # Case 3: the holding address has changed and we can't create or find an account for it
            else:
                raise Exception(
                    "Channel owning account has changed since the channel was exported and "
                    "it is not an account to which you have access."
                )
        account.add_channel_private_key(channel_private_key)
        await wallet.save()
        return f"Added channel signing key for {data['name']}."

    STREAM_DOC = """
    Create, update, abandon, list and inspect your stream claims.
    """

    async def publish(
        self,
        name: str,  # name for the content (can only consist of a-z A-Z 0-9 and -(dash))
        bid: str,   # amount to back the stream
        **stream_edit_and_tx_kwargs
    ) -> Transaction:  # transaction for the published claim
        """
        Create or replace a stream claim at a given name (use 'stream create/update' for more control).

        Usage:
            publish (<name> | --name=<name>) [--bid=<bid>]
                    {kwargs}

        """
        self.valid_stream_name_or_error(name)
        wallet = self.wallets.get_or_default(kwargs.get('wallet_id'))
        if kwargs.get('account_id'):
            accounts = [wallet.get_account_or_error(kwargs.get('account_id'))]
        else:
            accounts = wallet.accounts
        claims = await self.ledger.get_claims(
            wallet=wallet, accounts=accounts, claim_name=name
        )
        if len(claims) == 0:
            if 'bid' not in kwargs:
                raise Exception("'bid' is a required argument for new publishes.")
            if 'file_path' not in kwargs:
                raise Exception("'file_path' is a required argument for new publishes.")
            return await self.stream_create(name, **kwargs)
        elif len(claims) == 1:
            assert claims[0].claim.is_stream, f"Claim at name '{name}' is not a stream claim."
            return await self.stream_update(claims[0].claim_id, replace=True, **kwargs)
        raise Exception(
            f"There are {len(claims)} claims for '{name}', please use 'stream update' command "
            f"to update a specific stream claim."
        )

    async def stream_repost(
        self,
        name: str,                   # name of the repost (can only consist of a-z A-Z 0-9 and -(dash))
        bid: str,                    # amount to back the repost
        claim_id: str,               # id of the claim being reposted
        allow_duplicate_name=False,  # create new repost even if one already exists with given name
        account_id: str = None,      # account to hold the repost
        claim_address: str = None,   # specific address where the repost is held, if not specified
                                     # it will be determined automatically from the account
        ** signed_and_tx_kwargs
    ) -> Transaction:  # transaction for the repost
        """
        Creates a claim that references an existing stream by its claim id.

        Usage:
            stream repost (<name> | --name=<name>) (<bid> | --bid=<bid>) (<claim_id> | --claim_id=<claim_id>)
                          [--allow_duplicate_name] [--account_id=<account_id>] [--claim_address=<claim_address>]
                          {kwargs}

        """
        wallet = self.wallets.get_or_default(wallet_id)
        self.valid_stream_name_or_error(name)
        account = wallet.accounts.get_or_default(account_id)
        funding_accounts = wallet.accounts.get_or_all(fund_account_id)
        channel = await self.get_channel_or_none(wallet, channel_account_id, channel_id, channel_name, for_signing=True)
        amount = self.get_dewies_or_error('bid', bid, positive_value=True)
        claim_address = await self.get_receiving_address(claim_address, account)
        claims = await account.get_claims(claim_name=name)
        if len(claims) > 0:
            if not allow_duplicate_name:
                raise Exception(
                    f"You already have a stream claim published under the name '{name}'. "
                    f"Use --allow-duplicate-name flag to override."
                )
        if not VALID_FULL_CLAIM_ID.fullmatch(claim_id):
            raise Exception('Invalid claim id. It is expected to be a 40 characters long hexadecimal string.')

        claim = Claim()
        claim.repost.reference.claim_id = claim_id
        tx = await Transaction.claim_create(
            name, claim, amount, claim_address, funding_accounts, funding_accounts[0], channel
        )
        new_txo = tx.outputs[0]

        if channel:
            new_txo.sign(channel)
        await tx.sign(funding_accounts)

        await self.service.maybe_broadcast_or_release(tx, blocking, preview)
        return tx

    async def stream_create(
        self,
        name: str,                   # name for the stream (can only consist of a-z A-Z 0-9 and -(dash))
        bid: str,                    # amount to back the content
        allow_duplicate_name=False,  # create new stream even if one already exists with given name
        **stream_and_tx_kwargs
    ) -> Transaction:
        """
        Make a new stream claim and announce the associated file to lbrynet.

        Usage:
            stream create (<name> | --name=<name>) (<bid> | --bid=<bid>) [--allow_duplicate_name]
                          {kwargs}

        """
        stream_dict, kwargs = pop_kwargs('stream', extract_stream(**stream_and_tx_kwargs))
        tx_dict, kwargs = pop_kwargs('tx', extract_tx(**kwargs))
        assert_consumed_kwargs(kwargs)
        self.ledger.valid_stream_name_or_error(name)
        wallet = self.wallets.get_or_default_for_spending(tx_dict.pop('wallet_id'))
        amount = self.ledger.get_dewies_or_error('bid', bid, positive_value=True)
        holding_account = wallet.accounts.get_or_default(stream_dict.pop('account_id'))
        funding_accounts = wallet.accounts.get_or_all(tx_dict.pop('fund_account_id'))
        signing_channel = None
        if 'channel_id' in stream_dict or 'channel_name' in stream_dict:
            signing_channel = await wallet.channels.get_for_signing_or_none(
                channel_id=stream_dict.pop('channel_id', None),
                channel_name=stream_dict.pop('channel_name', None)
            )
        holding_address = await holding_account.get_valid_receiving_address(
            stream_dict.pop('claim_address', None)
        )
        kwargs['fee_address'] = self.ledger.get_fee_address(kwargs, holding_address)

        await wallet.verify_duplicate(name, allow_duplicate_name)

        stream_dict.pop('validate_file')
        stream_dict.pop('optimize_file')
        # TODO: fix
        #file_path, spec = await self._video_file_analyzer.verify_or_repair(
        #    validate_file, optimize_file, file_path, ignore_non_video=True
        #)
        #kwargs.update(spec)
        class FakeManagedStream:
            sd_hash = 'beef'
        async def create_file_stream(path):
            return FakeManagedStream()
        tx, fs = await wallet.streams.create(
            name=name, amount=amount, file_path=stream_dict.pop('file_path'),
            create_file_stream=create_file_stream,
            holding_address=holding_address, funding_accounts=funding_accounts,
            signing_channel=signing_channel, **remove_nulls(stream_dict)
        )
        await self.service.maybe_broadcast_or_release(tx, tx_dict['preview'], tx_dict['no_wait'])
        return tx

    async def stream_update(
        self,
        claim_id: str,    # claim_id of the stream to update
        bid: str = None,  # update amount backing the stream
        **stream_edit_and_tx_kwargs
    ) -> Transaction:  # stream update transaction
        """
        Update an existing stream claim and if a new file is provided announce it to lbrynet.

        Usage:
            stream update (<claim_id> | --claim_id=<claim_id>) [--bid=<bid>]
                          {kwargs}

        """
        wallet = self.wallets.get_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        funding_accounts = wallet.accounts.get_or_all(fund_account_id)
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
            raise Exception(
                f"Can't find the stream '{claim_id}' in account(s) {account_ids}."
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
            old_txo, claim, amount, claim_address, funding_accounts, funding_accounts[0], channel
        )
        new_txo = tx.outputs[0]

        stream_hash = None
        if not preview:
            old_stream = self.stream_manager.streams.get(old_txo.claim.stream.source.sd_hash, None)
            if file_path is not None:
                if old_stream:
                    await self.stream_manager.delete_stream(old_stream, delete_file=False)
                file_stream = await self.stream_manager.create_stream(file_path)
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
            await self.storage.save_claims([self._old_get_temp_claim_info(
                tx, new_txo, claim_address, new_txo.claim, new_txo.claim_name, dewies_to_lbc(amount)
            )])
            if stream_hash:
                await self.storage.save_content_claim(stream_hash, new_txo.id)
            self.component_manager.loop.create_task(self.analytics_manager.send_claim_action('publish'))
        else:
            await account.ledger.release_tx(tx)

        return tx

    async def stream_abandon(
        self, **abandon_and_tx_kwargs
    ) -> Transaction:  # transaction abandoning the stream
        """
        Abandon one of my stream claims.

        Usage:
            stream abandon
                           {kwargs}

        """
        wallet = self.wallets.get_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        if account_id:
            account = wallet.get_account_or_error(account_id)
            accounts = [account]
        else:
            account = wallet.default_account
            accounts = wallet.accounts

        if txid is not None and nout is not None:
            claims = await self.ledger.get_claims(
                wallet=wallet, accounts=accounts, tx_hash=unhexlify(txid)[::-1], position=nout
            )
        elif claim_id is not None:
            claims = await self.ledger.get_claims(
                wallet=wallet, accounts=accounts, claim_id=claim_id
            )
        else:
            raise Exception('Must specify claim_id, or txid and nout')

        if not claims:
            raise Exception('No claim found for the specified claim_id or txid:nout')

        tx = await Transaction.create(
            [Input.spend(txo) for txo in claims], [], accounts, account
        )

        await self.service.maybe_broadcast_or_release(tx, blocking, preview)
        return tx

    async def stream_list(
        self,
        account_id: str = None,  # restrict operation to specific account
        wallet_id: str = None,   # restrict operation to specific wallet
        is_spent=False,          # shows previous stream updates and abandons
        resolve=False,           # resolves each stream to provide additional metadata
        **claim_filter_and_pagination_kwargs
    ) -> Paginated[Output]:
        """
        List my stream claims.

        Usage:
            stream list [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]
                        [--is_spent] [--resolve]
                        {kwargs}

        """
        kwargs['type'] = 'stream'
        if 'is_spent' not in kwargs:
            kwargs['is_not_spent'] = True
        return await self.txo_list(*args, **kwargs)

    async def stream_cost_estimate(
        self,
        uri: str  # uri to use
    ) -> float:  # Estimated cost in lbry credits, returns None if uri is not resolvable
        """
        Get estimated cost for a lbry stream

        Usage:
            stream_cost_estimate (<uri> | --uri=<uri>)

        """
        return self.get_est_cost_from_uri(uri)

    COLLECTION_DOC = """
    Create, update, list, resolve, and abandon collections.
    """

    async def collection_create(
        self,
        name: str,                   # name for the stream (can only consist of a-z A-Z 0-9 and -(dash))
        bid: str,                    # amount to back the content
        claims: StrOrList,           # claim ids to be included in the collection
        allow_duplicate_name=False,  # create new collection even if one already exists with given name
        **claim_and_signed_and_tx_kwargs
    ) -> Transaction:
        """
        Create a new collection.

        Usage:
            collection create (<name> | --name=<name>) (<bid> | --bid=<bid>)
                              (<claims>... | --claims=<claims>...) [--allow_duplicate_name]
                              {kwargs}

        """
        wallet = self.wallets.get_or_default(wallet_id)
        account = wallet.accounts.get_or_default(account_id)
        funding_accounts = wallet.accounts.get_or_all(fund_account_id)
        self.valid_collection_name_or_error(name)
        channel = await self.get_channel_or_none(wallet, channel_account_id, channel_id, channel_name, for_signing=True)
        amount = self.get_dewies_or_error('bid', bid, positive_value=True)
        claim_address = await self.get_receiving_address(claim_address, account)

        existing_collections = await self.ledger.get_collections(accounts=wallet.accounts, claim_name=name)
        if len(existing_collections) > 0:
            if not allow_duplicate_name:
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

        await self.service.maybe_broadcast_or_release(tx, blocking, preview)
        return tx

    async def collection_update(
        self,
        claim_id: str,       # claim_id of the collection to update
        bid: str,            # amount to back the collection
        claims: StrOrList,   # claim ids to be included in the collection
        clear_claims=False,  # clear existing claims (prior to adding new ones)
        **claim_and_claim_edit_and_signed_and_tx_kwargs
    ) -> Transaction:  # updated collection transaction
        """
        Update an existing collection claim.

        Usage:
            collection update (<claim_id> | --claim_id=<claim_id>) [--bid=<bid>]
                              [--claims=<claims>...] [--clear_claims]
                              {kwargs}

        """
        wallet = self.wallets.get_or_default(wallet_id)
        funding_accounts = wallet.accounts.get_or_all(fund_account_id)
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
            raise Exception(
                f"Can't find the collection '{claim_id}' in account(s) {account_ids}."
            )
        old_txo = existing_collections[0]
        if not old_txo.claim.is_collection:
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
            claim.collection.message.source.CopyFrom(
                old_txo.claim.collection.message.source
            )
            claim.collection.update(**kwargs)
        else:
            claim = Claim.from_bytes(old_txo.claim.to_bytes())
            claim.collection.update(**kwargs)
        tx = await Transaction.claim_update(
            old_txo, claim, amount, claim_address, funding_accounts, funding_accounts[0], channel
        )
        new_txo = tx.outputs[0]

        new_txo.script.generate()

        if channel:
            new_txo.sign(channel)
        await tx.sign(funding_accounts)

        await self.service.maybe_broadcast_or_release(tx, blocking, preview)
        return tx

    async def collection_abandon(
        self, **abandon_and_tx_kwargs
    ) -> Transaction:  # transaction abandoning the collection
        """
        Abandon one of my collection claims.

        Usage:
            collection abandon
                               {kwargs}

        """
        return await self.stream_abandon(**abandon_and_tx_kwargs)

    async def collection_list(
        self,
        account_id: str = None,  # restrict operation to specific account
        wallet_id: str = None,   # restrict operation to specific wallet
        resolve_claims=0,        # resolve this number of items in the collection
        **claim_filter_and_pagination_kwargs
    ) -> Paginated[Output]:
        """
        List my collection claims.

        Usage:
            collection list [--resolve_claims=<resolve_claims>]
                            [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]
                            {kwargs}

        """
        wallet = self.wallets.get_or_default(wallet_id)
        if account_id:
            account = wallet.get_account_or_error(account_id)
            collections = account.get_collections
        else:
            collections = partial(self.ledger.get_collections, wallet=wallet, accounts=wallet.accounts)
        return await paginate_rows(collections, page, page_size, resolve_claims=resolve_claims)

    async def collection_resolve(
            self,
            claim_id: str = None,   # claim id of the collection
            url: str = None,        # url of the collection
            wallet_id: str = None,  # restrict operation to specific wallet
            **pagination_kwargs
    ) -> Paginated[Output]:  # resolved items in the collection
        """
        Resolve claims in the collection.

        Usage:
            collection resolve (--claim_id=<claim_id> | --url=<url>) [--wallet_id=<wallet_id>]
                               {kwargs}

        """
        wallet = self.wallets.get_or_default(wallet_id)

        if claim_id:
            txo = await self.ledger.get_claim_by_claim_id(wallet.accounts, claim_id)
            if not isinstance(txo, Output) or not txo.is_claim:
                raise Exception(f"Could not find collection with claim_id '{claim_id}'. ")
        elif url:
            txo = (await self.ledger.resolve(wallet.accounts, [url]))[url]
            if not isinstance(txo, Output) or not txo.is_claim:
                raise Exception(f"Could not find collection with url '{url}'. ")
        else:
            raise Exception(f"Missing argument claim_id or url. ")

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

    async def support_create(
        self,
        claim_id: str,           # claim_id of the claim to support
        amount: str,             # amount of support
        tip=False,               # send support to claim owner
        account_id: str = None,  # account to use for holding the support
        **tx_kwargs
    ) -> Transaction:  # new support transaction
        """
        Create a support or a tip for name claim.

        Usage:
            support create (<claim_id> | --claim_id=<claim_id>) (<amount> | --amount=<amount>)
                           [--tip] [--account_id=<account_id>]
                           {kwargs}

        """
        wallet = self.wallets.get_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        funding_accounts = wallet.accounts.get_or_all(fund_account_id)
        amount = self.ledger.get_dewies_or_error("amount", amount)
        claim = await self.ledger.get_claim_by_claim_id(wallet.accounts, claim_id)
        claim_address = claim.get_address(self.ledger.ledger)
        if not tip:
            account = wallet.accounts.get_or_default(account_id)
            claim_address = await account.receiving.get_or_create_usable_address()

        tx = await Transaction.support(
            claim.claim_name, claim_id, amount, claim_address, funding_accounts, funding_accounts[0]
        )

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

    async def support_list(
        self,
        account_id: str = None,      # restrict operation to specific account
        wallet_id: str = None,       # restrict operation to specific wallet
        name: StrOrList = None,      # support for specific claim name(s)
        claim_id: StrOrList = None,  # support for specific claim id(s)
        received=False,              # only show received (tips)
        sent=False,                  # only show sent (tips)
        staked=False,                # only show my staked supports
        is_spent=False,              # show abandoned supports
        **pagination_kwargs
    ) -> Paginated[Output]:
        """
        List staked supports and sent/received tips.

        Usage:
            support list [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]
                         [--name=<name>...] [--claim_id=<claim_id>...]
                         [--received | --sent | --staked] [--is_spent]
                         {kwargs}

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
        return await self.txo_list(*args, **kwargs)

    async def support_search(
        self,
        wallet_id: str = None,       # wallet to check if support is owned by user
        order_by: StrOrList = None,  # field to order by
        **support_filter_and_pagination_kwargs
    ) -> Paginated[Output]:  # search results
        """
        Search for supports on the blockchain.

        Arguments marked with "supports equality constraints" allow prepending the
        value with an equality constraint such as '>', '>=', '<' and '<='
        eg. --height=">400000" would limit results to only supports above 400k block height.

        Usage:
            support search [--wallet_id=<wallet_id>] [--order_by=<order_by>...]
                           {kwargs}

        """
        support_filter_dict, kwargs = pop_kwargs('support_filter', extract_support_filter(
            **support_filter_and_pagination_kwargs
        ))
        pagination, kwargs = pop_kwargs('pagination', extract_pagination(**kwargs))
        wallet = self.wallets.get_or_default(wallet_id)
        page_num = abs(pagination['page'] or 1)
        page_size = min(abs(pagination['page_size'] or DEFAULT_PAGE_SIZE), 50)
        support_filter_dict.update({
            'offset': page_size * (page_num - 1), 'limit': page_size,
            'include_total': pagination['include_total'],
            'order_by': order_by
        })
        result = await self.service.search_supports(
            wallet.accounts, **remove_nulls(support_filter_dict)
        )
        d = {
            "items": result.rows,
            "page": page_num,
            "page_size": page_size
        }
        if pagination['include_total']:
            d['total_pages'] = int((result.total + (page_size - 1)) / page_size)
            d['total_items'] = result.total
        return d

    async def support_sum(
            self,
            claim_id: str,                          # id of claim to calculate support stats for
            include_channel_content: bool = False,  # if claim_id is for a channel, include supports for
                                                    # claims in that channel
            exclude_own_supports: bool = False,     # exclude supports signed by claim_id (i.e. self-supports)
            **pagination_kwargs
    ) -> Paginated[Dict]:  # supports grouped by channel
        # TODO: add unsigned supports to the output so the numbers add up. just a left join on identity
        """
        List total staked supports for a claim, grouped by the channel that signed the support.

        If claim_id is a channel claim:
            Use --include_channel_content to include supports for content claims in the channel.
            Use --exclude_own_supports to exclude supports from the channel to itself.

        Usage:
            support sum <claim_id> [--inculde_channel_content]
                        {kwargs}
        """
        return await self.service.sum_supports(hex_str_to_hash(claim_id), include_channel_content, exclude_own_supports)

    async def support_abandon(
        self,
        keep: str = None,  # amount of lbc to keep as support
        **abandon_and_tx_kwargs
    ) -> Transaction:  # transaction abandoning the supports
        """
        Abandon supports, including tips, of a specific claim, optionally
        keeping some amount as supports.

        Usage:
            support abandon [--keep=<keep>]
                            {kwargs}

        """
        wallet = self.wallets.get_or_default(wallet_id)
        assert not wallet.is_locked, "Cannot spend funds with locked wallet, unlock first."
        if account_id:
            account = wallet.get_account_or_error(account_id)
            accounts = [account]
        else:
            account = wallet.default_account
            accounts = wallet.accounts

        if txid is not None and nout is not None:
            supports = await self.ledger.get_supports(
                wallet=wallet, accounts=accounts, tx_hash=unhexlify(txid)[::-1], position=nout
            )
        elif claim_id is not None:
            supports = await self.ledger.get_supports(
                wallet=wallet, accounts=accounts, claim_id=claim_id
            )
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
            [Input.spend(txo) for txo in supports], outputs, accounts, account
        )
        await self.service.maybe_broadcast_or_release(tx, blocking, preview)
        return tx

    TRANSACTION_DOC = """
    Transaction management.
    """

    async def transaction_list(
        self,
        account_id: str = None,  # restrict operation to specific account
        wallet_id: str = None,   # restrict operation to specific wallet
        **pagination_kwargs
    ) -> list:  # transactions
        """
        List transactions belonging to wallet

        Usage:
            transaction_list [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]
                             {kwargs}

        Returns:
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
        wallet = self.wallets.get_or_default(wallet_id)
        if account_id:
            account = wallet.get_account_or_error(account_id)
            transactions = account.get_transaction_history
        else:
            transactions = partial(
                self.ledger.get_transaction_history, wallet=wallet, accounts=wallet.accounts)
        return await paginate_rows(transactions, page, page_size)

    async def transaction_search(
        self,
        txids: StrOrList,  # transaction ids to find
    ) -> List[Transaction]:
        """
        Search for transaction(s) in the entire blockchain.

        Usage:
            transaction_search <txid>...

        """
        return await self.service.search_transactions(txids)

    TXO_DOC = """
    List and sum transaction outputs.
    """

    @staticmethod
    def _constrain_txo_from_kwargs(
            constraints, type=None, txid=None,  # pylint: disable=redefined-builtin
            claim_id=None, channel_id=None, name=None, reposted_claim_id=None,
            is_spent=False, is_not_spent=False,
            is_my_input_or_output=None, exclude_internal_transfers=False,
            is_my_output=None, is_not_my_output=None,
            is_my_input=None, is_not_my_input=None):
        if is_spent:
            constraints['spent_height__not'] = 0
        elif is_not_spent:
            constraints['spent_height'] = 0
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
        to_hash = lambda x: unhexlify(x)[::-1]
        constrain_single_or_list(constraints, 'txo_type', type, lambda x: TXO_TYPES[x])
        constrain_single_or_list(constraints, 'channel_hash', channel_id, to_hash)
        constrain_single_or_list(constraints, 'claim_hash', claim_id, to_hash)
        constrain_single_or_list(constraints, 'claim_name', name)
        constrain_single_or_list(constraints, 'tx_hash', txid, to_hash)
        constrain_single_or_list(constraints, 'reposted_claim_hash', reposted_claim_id, to_hash)
        return constraints

    async def txo_list(
        self,
        include_received_tips=False,  # calculate the amount of tips recieved for claim outputs
        resolve=False,                # resolves each claim to provide additional metadata
        order_by: str = None,         # field to order by: 'name', 'height', 'amount' and 'none'
        **txo_filter_and_pagination_kwargs
    ) -> Paginated[Output]:
        """
        List my transaction outputs.

        Usage:
            txo list [--include_received_tips] [--resolve] [--order_by=<order_by>]
                     {kwargs}

        """
        txo_dict, kwargs = pop_kwargs('txo_filter', extract_txo_filter(**txo_filter_and_pagination_kwargs))
        pagination, kwargs = pop_kwargs('pagination', extract_pagination(**kwargs))
        assert_consumed_kwargs(kwargs)
        wallet = self.wallets.get_or_default(txo_dict.pop('wallet_id'))
        accounts = wallet.accounts.get_or_all(txo_dict.pop('account_id'))
        constraints = {
            'resolve': resolve,
            'include_is_my_input': True,
            'include_is_my_output': True,
            'include_received_tips': include_received_tips,
        }
        if order_by is not None:
            if order_by == 'name':
                constraints['order_by'] = 'txo.claim_name'
            elif order_by in ('height', 'amount', 'none'):
                constraints['order_by'] = order_by
            else:
                raise ValueError(f"'{order_by}' is not a valid --order_by value.")
        self._constrain_txo_from_kwargs(constraints, **txo_dict)
        return await paginate_rows(
            self.service.get_txos,
            wallet=wallet, accounts=accounts,
            **pagination, **constraints
        )

    async def txo_spend(
        self,
        batch_size=500,                 # number of txos to spend per transactions
        include_full_tx=False,          # include entire tx in output and not just the txid
        change_account_id: str = None,  # account to send excess change (LBC)
        fund_account_id: StrOrList = None,  # accounts to fund the transaction
        preview=False,                  # do not broadcast the transaction
        no_wait=False,                  # do not wait for mempool confirmation
        **txo_filter_kwargs
    ) -> List[Transaction]:
        """
        Spend transaction outputs, batching into multiple transactions as necessary.

        Usage:
            txo spend [--batch_size=<batch_size>] [--include_full_tx]
                      {kwargs}

        """
        wallet = self.wallets.get_or_default(wallet_id)
        accounts = [wallet.get_account_or_error(account_id)] if account_id else wallet.accounts
        txos = await self.ledger.get_txos(
            wallet=wallet, accounts=accounts,
            **self._constrain_txo_from_kwargs({}, is_not_spent=True, is_my_output=True, **kwargs)
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

    async def txo_sum(self, **txo_filter_kwargs) -> int:  # sum of filtered outputs
        """
        Sum of transaction outputs.

        Usage:
            txo sum
                    {kwargs}

        """
        wallet = self.wallets.get_or_default(wallet_id)
        return await self.ledger.get_txo_sum(
            wallet=wallet, accounts=[wallet.get_account_or_error(account_id)] if account_id else wallet.accounts,
            **self._constrain_txo_from_kwargs({}, **kwargs)
        )

    async def txo_plot(
        self,
        days_back=0,             # number of days back from today
                                 # (not compatible with --start_day, --days_after, --end_day)
        start_day: str = None,   # start on specific date (format: YYYY-MM-DD) (instead of --days_back)
        days_after: int = None,  # end number of days after --start_day (instead of using --end_day)
        end_day: str = None,     # end on specific date (format: YYYY-MM-DD) (instead of --days_after)
        **txo_filter_and_pagination_kwargs
    ) -> List:
        """
        Plot transaction output sum over days.

        Usage:
            txo_plot [--days_back=<days_back> |
                        [--start_day=<start_day> [--days_after=<days_after> | --end_day=<end_day>]]
                     ]
                     {kwargs}

        """
        wallet = self.wallets.get_or_default(wallet_id)
        plot = await self.ledger.get_txo_plot(
            wallet=wallet, accounts=[wallet.get_account_or_error(account_id)] if account_id else wallet.accounts,
            days_back=days_back, start_day=start_day, days_after=days_after, end_day=end_day,
            **self._constrain_txo_from_kwargs({}, **kwargs)
        )
        for row in plot:
            row['total'] = dewies_to_lbc(row['total'])
        return plot

    UTXO_DOC = """
    Unspent transaction management.
    """

    async def utxo_list(self, **txo_filter_and_pagination_kwargs) -> Paginated[Output]:  # unspent outputs
        """
        List unspent transaction outputs

        Usage:
            utxo_list
                      {kwargs}

        """
        kwargs['type'] = ['other', 'purchase']
        kwargs['is_not_spent'] = True
        return await self.txo_list(*args, **kwargs)

    async def utxo_release(
        self,
        account_id: str = None,  # restrict operation to specific account
        wallet_id: str = None,   # restrict operation to specific wallet
    ):
        """
        When spending a UTXO it is locally locked to prevent double spends;
        occasionally this can result in a UTXO being locked which ultimately
        did not get spent (failed to broadcast, spend transaction was not
        accepted by blockchain node, etc). This command releases the lock
        on all UTXOs in your account.

        Usage:
            utxo_release [<account_id> | --account_id=<account_id>] [--wallet_id=<wallet_id>]

        """
        wallet = self.wallets.get_or_default(wallet_id)
        if account_id is not None:
            await wallet.get_account_or_error(account_id).release_all_outputs()
        else:
            for account in wallet.accounts:
                await account.release_all_outputs()

    BLOB_DOC = """
    Blob management.
    """

    async def blob_get(
        self,
        blob_hash: str,       # blob hash of the blob to get
        timeout: int = None,  # timeout in number of seconds
        read=False
    ) -> str:  # Success/Fail message or (dict) decoded data
        """
        Download and return a blob

        Usage:
            blob get (<blob_hash> | --blob_hash=<blob_hash>) [--timeout=<timeout>] [--read]

        """

        blob = await download_blob(asyncio.get_running_loop(), self.conf, self.blob_manager, self.dht_node, blob_hash)
        if read:
            with blob.reader_context() as handle:
                return handle.read().decode()
        elif isinstance(blob, BlobBuffer):
            log.warning("manually downloaded blob buffer could have missed garbage collection, clearing it")
            blob.delete()
        return "Downloaded blob %s" % blob_hash

    async def blob_delete(
        self,
        blob_hash: str,  # blob hash of the blob to delete
    ) -> str:  # Success/fail message
        """
        Delete a blob

        Usage:
            blob_delete (<blob_hash> | --blob_hash=<blob_hash>)

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

    async def peer_list(
        self,
        blob_hash: str,                       # find available peers for this blob hash
        search_bottom_out_limit: int = None,  # the number of search probes in a row
                                              # that don't find any new peers
                                              # before giving up and returning
        page: int = None,                     # page to return during paginating
        page_size: int = None,                # number of items on page during pagination
    ) -> list:  # List of contact dictionaries
        """
        Get peers for blob hash

        Usage:
            peer list (<blob_hash> | --blob_hash=<blob_hash>)
                [<search_bottom_out_limit> | --search_bottom_out_limit=<search_bottom_out_limit>]
                [--page=<page>] [--page_size=<page_size>]

        Returns:
            {'address': <peer ip>, 'udp_port': <dht port>, 'tcp_port': <peer port>, 'node_id': <peer node id>}
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

    async def blob_announce(
        self,
        blob_hash: str = None,    # announce a blob, specified by blob_hash
        stream_hash: str = None,  # announce all blobs associated with stream_hash
        sd_hash: str = None       # announce all blobs associated with sd_hash and the sd_hash itself
    ) -> bool:  # true if successful
        """
        Announce blobs to the DHT

        Usage:
            blob announce (<blob_hash> | --blob_hash=<blob_hash>
                          | --stream_hash=<stream_hash> | --sd_hash=<sd_hash>)

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

    async def blob_list(
        self,
        uri: str = None,          # filter blobs by stream in a uri
        stream_hash: str = None,  # filter blobs by stream hash
        sd_hash: str = None,      # filter blobs by sd hash
        needed=False,             # only return needed blobs
        finished=False,           # only return finished blobs
        page: int = None,         # page to return during paginating
        page_size: int = None,    # number of items on page during pagination
    ) -> list:  # List of blob hashes
        """
        Returns blob hashes. If not given filters, returns all blobs known by the blob manager

        Usage:
            blob list [--needed] [--finished] [<uri> | --uri=<uri>]
                      [<stream_hash> | --stream_hash=<stream_hash>]
                      [<sd_hash> | --sd_hash=<sd_hash>]
                      [--page=<page>] [--page_size=<page_size>]

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

    async def file_reflect(
        self,
        reflector: str = None,  # reflector server, ip address or url, by default choose a server from the config
        **file_filter_kwargs
    ) -> list:  # list of blobs reflected
        """
        Reflect all the blobs in a file matching the filter criteria

        Usage:
            file reflect [--reflector=<reflector>]
                         {kwargs}

        """

        server, port = kwargs.get('server'), kwargs.get('port')
        if server and port:
            port = int(port)
        else:
            server, port = random.choice(self.conf.reflector_servers)
        reflected = await asyncio.gather(*[
            self.stream_manager.reflect_stream(stream, server, port)
            for stream in self.stream_manager.get_filtered_streams(**kwargs)
        ])
        total = []
        for reflected_for_stream in reflected:
            total.extend(reflected_for_stream)
        return total

    async def peer_ping(
        self,
        node_id: str,  # node id
        address: str,  # ip address
        port: int      # ip port
    ) -> str:  # pong, or {'error': <error message>} if an error is encountered
        """
        Send a kademlia ping to the specified peer. If address and port are provided the peer is directly pinged,
        if not provided the peer is located first.

        Usage:
            peer ping (<node_id> | --node_id=<node_id>) (<address> | --address=<address>) (<port> | --port=<port>)

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

    async def routing_table_get(self) -> dict:  # dictionary containing routing and peer information
        """
        Get DHT routing information

        Returns:
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

    TRACEMALLOC_DOC = """
    Controls and queries tracemalloc memory tracing tools for troubleshooting.
    """

    async def tracemalloc_enable(self) -> bool:  # is it tracing?
        """ Enable tracemalloc memory tracing """
        tracemalloc.start()
        return tracemalloc.is_tracing()

    async def tracemalloc_disable(self) -> bool:  # is it tracing?
        """ Disable tracemalloc memory tracing """
        tracemalloc.stop()
        return tracemalloc.is_tracing()

    async def tracemalloc_top(
        self,
        items=10  # maximum items to return, from the most common
    ) -> dict:  # dictionary containing most common objects in memory
        """
        Show most common objects, the place that created them and their size.

        Usage:
            tracemalloc top [(<items> | --items=<items>)]

        Returns:
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

    async def comment_list(
        self,
        claim_id: str,                      # The claim on which the comment will be made on
        parent_id: str = None,              # CommentId of a specific thread you'd like to see
        include_replies=True,               # Whether or not you want to include replies in list
        is_channel_signature_valid=False,   # Only include comments with valid signatures.
                                            # [Warning: Paginated total size will not change, even if list reduces]
        hidden=False,                       # Select only Hidden Comments
        visible=False,                      # Select only Visible Comments
        page=1, page_size=50
    ) -> dict:  # Containing the list, and information about the paginated content
        """
        List comments associated with a claim.

        Usage:
            comment list (<claim_id> | --claim_id=<claim_id>)
                         [(--page=<page> --page_size=<page_size>)]
                         [--parent_id=<parent_id>] [--include_replies]
                         [--is_channel_signature_valid]
                         [--visible | --hidden]

        Returns:
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
            result = await comment_client.post(
                self.conf.comment_server,
                'get_claim_hidden_comments',
                claim_id=claim_id,
                hidden=hidden,
                page=page,
                page_size=page_size
            )
        else:
            result = await comment_client.post(
                self.conf.comment_server,
                'get_claim_comments',
                claim_id=claim_id,
                parent_id=parent_id,
                page=page,
                page_size=page_size,
                top_level=not include_replies
            )
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

    async def comment_create(
        self,
        comment: str,           # Comment to be made, should be at most 2000 characters.
        claim_id: str = None,   # The ID of the claim to comment on
        parent_id: str = None,  # The ID of a comment to make a response to
        wallet_id: str = None,  # restrict operation to specific wallet
        **signed_kwargs
    ) -> dict:  # Comment object if successfully made, (None) otherwise
        """
        Create and associate a comment with a claim using your channel identity.

        Usage:
            comment create  (<comment> | --comment=<comment>)
                            (<claim_id> | --claim_id=<claim_id> | --parent_id=<parent_id>)
                            [--wallet_id=<wallet_id>]
                            {kwargs}

        Returns:
            {
                "comment":      (str) The actual string as inputted by the user,
                "comment_id":   (str) The Comment's unique identifier,
                "channel_name": (str) Name of the channel this was posted under, prepended with a '@',
                "channel_id":   (str) The Channel Claim ID that this comment was posted under,
                "signature":    (str) The signature of the comment,
                "signing_ts":   (str) The timestamp used to sign the comment,
                "channel_url":  (str) Channel's URI in the ClaimTrie,
                "parent_id":    (str) Comment this is replying to, (None) if this is the root,
                "timestamp":    (int) The time at which comment was entered into the server at, in nanoseconds.
            }
        """
        wallet = self.wallets.get_or_default(wallet_id)
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

        response = await comment_client.post(self.conf.comment_server, 'create_comment', comment_body)
        response.update({
            'is_claim_signature_valid': comment_client.is_comment_signed_by_channel(response, channel)
        })
        return response

    async def comment_update(
        self,
        comment: str,           # New comment replacing the old one
        comment_id: str,        # Hash identifying the comment to edit
        wallet_id: str = None,  # restrict operation to specific wallet
    ) -> dict:  # Comment object if edit was successful, (None) otherwise
        """
        Edit a comment published as one of your channels.

        Usage:
            comment update (<comment> | --comment=<comment>)
                         (<comment_id> | --comment_id=<comment_id>)
                         [--wallet_id=<wallet_id>]

        Returns:
            {
                "comment":      (str) The actual string as inputted by the user,
                "comment_id":   (str) The Comment's unique identifier,
                "channel_name": (str) Name of the channel this was posted under, prepended with a '@',
                "channel_id":   (str) The Channel Claim ID that this comment was posted under,
                "signature":    (str) The signature of the comment,
                "signing_ts":   (str) Timestamp used to sign the most recent signature,
                "channel_url":  (str) Channel's URI in the ClaimTrie,
                "parent_id":    (str) Comment this is replying to, (None) if this is the root,
                "timestamp":    (int) The time at which comment was entered into the server at, in nanoseconds.
            }
        """
        channel = await comment_client.post(
            self.conf.comment_server,
            'get_channel_from_comment_id',
            comment_id=comment_id
        )
        if 'error' in channel:
            raise ValueError(channel['error'])

        wallet = self.wallets.get_or_default(wallet_id)
        # channel = await self.get_channel_or_none(wallet, None, **channel)
        channel_claim = await self.get_channel_or_error(wallet, [], **channel)
        edited_comment = {
            'comment_id': comment_id,
            'comment': comment,
            'channel_id': channel_claim.claim_id,
            'channel_name': channel_claim.claim_name
        }
        comment_client.sign_comment(edited_comment, channel_claim)
        return await comment_client.post(
            self.conf.comment_server, 'edit_comment', edited_comment
        )

    async def comment_abandon(
        self,
        comment_id: str,        # The ID of the comment to be abandoned.
        wallet_id: str = None,  # restrict operation to specific wallet
    ) -> dict:  # Object with the `comment_id` passed in as the key, and a flag indicating if it was abandoned
        """
        Abandon a comment published under your channel identity.

        Usage:
            comment abandon  (<comment_id> | --comment_id=<comment_id>) [--wallet_id=<wallet_id>]

        Returns:
            {
                <comment_id> (str): {
                    "abandoned": (bool)
                }
            }
        """
        wallet = self.wallets.get_or_default(wallet_id)
        abandon_comment_body = {'comment_id': comment_id}
        channel = await comment_client.post(
            self.conf.comment_server, 'get_channel_from_comment_id', comment_id=comment_id
        )
        if 'error' in channel:
            return {comment_id: {'abandoned': False}}
        channel = await self.get_channel_or_none(wallet, None, **channel)
        abandon_comment_body.update({
            'channel_id': channel.claim_id,
            'channel_name': channel.claim_name,
        })
        comment_client.sign_comment(abandon_comment_body, channel, abandon=True)
        return await comment_client.post(self.conf.comment_server, 'abandon_comment', abandon_comment_body)

    async def comment_hide(
        self,
        comment_ids: StrOrList,  # one or more comment_id to hide.
        wallet_id: str = None,   # restrict operation to specific wallet
    ) -> dict:  # keyed by comment_id, containing success info
        """
        Hide a comment published to a claim you control.

        Usage:
            comment hide  <comment_ids>... [--wallet_id=<wallet_id>]

        Returns:
            '<comment_id>': {
                "hidden": (bool)  flag indicating if comment_id was hidden
            }
        """
        wallet = self.wallets.get_or_default(wallet_id)

        if isinstance(comment_ids, str):
            comment_ids = [comment_ids]

        comments = await comment_client.post(
            self.conf.comment_server, 'get_comments_by_id', comment_ids=comment_ids
        )
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
                comment_client.sign_comment(piece, channel, abandon=True)
                pieces.append(piece)
        return await comment_client.post(self.conf.comment_server, 'hide_comments', pieces=pieces)


class Client(API):

    def __init__(self, url):
        self.url = url
        self.session: Optional[ClientSession] = None
        self.receive_messages_task: Optional[asyncio.Task] = None
        self.ws = None
        self.message_id = 0
        self.requests: Dict[int, EventController] = {}
        self.subscriptions: Dict[str, EventController] = {}

    async def connect(self):
        self.session = ClientSession()
        self.ws = await self.session.ws_connect(self.url)
        self.receive_messages_task = asyncio.create_task(self.receive_messages())

    async def disconnect(self):
        await self.session.close()
        self.receive_messages_task.cancel()

    async def receive_messages(self):
        async for message in self.ws:
            d = message.json()
            if 'id' in d:
                controller = self.requests[d['id']]
                if 'event' in d:
                    await controller.add(d['event'])
                    continue
                elif 'result' in d:
                    await controller.add(d['result'])
                elif 'error' in d:
                    await controller.add_error(Exception(d['error']))
                else:
                    raise ValueError(f'Unknown message received: {d}')
                await controller.close()
                del self.requests[d['id']]
            elif 'method' in d and d['method'].startswith('event'):
                print(d)
            else:
                raise ValueError(f'Unknown message received: {d}')

    async def send(self, method, **kwargs) -> EventStream:
        self.message_id += 1
        self.requests[self.message_id] = ec = EventController()
        await self.ws.send_json({'id': self.message_id, 'method': method, 'params': kwargs})
        return ec.stream

    async def subscribe(self, event) -> EventStream:
        if event not in self.subscriptions:
            self.subscriptions[event] = EventController()
            await self.ws.send_json({'id': None, 'method': 'subscribe', 'params': [event]})
        return self.subscriptions[event].stream

    def __getattribute__(self, name):
        if name in dir(API):
            return partial(object.__getattribute__(self, 'send'), name)
        return object.__getattribute__(self, name)
