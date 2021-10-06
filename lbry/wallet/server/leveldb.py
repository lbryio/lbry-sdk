# Copyright (c) 2016, Neil Booth
# Copyright (c) 2017, the ElectrumX authors
#
# All rights reserved.
#
# See the file "LICENCE" for information about the copyright
# and warranty status of this software.

"""Interface to the blockchain database."""

import os
import asyncio
import array
import time
import typing
import struct
import zlib
import base64
from typing import Optional, Iterable, Tuple, DefaultDict, Set, Dict, List, TYPE_CHECKING
from functools import partial
from asyncio import sleep
from bisect import bisect_right
from collections import defaultdict

from lbry.error import ResolveCensoredError
from lbry.schema.result import Censor
from lbry.utils import LRUCacheWithMetrics
from lbry.schema.url import URL, normalize_name
from lbry.wallet.server import util
from lbry.wallet.server.hash import hash_to_hex_str
from lbry.wallet.server.tx import TxInput
from lbry.wallet.server.merkle import Merkle, MerkleCache
from lbry.wallet.server.db.common import ResolveResult, STREAM_TYPES, CLAIM_TYPES
from lbry.wallet.server.db.prefixes import PendingActivationValue, ClaimTakeoverValue, ClaimToTXOValue, HubDB
from lbry.wallet.server.db.prefixes import ACTIVATED_CLAIM_TXO_TYPE, ACTIVATED_SUPPORT_TXO_TYPE
from lbry.wallet.server.db.prefixes import PendingActivationKey, TXOToClaimValue
from lbry.wallet.transaction import OutputScript
from lbry.schema.claim import Claim, guess_stream_type
from lbry.wallet.ledger import Ledger, RegTestLedger, TestNetLedger

from lbry.wallet.server.db.elasticsearch import SearchIndex

if TYPE_CHECKING:
    from lbry.wallet.server.db.prefixes import EffectiveAmountKey


class UTXO(typing.NamedTuple):
    tx_num: int
    tx_pos: int
    tx_hash: bytes
    height: int
    value: int


TXO_STRUCT = struct.Struct(b'>LH')
TXO_STRUCT_unpack = TXO_STRUCT.unpack
TXO_STRUCT_pack = TXO_STRUCT.pack
OptionalResolveResultOrError = Optional[typing.Union[ResolveResult, ResolveCensoredError, LookupError, ValueError]]


class DBError(Exception):
    """Raised on general DB errors generally indicating corruption."""


class LevelDB:
    DB_VERSIONS = HIST_DB_VERSIONS = [7]

    def __init__(self, env):
        self.logger = util.class_logger(__name__, self.__class__.__name__)
        self.env = env
        self.coin = env.coin

        self.logger.info(f'switching current directory to {env.db_dir}')

        self.prefix_db = None

        self.hist_unflushed = defaultdict(partial(array.array, 'I'))
        self.hist_unflushed_count = 0
        self.hist_flush_count = 0
        self.hist_comp_flush_count = -1
        self.hist_comp_cursor = -1

        # blocking/filtering dicts
        blocking_channels = self.env.default('BLOCKING_CHANNEL_IDS', '').split(' ')
        filtering_channels = self.env.default('FILTERING_CHANNEL_IDS', '').split(' ')
        self.blocked_streams = {}
        self.blocked_channels = {}
        self.blocking_channel_hashes = {
            bytes.fromhex(channel_id) for channel_id in blocking_channels if channel_id
        }
        self.filtered_streams = {}
        self.filtered_channels = {}
        self.filtering_channel_hashes = {
            bytes.fromhex(channel_id) for channel_id in filtering_channels if channel_id
        }

        self.tx_counts = None
        self.headers = None
        self.encoded_headers = LRUCacheWithMetrics(1 << 21, metric_name='encoded_headers', namespace='wallet_server')
        self.last_flush = time.time()

        self.logger.info(f'using {self.env.db_engine} for DB backend')

        # Header merkle cache
        self.merkle = Merkle()
        self.header_mc = MerkleCache(self.merkle, self.fs_block_hashes)

        self._tx_and_merkle_cache = LRUCacheWithMetrics(2 ** 17, metric_name='tx_and_merkle', namespace="wallet_server")

        self.claim_to_txo: Dict[bytes, ClaimToTXOValue] = {}
        self.txo_to_claim: DefaultDict[int, Dict[int, bytes]] = defaultdict(dict)

        # Search index
        self.search_index = SearchIndex(
            self.env.es_index_prefix, self.env.database_query_timeout,
            elastic_host=env.elastic_host, elastic_port=env.elastic_port,
            half_life=self.env.trending_half_life, whale_threshold=self.env.trending_whale_threshold,
            whale_half_life=self.env.trending_whale_half_life
        )

        self.genesis_bytes = bytes.fromhex(self.coin.GENESIS_HASH)

        if env.coin.NET == 'mainnet':
            self.ledger = Ledger
        elif env.coin.NET == 'testnet':
            self.ledger = TestNetLedger
        else:
            self.ledger = RegTestLedger

    def get_claim_from_txo(self, tx_num: int, tx_idx: int) -> Optional[TXOToClaimValue]:
        claim_hash_and_name = self.prefix_db.txo_to_claim.get(tx_num, tx_idx)
        if not claim_hash_and_name:
            return
        return claim_hash_and_name

    def get_repost(self, claim_hash) -> Optional[bytes]:
        repost = self.prefix_db.repost.get(claim_hash)
        if repost:
            return repost.reposted_claim_hash
        return

    def get_reposted_count(self, claim_hash: bytes) -> int:
        return sum(
            1 for _ in self.prefix_db.reposted_claim.iterate(prefix=(claim_hash,), include_value=False)
        )

    def get_activation(self, tx_num, position, is_support=False) -> int:
        activation = self.prefix_db.activated.get(
            ACTIVATED_SUPPORT_TXO_TYPE if is_support else ACTIVATED_CLAIM_TXO_TYPE, tx_num, position
        )
        if activation:
            return activation.height
        return -1

    def get_supported_claim_from_txo(self, tx_num: int, position: int) -> typing.Tuple[Optional[bytes], Optional[int]]:
        supported_claim_hash = self.prefix_db.support_to_claim.get(tx_num, position)
        if supported_claim_hash:
            packed_support_amount = self.prefix_db.claim_to_support.get(
                supported_claim_hash.claim_hash, tx_num, position
            )
            if packed_support_amount:
                return supported_claim_hash.claim_hash, packed_support_amount.amount
        return None, None

    def get_support_amount(self, claim_hash: bytes):
        support_amount_val = self.prefix_db.support_amount.get(claim_hash)
        if support_amount_val is None:
            return 0
        return support_amount_val.amount

    def get_supports(self, claim_hash: bytes):
        return [
            (k.tx_num, k.position, v.amount) for k, v in self.prefix_db.claim_to_support.iterate(prefix=(claim_hash,))
        ]

    def get_short_claim_id_url(self, name: str, normalized_name: str, claim_hash: bytes,
                               root_tx_num: int, root_position: int) -> str:
        claim_id = claim_hash.hex()
        for prefix_len in range(10):
            for k in self.prefix_db.claim_short_id.iterate(prefix=(normalized_name, claim_id[:prefix_len+1]),
                                                           include_value=False):
                if k.root_tx_num == root_tx_num and k.root_position == root_position:
                    return f'{name}#{k.partial_claim_id}'
                break
        print(f"{claim_id} has a collision")
        return f'{name}#{claim_id}'

    def _prepare_resolve_result(self, tx_num: int, position: int, claim_hash: bytes, name: str,
                                root_tx_num: int, root_position: int, activation_height: int,
                                signature_valid: bool) -> ResolveResult:
        try:
            normalized_name = normalize_name(name)
        except UnicodeDecodeError:
            normalized_name = name
        controlling_claim = self.get_controlling_claim(normalized_name)

        tx_hash = self.prefix_db.tx_hash.get(tx_num, deserialize_value=False)
        height = bisect_right(self.tx_counts, tx_num)
        created_height = bisect_right(self.tx_counts, root_tx_num)
        last_take_over_height = controlling_claim.height

        expiration_height = self.coin.get_expiration_height(height)
        support_amount = self.get_support_amount(claim_hash)
        claim_amount = self.claim_to_txo[claim_hash].amount

        effective_amount = support_amount + claim_amount
        channel_hash = self.get_channel_for_claim(claim_hash, tx_num, position)
        reposted_claim_hash = self.get_repost(claim_hash)
        short_url = self.get_short_claim_id_url(name, normalized_name, claim_hash, root_tx_num, root_position)
        canonical_url = short_url
        claims_in_channel = self.get_claims_in_channel_count(claim_hash)
        if channel_hash:
            channel_vals = self.claim_to_txo.get(channel_hash)
            if channel_vals:
                channel_short_url = self.get_short_claim_id_url(
                    channel_vals.name, channel_vals.normalized_name, channel_hash, channel_vals.root_tx_num,
                    channel_vals.root_position
                )
                canonical_url = f'{channel_short_url}/{short_url}'
        return ResolveResult(
            name, normalized_name, claim_hash, tx_num, position, tx_hash, height, claim_amount, short_url=short_url,
            is_controlling=controlling_claim.claim_hash == claim_hash, canonical_url=canonical_url,
            last_takeover_height=last_take_over_height, claims_in_channel=claims_in_channel,
            creation_height=created_height, activation_height=activation_height,
            expiration_height=expiration_height, effective_amount=effective_amount, support_amount=support_amount,
            channel_hash=channel_hash, reposted_claim_hash=reposted_claim_hash,
            reposted=self.get_reposted_count(claim_hash),
            signature_valid=None if not channel_hash else signature_valid
        )

    def _resolve(self, name: str, claim_id: Optional[str] = None,
                 amount_order: Optional[int] = None) -> Optional[ResolveResult]:
        """
        :param normalized_name: name
        :param claim_id: partial or complete claim id
        :param amount_order: '$<value>' suffix to a url, defaults to 1 (winning) if no claim id modifier is provided
        """
        try:
            normalized_name = normalize_name(name)
        except UnicodeDecodeError:
            normalized_name = name
        if (not amount_order and not claim_id) or amount_order == 1:
            # winning resolution
            controlling = self.get_controlling_claim(normalized_name)
            if not controlling:
                # print(f"none controlling for lbry://{normalized_name}")
                return
            # print(f"resolved controlling lbry://{normalized_name}#{controlling.claim_hash.hex()}")
            return self._fs_get_claim_by_hash(controlling.claim_hash)

        amount_order = max(int(amount_order or 1), 1)

        if claim_id:
            if len(claim_id) == 40:  # a full claim id
                claim_txo = self.get_claim_txo(bytes.fromhex(claim_id))
                if not claim_txo or normalized_name != claim_txo.normalized_name:
                    return
                return self._prepare_resolve_result(
                    claim_txo.tx_num, claim_txo.position, bytes.fromhex(claim_id), claim_txo.name,
                    claim_txo.root_tx_num, claim_txo.root_position,
                    self.get_activation(claim_txo.tx_num, claim_txo.position), claim_txo.channel_signature_is_valid
                )
            # resolve by partial/complete claim id
            for key, claim_txo in self.prefix_db.claim_short_id.iterate(prefix=(normalized_name, claim_id[:10])):
                claim_hash = self.txo_to_claim[claim_txo.tx_num][claim_txo.position]
                non_normalized_name = self.claim_to_txo.get(claim_hash).name
                signature_is_valid = self.claim_to_txo.get(claim_hash).channel_signature_is_valid
                return self._prepare_resolve_result(
                    claim_txo.tx_num, claim_txo.position, claim_hash, non_normalized_name, key.root_tx_num,
                    key.root_position, self.get_activation(claim_txo.tx_num, claim_txo.position),
                    signature_is_valid
                )
            return

        # resolve by amount ordering, 1 indexed
        for idx, (key, claim_val) in enumerate(self.prefix_db.effective_amount.iterate(prefix=(normalized_name,))):
            if amount_order > idx + 1:
                continue
            claim_txo = self.claim_to_txo.get(claim_val.claim_hash)
            activation = self.get_activation(key.tx_num, key.position)
            return self._prepare_resolve_result(
                key.tx_num, key.position, claim_val.claim_hash, key.normalized_name, claim_txo.root_tx_num,
                claim_txo.root_position, activation, claim_txo.channel_signature_is_valid
            )
        return

    def _resolve_claim_in_channel(self, channel_hash: bytes, normalized_name: str):
        candidates = []
        for key, stream in self.prefix_db.channel_to_claim.iterate(prefix=(channel_hash, normalized_name)):
            effective_amount = self.get_effective_amount(stream.claim_hash)
            if not candidates or candidates[-1][-1] == effective_amount:
                candidates.append((stream.claim_hash, key.tx_num, key.position, effective_amount))
            else:
                break
        if not candidates:
            return
        return list(sorted(candidates, key=lambda item: item[1]))[0]

    def _fs_resolve(self, url) -> typing.Tuple[OptionalResolveResultOrError, OptionalResolveResultOrError,
                                               OptionalResolveResultOrError]:
        try:
            parsed = URL.parse(url)
        except ValueError as e:
            return e, None, None

        stream = channel = resolved_channel = resolved_stream = None
        if parsed.has_stream_in_channel:
            channel = parsed.channel
            stream = parsed.stream
        elif parsed.has_channel:
            channel = parsed.channel
        elif parsed.has_stream:
            stream = parsed.stream
        if channel:
            resolved_channel = self._resolve(channel.name, channel.claim_id, channel.amount_order)
            if not resolved_channel:
                return None, LookupError(f'Could not find channel in "{url}".'), None
        if stream:
            if resolved_channel:
                stream_claim = self._resolve_claim_in_channel(resolved_channel.claim_hash, stream.normalized)
                if stream_claim:
                    stream_claim_id, stream_tx_num, stream_tx_pos, effective_amount = stream_claim
                    resolved_stream = self._fs_get_claim_by_hash(stream_claim_id)
            else:
                resolved_stream = self._resolve(stream.name, stream.claim_id, stream.amount_order)
                if not channel and not resolved_channel and resolved_stream and resolved_stream.channel_hash:
                    resolved_channel = self._fs_get_claim_by_hash(resolved_stream.channel_hash)
            if not resolved_stream:
                return LookupError(f'Could not find claim at "{url}".'), None, None

        repost = None
        if resolved_stream or resolved_channel:
            claim_hash = resolved_stream.claim_hash if resolved_stream else resolved_channel.claim_hash
            claim = resolved_stream if resolved_stream else resolved_channel
            reposted_claim_hash = resolved_stream.reposted_claim_hash if resolved_stream else None
            blocker_hash = self.blocked_streams.get(claim_hash) or self.blocked_streams.get(
                reposted_claim_hash) or self.blocked_channels.get(claim_hash) or self.blocked_channels.get(
                reposted_claim_hash) or self.blocked_channels.get(claim.channel_hash)
            if blocker_hash:
                reason_row = self._fs_get_claim_by_hash(blocker_hash)
                return None, ResolveCensoredError(url, blocker_hash, censor_row=reason_row), None
            if claim.reposted_claim_hash:
                repost = self._fs_get_claim_by_hash(claim.reposted_claim_hash)
        return resolved_stream, resolved_channel, repost

    async def fs_resolve(self, url) -> typing.Tuple[OptionalResolveResultOrError, OptionalResolveResultOrError,
                                                    OptionalResolveResultOrError]:
         return await asyncio.get_event_loop().run_in_executor(None, self._fs_resolve, url)

    def _fs_get_claim_by_hash(self, claim_hash):
        claim = self.claim_to_txo.get(claim_hash)
        if claim:
            activation = self.get_activation(claim.tx_num, claim.position)
            return self._prepare_resolve_result(
                claim.tx_num, claim.position, claim_hash, claim.name, claim.root_tx_num, claim.root_position,
                activation, claim.channel_signature_is_valid
            )

    async def fs_getclaimbyid(self, claim_id):
        return await asyncio.get_event_loop().run_in_executor(
            None, self._fs_get_claim_by_hash, bytes.fromhex(claim_id)
        )

    def get_claim_txo_amount(self, claim_hash: bytes) -> Optional[int]:
        claim = self.get_claim_txo(claim_hash)
        if claim:
            return claim.amount

    def get_block_hash(self, height: int) -> Optional[bytes]:
        v = self.prefix_db.block_hash.get(height)
        if v:
            return v.block_hash

    def get_support_txo_amount(self, claim_hash: bytes, tx_num: int, position: int) -> Optional[int]:
        v = self.prefix_db.claim_to_support.get(claim_hash, tx_num, position)
        return None if not v else v.amount

    def get_claim_txo(self, claim_hash: bytes) -> Optional[ClaimToTXOValue]:
        assert claim_hash
        return self.prefix_db.claim_to_txo.get(claim_hash)

    def _get_active_amount(self, claim_hash: bytes, txo_type: int, height: int) -> int:
        return sum(
            v.amount for v in self.prefix_db.active_amount.iterate(
                start=(claim_hash, txo_type, 0), stop=(claim_hash, txo_type, height), include_key=False
            )
        )

    def get_active_amount_as_of_height(self, claim_hash: bytes, height: int) -> int:
        for v in self.prefix_db.active_amount.iterate(
                start=(claim_hash, ACTIVATED_CLAIM_TXO_TYPE, 0), stop=(claim_hash, ACTIVATED_CLAIM_TXO_TYPE, height),
                include_key=False, reverse=True):
            return v.amount
        return 0

    def get_effective_amount(self, claim_hash: bytes, support_only=False) -> int:
        support_amount = self._get_active_amount(claim_hash, ACTIVATED_SUPPORT_TXO_TYPE, self.db_height + 1)
        if support_only:
            return support_only
        return support_amount + self._get_active_amount(claim_hash, ACTIVATED_CLAIM_TXO_TYPE, self.db_height + 1)

    def get_url_effective_amount(self, name: str, claim_hash: bytes) -> Optional['EffectiveAmountKey']:
        for k, v in self.prefix_db.effective_amount.iterate(prefix=(name,)):
            if v.claim_hash == claim_hash:
                return k

    def get_claims_for_name(self, name):
        claims = []
        prefix = self.prefix_db.claim_short_id.pack_partial_key(name) + bytes([1])
        for _k, _v in self.prefix_db.iterator(prefix=prefix):
            v = self.prefix_db.claim_short_id.unpack_value(_v)
            claim_hash = self.get_claim_from_txo(v.tx_num, v.position).claim_hash
            if claim_hash not in claims:
                claims.append(claim_hash)
        return claims

    def get_claims_in_channel_count(self, channel_hash) -> int:
        channel_count_val = self.prefix_db.channel_count.get(channel_hash)
        if channel_count_val is None:
            return 0
        return channel_count_val.count

    async def reload_blocking_filtering_streams(self):
        def reload():
            self.blocked_streams, self.blocked_channels = self.get_streams_and_channels_reposted_by_channel_hashes(
                self.blocking_channel_hashes
            )
            self.filtered_streams, self.filtered_channels = self.get_streams_and_channels_reposted_by_channel_hashes(
                self.filtering_channel_hashes
            )
        await asyncio.get_event_loop().run_in_executor(None, reload)

    def get_streams_and_channels_reposted_by_channel_hashes(self, reposter_channel_hashes: Set[bytes]):
        streams, channels = {}, {}
        for reposter_channel_hash in reposter_channel_hashes:
            for stream in self.prefix_db.channel_to_claim.iterate((reposter_channel_hash, ), include_key=False):
                repost = self.get_repost(stream.claim_hash)
                if repost:
                    txo = self.get_claim_txo(repost)
                    if txo:
                        if txo.normalized_name.startswith('@'):
                            channels[repost] = reposter_channel_hash
                        else:
                            streams[repost] = reposter_channel_hash
        return streams, channels

    def get_channel_for_claim(self, claim_hash, tx_num, position) -> Optional[bytes]:
        v = self.prefix_db.claim_to_channel.get(claim_hash, tx_num, position)
        if v:
            return v.signing_hash

    def get_expired_by_height(self, height: int) -> Dict[bytes, Tuple[int, int, str, TxInput]]:
        expired = {}
        for k, v in self.prefix_db.claim_expiration.iterate(prefix=(height,)):
            tx_hash = self.prefix_db.tx_hash.get(k.tx_num, deserialize_value=False)
            tx = self.coin.transaction(self.prefix_db.tx.get(tx_hash, deserialize_value=False))
            # treat it like a claim spend so it will delete/abandon properly
            # the _spend_claim function this result is fed to expects a txi, so make a mock one
            # print(f"\texpired lbry://{v.name} {v.claim_hash.hex()}")
            expired[v.claim_hash] = (
                k.tx_num, k.position, v.normalized_name,
                TxInput(prev_hash=tx_hash, prev_idx=k.position, script=tx.outputs[k.position].pk_script, sequence=0)
            )
        return expired

    def get_controlling_claim(self, name: str) -> Optional[ClaimTakeoverValue]:
        controlling = self.prefix_db.claim_takeover.get(name)
        if not controlling:
            return
        return controlling

    def get_claim_txos_for_name(self, name: str):
        txos = {}
        prefix = self.prefix_db.claim_short_id.pack_partial_key(name) + int(1).to_bytes(1, byteorder='big')
        for k, v in self.prefix_db.iterator(prefix=prefix):
            tx_num, nout = self.prefix_db.claim_short_id.unpack_value(v)
            txos[self.get_claim_from_txo(tx_num, nout).claim_hash] = tx_num, nout
        return txos

    def get_claim_metadata(self, tx_hash, nout):
        raw = self.prefix_db.tx.get(tx_hash, deserialize_value=False)
        try:
            output = self.coin.transaction(raw).outputs[nout]
            script = OutputScript(output.pk_script)
            script.parse()
            return Claim.from_bytes(script.values['claim'])
        except:
            self.logger.error(
                "tx parsing for ES went boom %s %s", tx_hash[::-1].hex(),
                (raw or b'').hex()
            )
            return

    def _prepare_claim_for_sync(self, claim_hash: bytes):
        claim = self._fs_get_claim_by_hash(claim_hash)
        if not claim:
            print("wat")
            return
        return self._prepare_claim_metadata(claim_hash, claim)

    def _prepare_claim_metadata(self, claim_hash: bytes, claim: ResolveResult):
        metadata = self.get_claim_metadata(claim.tx_hash, claim.position)
        if not metadata:
            return
        metadata = metadata
        if not metadata.is_stream or not metadata.stream.has_fee:
            fee_amount = 0
        else:
            fee_amount = int(max(metadata.stream.fee.amount or 0, 0) * 1000)
            if fee_amount >= 9223372036854775807:
                return
        reposted_claim_hash = None if not metadata.is_repost else metadata.repost.reference.claim_hash[::-1]
        reposted_claim = None
        reposted_metadata = None
        if reposted_claim_hash:
            reposted_claim = self.claim_to_txo.get(reposted_claim_hash)
            if not reposted_claim:
                return
            reposted_metadata = self.get_claim_metadata(
                self.prefix_db.tx_hash.get(reposted_claim.tx_num, deserialize_value=False), reposted_claim.position
            )
            if not reposted_metadata:
                return
        reposted_tags = []
        reposted_languages = []
        reposted_has_source = False
        reposted_claim_type = None
        reposted_stream_type = None
        reposted_media_type = None
        reposted_fee_amount = None
        reposted_fee_currency = None
        reposted_duration = None
        if reposted_claim:
            reposted_tx_hash = self.prefix_db.tx_hash.get(reposted_claim.tx_num, deserialize_value=False)
            raw_reposted_claim_tx = self.prefix_db.tx.get(reposted_tx_hash, deserialize_value=False)
            try:
                reposted_claim_txo = self.coin.transaction(
                    raw_reposted_claim_tx
                ).outputs[reposted_claim.position]
                reposted_script = OutputScript(reposted_claim_txo.pk_script)
                reposted_script.parse()
            except:
                self.logger.error(
                    "repost tx parsing for ES went boom %s %s", reposted_tx_hash[::-1].hex(),
                    raw_reposted_claim_tx.hex()
                )
                return
            try:
                reposted_metadata = Claim.from_bytes(reposted_script.values['claim'])
            except:
                self.logger.error(
                    "reposted claim parsing for ES went boom %s %s", reposted_tx_hash[::-1].hex(),
                    raw_reposted_claim_tx.hex()
                )
                return
        if reposted_metadata:
            if reposted_metadata.is_stream:
                meta = reposted_metadata.stream
            elif reposted_metadata.is_channel:
                meta = reposted_metadata.channel
            elif reposted_metadata.is_collection:
                meta = reposted_metadata.collection
            elif reposted_metadata.is_repost:
                meta = reposted_metadata.repost
            else:
                return
            reposted_tags = [tag for tag in meta.tags]
            reposted_languages = [lang.language or 'none' for lang in meta.languages] or ['none']
            reposted_has_source = False if not reposted_metadata.is_stream else reposted_metadata.stream.has_source
            reposted_claim_type = CLAIM_TYPES[reposted_metadata.claim_type]
            reposted_stream_type = STREAM_TYPES[guess_stream_type(reposted_metadata.stream.source.media_type)] \
                if reposted_metadata.is_stream else 0
            reposted_media_type = reposted_metadata.stream.source.media_type if reposted_metadata.is_stream else 0
            if not reposted_metadata.is_stream or not reposted_metadata.stream.has_fee:
                reposted_fee_amount = 0
            else:
                reposted_fee_amount = int(max(reposted_metadata.stream.fee.amount or 0, 0) * 1000)
                if reposted_fee_amount >= 9223372036854775807:
                    return
            reposted_fee_currency = None if not reposted_metadata.is_stream else reposted_metadata.stream.fee.currency
            reposted_duration = None
            if reposted_metadata.is_stream and \
                    (reposted_metadata.stream.video.duration or reposted_metadata.stream.audio.duration):
                reposted_duration = reposted_metadata.stream.video.duration or reposted_metadata.stream.audio.duration
        if metadata.is_stream:
            meta = metadata.stream
        elif metadata.is_channel:
            meta = metadata.channel
        elif metadata.is_collection:
            meta = metadata.collection
        elif metadata.is_repost:
            meta = metadata.repost
        else:
            return
        claim_tags = [tag for tag in meta.tags]
        claim_languages = [lang.language or 'none' for lang in meta.languages] or ['none']

        tags = list(set(claim_tags).union(set(reposted_tags)))
        languages = list(set(claim_languages).union(set(reposted_languages)))
        blocked_hash = self.blocked_streams.get(claim_hash) or self.blocked_streams.get(
            reposted_claim_hash) or self.blocked_channels.get(claim_hash) or self.blocked_channels.get(
            reposted_claim_hash) or self.blocked_channels.get(claim.channel_hash)
        filtered_hash = self.filtered_streams.get(claim_hash) or self.filtered_streams.get(
            reposted_claim_hash) or self.filtered_channels.get(claim_hash) or self.filtered_channels.get(
            reposted_claim_hash) or self.filtered_channels.get(claim.channel_hash)
        value = {
            'claim_id': claim_hash.hex(),
            'claim_name': claim.name,
            'normalized_name': claim.normalized_name,
            'tx_id': claim.tx_hash[::-1].hex(),
            'tx_num': claim.tx_num,
            'tx_nout': claim.position,
            'amount': claim.amount,
            'timestamp': self.estimate_timestamp(claim.height),
            'creation_timestamp': self.estimate_timestamp(claim.creation_height),
            'height': claim.height,
            'creation_height': claim.creation_height,
            'activation_height': claim.activation_height,
            'expiration_height': claim.expiration_height,
            'effective_amount': claim.effective_amount,
            'support_amount': claim.support_amount,
            'is_controlling': bool(claim.is_controlling),
            'last_take_over_height': claim.last_takeover_height,
            'short_url': claim.short_url,
            'canonical_url': claim.canonical_url,
            'title': None if not metadata.is_stream else metadata.stream.title,
            'author': None if not metadata.is_stream else metadata.stream.author,
            'description': None if not metadata.is_stream else metadata.stream.description,
            'claim_type': CLAIM_TYPES[metadata.claim_type],
            'has_source': reposted_has_source if metadata.is_repost else (
                False if not metadata.is_stream else metadata.stream.has_source),
            'stream_type': STREAM_TYPES[guess_stream_type(metadata.stream.source.media_type)]
                if metadata.is_stream else reposted_stream_type if metadata.is_repost else 0,
            'media_type': metadata.stream.source.media_type
                if metadata.is_stream else reposted_media_type if metadata.is_repost else None,
            'fee_amount': fee_amount if not metadata.is_repost else reposted_fee_amount,
            'fee_currency': metadata.stream.fee.currency
                if metadata.is_stream else reposted_fee_currency if metadata.is_repost else None,
            'repost_count': self.get_reposted_count(claim_hash),
            'reposted_claim_id': None if not reposted_claim_hash else reposted_claim_hash.hex(),
            'reposted_claim_type': reposted_claim_type,
            'reposted_has_source': reposted_has_source,
            'channel_id': None if not metadata.is_signed else metadata.signing_channel_hash[::-1].hex(),
            'public_key_id': None if not metadata.is_channel else
            self.ledger.public_key_to_address(metadata.channel.public_key_bytes),
            'signature': (metadata.signature or b'').hex() or None,
            # 'signature_digest': metadata.signature,
            'is_signature_valid': bool(claim.signature_valid),
            'tags': tags,
            'languages': languages,
            'censor_type': Censor.RESOLVE if blocked_hash else Censor.SEARCH if filtered_hash else Censor.NOT_CENSORED,
            'censoring_channel_id': (blocked_hash or filtered_hash or b'').hex() or None,
            'claims_in_channel': None if not metadata.is_channel else self.get_claims_in_channel_count(claim_hash)
        }

        if metadata.is_repost and reposted_duration is not None:
            value['duration'] = reposted_duration
        elif metadata.is_stream and (metadata.stream.video.duration or metadata.stream.audio.duration):
            value['duration'] = metadata.stream.video.duration or metadata.stream.audio.duration
        if metadata.is_stream:
            value['release_time'] = metadata.stream.release_time or value['creation_timestamp']
        elif metadata.is_repost or metadata.is_collection:
            value['release_time'] = value['creation_timestamp']
        return value

    async def all_claims_producer(self, batch_size=500_000):
        batch = []
        for claim_hash, claim_txo in self.claim_to_txo.items():
            # TODO: fix the couple of claim txos that dont have controlling names
            if not self.prefix_db.claim_takeover.get(claim_txo.normalized_name):
                continue
            claim = self._fs_get_claim_by_hash(claim_hash)
            if claim:
                batch.append(claim)
            if len(batch) == batch_size:
                batch.sort(key=lambda x: x.tx_hash)
                for claim in batch:
                    meta = self._prepare_claim_metadata(claim.claim_hash, claim)
                    if meta:
                        yield meta
                batch.clear()
        batch.sort(key=lambda x: x.tx_hash)
        for claim in batch:
            meta = self._prepare_claim_metadata(claim.claim_hash, claim)
            if meta:
                yield meta
        batch.clear()

    async def claims_producer(self, claim_hashes: Set[bytes]):
        batch = []
        results = []

        loop = asyncio.get_event_loop()

        def produce_claim(claim_hash):
            if claim_hash not in self.claim_to_txo:
                self.logger.warning("can't sync non existent claim to ES: %s", claim_hash.hex())
                return
            name = self.claim_to_txo[claim_hash].normalized_name
            if not self.prefix_db.claim_takeover.get(name):
                self.logger.warning("can't sync non existent claim to ES: %s", claim_hash.hex())
                return
            claim_txo = self.claim_to_txo.get(claim_hash)
            if not claim_txo:
                return
            activation = self.get_activation(claim_txo.tx_num, claim_txo.position)
            claim = self._prepare_resolve_result(
                claim_txo.tx_num, claim_txo.position, claim_hash, claim_txo.name, claim_txo.root_tx_num,
                claim_txo.root_position, activation, claim_txo.channel_signature_is_valid
            )
            if claim:
                batch.append(claim)

        def get_metadata(claim):
            meta = self._prepare_claim_metadata(claim.claim_hash, claim)
            if meta:
                results.append(meta)

        if claim_hashes:
            await asyncio.wait(
                [loop.run_in_executor(None, produce_claim, claim_hash) for claim_hash in claim_hashes]
            )
        batch.sort(key=lambda x: x.tx_hash)

        if batch:
            await asyncio.wait(
                [loop.run_in_executor(None, get_metadata, claim) for claim in batch]
            )
        for meta in results:
            yield meta

        batch.clear()

    def get_activated_at_height(self, height: int) -> DefaultDict[PendingActivationValue, List[PendingActivationKey]]:
        activated = defaultdict(list)
        for k, v in self.prefix_db.pending_activation.iterate(prefix=(height,)):
            activated[v].append(k)
        return activated

    def get_future_activated(self, height: int) -> typing.Dict[PendingActivationValue, PendingActivationKey]:
        results = {}
        for k, v in self.prefix_db.pending_activation.iterate(
                start=(height + 1,), stop=(height + 1 + self.coin.maxTakeoverDelay,), reverse=True):
            if v not in results:
                results[v] = k
        return results

    async def _read_tx_counts(self):
        if self.tx_counts is not None:
            return
        # tx_counts[N] has the cumulative number of txs at the end of
        # height N.  So tx_counts[0] is 1 - the genesis coinbase

        def get_counts():
            return [
                v.tx_count for v in self.prefix_db.tx_count.iterate(include_key=False, fill_cache=False)
            ]

        tx_counts = await asyncio.get_event_loop().run_in_executor(None, get_counts)
        assert len(tx_counts) == self.db_height + 1, f"{len(tx_counts)} vs {self.db_height + 1}"
        self.tx_counts = array.array('I', tx_counts)

        if self.tx_counts:
            assert self.db_tx_count == self.tx_counts[-1], \
                f"{self.db_tx_count} vs {self.tx_counts[-1]} ({len(self.tx_counts)} counts)"
        else:
            assert self.db_tx_count == 0


    async def _read_claim_txos(self):
        def read_claim_txos():
            set_claim_to_txo = self.claim_to_txo.__setitem__
            for k, v in self.prefix_db.claim_to_txo.iterate(fill_cache=False):
                set_claim_to_txo(k.claim_hash, v)
                self.txo_to_claim[v.tx_num][v.position] = k.claim_hash

        self.claim_to_txo.clear()
        self.txo_to_claim.clear()
        start = time.perf_counter()
        self.logger.info("loading claims")
        await asyncio.get_event_loop().run_in_executor(None, read_claim_txos)
        ts = time.perf_counter() - start
        self.logger.info("loaded %i claim txos in %ss", len(self.claim_to_txo), round(ts, 4))

    async def _read_headers(self):
        if self.headers is not None:
            return

        def get_headers():
            return [
                header for header in self.prefix_db.header.iterate(
                    include_key=False, fill_cache=False, deserialize_value=False
                )
            ]

        headers = await asyncio.get_event_loop().run_in_executor(None, get_headers)
        assert len(headers) - 1 == self.db_height, f"{len(headers)} vs {self.db_height}"
        self.headers = headers

    def estimate_timestamp(self, height: int) -> int:
        if height < len(self.headers):
            return struct.unpack('<I', self.headers[height][100:104])[0]
        return int(160.6855883050695 * height)

    async def open_dbs(self):
        if self.prefix_db and not self.prefix_db.closed:
            return

        self.prefix_db = HubDB(
            os.path.join(self.env.db_dir, 'lbry-leveldb'), self.env.reorg_limit, self.env.cache_MB,
            max_open_files=512
        )
        self.logger.info(f'opened db: lbry-leveldb')

        # read db state
        self.read_db_state()

        # These are our state as we move ahead of DB state
        self.fs_height = self.db_height
        self.fs_tx_count = self.db_tx_count
        self.last_flush_tx_count = self.fs_tx_count

        # Log some stats
        self.logger.info(f'DB version: {self.db_version:d}')
        self.logger.info(f'coin: {self.coin.NAME}')
        self.logger.info(f'network: {self.coin.NET}')
        self.logger.info(f'height: {self.db_height:,d}')
        self.logger.info(f'tip: {hash_to_hex_str(self.db_tip)}')
        self.logger.info(f'tx count: {self.db_tx_count:,d}')
        if self.first_sync:
            self.logger.info(f'sync time so far: {util.formatted_time(self.wall_time)}')
        if self.hist_db_version not in self.DB_VERSIONS:
            msg = f'this software only handles DB versions {self.DB_VERSIONS}'
            self.logger.error(msg)
            raise RuntimeError(msg)
        self.logger.info(f'flush count: {self.hist_flush_count:,d}')

        self.utxo_flush_count = self.hist_flush_count

        # Read TX counts (requires meta directory)
        await self._read_tx_counts()
        await self._read_headers()
        await self._read_claim_txos()

        # start search index
        await self.search_index.start()

    def close(self):
        self.prefix_db.close()

    # Header merkle cache

    async def populate_header_merkle_cache(self):
        self.logger.info('populating header merkle cache...')
        length = max(1, self.db_height - self.env.reorg_limit)
        start = time.time()
        await self.header_mc.initialize(length)
        elapsed = time.time() - start
        self.logger.info(f'header merkle cache populated in {elapsed:.1f}s')

    async def header_branch_and_root(self, length, height):
        return await self.header_mc.branch_and_root(length, height)

    def raw_header(self, height):
        """Return the binary header at the given height."""
        header, n = self.read_headers(height, 1)
        if n != 1:
            raise IndexError(f'height {height:,d} out of range')
        return header

    def encode_headers(self, start_height, count, headers):
        key = (start_height, count)
        if not self.encoded_headers.get(key):
            compressobj = zlib.compressobj(wbits=-15, level=1, memLevel=9)
            headers = base64.b64encode(compressobj.compress(headers) + compressobj.flush()).decode()
            if start_height % 1000 != 0:
                return headers
            self.encoded_headers[key] = headers
        return self.encoded_headers.get(key)

    def read_headers(self, start_height, count) -> typing.Tuple[bytes, int]:
        """Requires start_height >= 0, count >= 0.  Reads as many headers as
        are available starting at start_height up to count.  This
        would be zero if start_height is beyond self.db_height, for
        example.

        Returns a (binary, n) pair where binary is the concatenated
        binary headers, and n is the count of headers returned.
        """

        if start_height < 0 or count < 0:
            raise DBError(f'{count:,d} headers starting at {start_height:,d} not on disk')

        disk_count = max(0, min(count, self.db_height + 1 - start_height))
        if disk_count:
            return b''.join(self.headers[start_height:start_height + disk_count]), disk_count
        return b'', 0

    def fs_tx_hash(self, tx_num):
        """Return a par (tx_hash, tx_height) for the given tx number.

        If the tx_height is not on disk, returns (None, tx_height)."""
        tx_height = bisect_right(self.tx_counts, tx_num)
        if tx_height > self.db_height:
            return None, tx_height
        try:
            return self.prefix_db.tx_hash.get(tx_num, deserialize_value=False), tx_height
        except IndexError:
            self.logger.exception(
                "Failed to access a cached transaction, known bug #3142 "
                "should be fixed in #3205"
            )
            return None, tx_height

    def get_block_txs(self, height: int) -> List[bytes]:
        return [
            tx_hash for tx_hash in self.prefix_db.tx_hash.iterate(
                start=(self.tx_counts[height-1],), stop=(self.tx_counts[height],),
                deserialize_value=False, include_key=False
            )
        ]

    def _fs_transactions(self, txids: Iterable[str]):
        tx_counts = self.tx_counts
        tx_db_get = self.prefix_db.tx.get
        tx_cache = self._tx_and_merkle_cache
        tx_infos = {}

        for tx_hash in txids:
            cached_tx = tx_cache.get(tx_hash)
            if cached_tx:
                tx, merkle = cached_tx
            else:
                tx_hash_bytes = bytes.fromhex(tx_hash)[::-1]
                tx_num = self.prefix_db.tx_num.get(tx_hash_bytes)
                tx = None
                tx_height = -1
                tx_num = None if not tx_num else tx_num.tx_num
                if tx_num is not None:
                    fill_cache = tx_num in self.txo_to_claim and len(self.txo_to_claim[tx_num]) > 0
                    tx_height = bisect_right(tx_counts, tx_num)
                    tx = tx_db_get(tx_hash_bytes, fill_cache=fill_cache, deserialize_value=False)
                if tx_height == -1:
                    merkle = {
                        'block_height': -1
                    }
                else:
                    tx_pos = tx_num - tx_counts[tx_height - 1]
                    branch, root = self.merkle.branch_and_root(
                        self.get_block_txs(tx_height), tx_pos
                    )
                    merkle = {
                        'block_height': tx_height,
                        'merkle': [
                            hash_to_hex_str(hash)
                            for hash in branch
                        ],
                        'pos': tx_pos
                    }
                if tx_height + 10 < self.db_height:
                    tx_cache[tx_hash] = tx, merkle
            tx_infos[tx_hash] = (None if not tx else tx.hex(), merkle)
        return tx_infos

    async def fs_transactions(self, txids):
        return await asyncio.get_event_loop().run_in_executor(None, self._fs_transactions, txids)

    async def fs_block_hashes(self, height, count):
        if height + count > len(self.headers):
            raise DBError(f'only got {len(self.headers) - height:,d} headers starting at {height:,d}, not {count:,d}')
        return [self.coin.header_hash(header) for header in self.headers[height:height + count]]

    def read_history(self, hashX: bytes, limit: int = 1000) -> List[Tuple[bytes, int]]:
        txs = []
        txs_extend = txs.extend
        for hist in self.prefix_db.hashX_history.iterate(prefix=(hashX,), include_key=False):
            txs_extend([
                (self.prefix_db.tx_hash.get(tx_num, deserialize_value=False), bisect_right(self.tx_counts, tx_num))
                for tx_num in hist
            ])
            if len(txs) >= limit:
                break
        return txs

    async def limited_history(self, hashX, *, limit=1000):
        """Return an unpruned, sorted list of (tx_hash, height) tuples of
        confirmed transactions that touched the address, earliest in
        the blockchain first.  Includes both spending and receiving
        transactions.  By default returns at most 1000 entries.  Set
        limit to None to get them all.
        """
        return await asyncio.get_event_loop().run_in_executor(None, self.read_history, hashX, limit)

    # -- Undo information

    def min_undo_height(self, max_height):
        """Returns a height from which we should store undo info."""
        return max_height - self.env.reorg_limit + 1

    def apply_expiration_extension_fork(self):
        # TODO: this can't be reorged
        for k, v in self.prefix_db.claim_expiration.iterate():
            self.prefix_db.claim_expiration.stage_delete(k, v)
            self.prefix_db.claim_expiration.stage_put(
                (bisect_right(self.tx_counts, k.tx_num) + self.coin.nExtendedClaimExpirationTime,
                 k.tx_num, k.position), v
            )
        self.prefix_db.unsafe_commit()

    def write_db_state(self):
        """Write (UTXO) state to the batch."""
        if self.db_height > 0:
            self.prefix_db.db_state.stage_delete((), self.prefix_db.db_state.get())
        self.prefix_db.db_state.stage_put((), (
                self.genesis_bytes, self.db_height, self.db_tx_count, self.db_tip,
                self.utxo_flush_count, int(self.wall_time), self.first_sync, self.db_version,
                self.hist_flush_count, self.hist_comp_flush_count, self.hist_comp_cursor
            )
        )

    def read_db_state(self):
        state = self.prefix_db.db_state.get()

        if not state:
            self.db_height = -1
            self.db_tx_count = 0
            self.db_tip = b'\0' * 32
            self.db_version = max(self.DB_VERSIONS)
            self.utxo_flush_count = 0
            self.wall_time = 0
            self.first_sync = True
            self.hist_flush_count = 0
            self.hist_comp_flush_count = -1
            self.hist_comp_cursor = -1
            self.hist_db_version = max(self.DB_VERSIONS)
        else:
            self.db_version = state.db_version
            if self.db_version not in self.DB_VERSIONS:
                raise DBError(f'your DB version is {self.db_version} but this '
                                   f'software only handles versions {self.DB_VERSIONS}')
            # backwards compat
            genesis_hash = state.genesis
            if genesis_hash.hex() != self.coin.GENESIS_HASH:
                raise DBError(f'DB genesis hash {genesis_hash} does not '
                                   f'match coin {self.coin.GENESIS_HASH}')
            self.db_height = state.height
            self.db_tx_count = state.tx_count
            self.db_tip = state.tip
            self.utxo_flush_count = state.utxo_flush_count
            self.wall_time = state.wall_time
            self.first_sync = state.first_sync
            self.hist_flush_count = state.hist_flush_count
            self.hist_comp_flush_count = state.comp_flush_count
            self.hist_comp_cursor = state.comp_cursor
            self.hist_db_version = state.db_version

    def assert_db_state(self):
        state = self.prefix_db.db_state.get()
        assert self.db_version == state.db_version
        assert self.db_height == state.height
        assert self.db_tx_count == state.tx_count
        assert self.db_tip == state.tip
        assert self.first_sync == state.first_sync

    async def all_utxos(self, hashX):
        """Return all UTXOs for an address sorted in no particular order."""
        def read_utxos():
            utxos = []
            utxos_append = utxos.append
            fs_tx_hash = self.fs_tx_hash
            for k, v in self.prefix_db.utxo.iterate(prefix=(hashX, )):
                tx_hash, height = fs_tx_hash(k.tx_num)
                utxos_append(UTXO(k.tx_num, k.nout, tx_hash, height, v.amount))
            return utxos

        while True:
            utxos = await asyncio.get_event_loop().run_in_executor(None, read_utxos)
            if all(utxo.tx_hash is not None for utxo in utxos):
                return utxos
            self.logger.warning(f'all_utxos: tx hash not '
                                f'found (reorg?), retrying...')
            await sleep(0.25)

    async def lookup_utxos(self, prevouts):
        def lookup_utxos():
            utxos = []
            utxo_append = utxos.append
            for (tx_hash, nout) in prevouts:
                tx_num_val = self.prefix_db.tx_num.get(tx_hash)
                if not tx_num_val:
                    continue
                tx_num = tx_num_val.tx_num
                hashX_val = self.prefix_db.hashX_utxo.get(tx_hash[:4], tx_num, nout)
                if not hashX_val:
                    continue
                hashX = hashX_val.hashX
                utxo_value = self.prefix_db.utxo.get(hashX, tx_num, nout)
                if utxo_value:
                    utxo_append((hashX, utxo_value.amount))
            return utxos
        return await asyncio.get_event_loop().run_in_executor(None, lookup_utxos)
