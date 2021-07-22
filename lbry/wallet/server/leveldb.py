# Copyright (c) 2016, Neil Booth
# Copyright (c) 2017, the ElectrumX authors
#
# All rights reserved.
#
# See the file "LICENCE" for information about the copyright
# and warranty status of this software.

"""Interface to the blockchain database."""


import asyncio
import array
import os
import time
import typing
import struct
import attr
import zlib
import base64
from typing import Optional, Iterable, Tuple, DefaultDict, Set, Dict, List
from functools import partial
from asyncio import sleep
from bisect import bisect_right, bisect_left
from collections import defaultdict
from glob import glob
from struct import pack, unpack
from concurrent.futures.thread import ThreadPoolExecutor
from lbry.utils import LRUCacheWithMetrics
from lbry.schema.url import URL
from lbry.wallet.server import util
from lbry.wallet.server.hash import hash_to_hex_str, CLAIM_HASH_LEN
from lbry.wallet.server.tx import TxInput
from lbry.wallet.server.merkle import Merkle, MerkleCache
from lbry.wallet.server.util import formatted_time, pack_be_uint16, unpack_be_uint16_from
from lbry.wallet.server.storage import db_class
from lbry.wallet.server.db.revertable import RevertablePut, RevertableDelete, RevertableOp, RevertableOpStack
from lbry.wallet.server.db import DB_PREFIXES
from lbry.wallet.server.db.common import ResolveResult, STREAM_TYPES, CLAIM_TYPES
from lbry.wallet.server.db.prefixes import Prefixes, PendingActivationValue, ClaimTakeoverValue, ClaimToTXOValue
from lbry.wallet.server.db.prefixes import ACTIVATED_CLAIM_TXO_TYPE, ACTIVATED_SUPPORT_TXO_TYPE
from lbry.wallet.server.db.prefixes import PendingActivationKey, ClaimToTXOKey, TXOToClaimValue
from lbry.wallet.server.db.claimtrie import length_encoded_name
from lbry.wallet.transaction import OutputScript
from lbry.schema.claim import Claim, guess_stream_type
from lbry.wallet.ledger import Ledger, RegTestLedger, TestNetLedger

from lbry.wallet.server.db.elasticsearch import SearchIndex


class UTXO(typing.NamedTuple):
    tx_num: int
    tx_pos: int
    tx_hash: bytes
    height: int
    value: int


TXO_STRUCT = struct.Struct(b'>LH')
TXO_STRUCT_unpack = TXO_STRUCT.unpack
TXO_STRUCT_pack = TXO_STRUCT.pack


@attr.s(slots=True)
class FlushData:
    height = attr.ib()
    tx_count = attr.ib()
    block_hashes = attr.ib()
    block_txs = attr.ib()
    put_and_delete_ops = attr.ib()
    tip = attr.ib()


OptionalResolveResultOrError = Optional[typing.Union[ResolveResult, LookupError, ValueError]]

DB_STATE_STRUCT = struct.Struct(b'>32sLL32sLLBBlll')
DB_STATE_STRUCT_SIZE = 94


class DBState(typing.NamedTuple):
    genesis: bytes
    height: int
    tx_count: int
    tip: bytes
    utxo_flush_count: int
    wall_time: int
    first_sync: bool
    db_version: int
    hist_flush_count: int
    comp_flush_count: int
    comp_cursor: int

    def pack(self) -> bytes:
        return DB_STATE_STRUCT.pack(
            self.genesis, self.height, self.tx_count, self.tip, self.utxo_flush_count,
            self.wall_time, 1 if self.first_sync else 0, self.db_version, self.hist_flush_count,
            self.comp_flush_count, self.comp_cursor
        )

    @classmethod
    def unpack(cls, packed: bytes) -> 'DBState':
        return cls(*DB_STATE_STRUCT.unpack(packed[:DB_STATE_STRUCT_SIZE]))


class DBError(Exception):
    """Raised on general DB errors generally indicating corruption."""


class LevelDB:
    DB_VERSIONS = HIST_DB_VERSIONS = [7]

    def __init__(self, env):
        self.logger = util.class_logger(__name__, self.__class__.__name__)
        self.env = env
        self.coin = env.coin
        self.executor = None

        self.logger.info(f'switching current directory to {env.db_dir}')

        self.db_class = db_class(env.db_dir, self.env.db_engine)
        self.db = None

        self.hist_unflushed = defaultdict(partial(array.array, 'I'))
        self.hist_unflushed_count = 0
        self.hist_flush_count = 0
        self.hist_comp_flush_count = -1
        self.hist_comp_cursor = -1

        self.tx_counts = None
        self.headers = None
        self.encoded_headers = LRUCacheWithMetrics(1 << 21, metric_name='encoded_headers', namespace='wallet_server')
        self.last_flush = time.time()

        self.logger.info(f'using {self.env.db_engine} for DB backend')

        # Header merkle cache
        self.merkle = Merkle()
        self.header_mc = MerkleCache(self.merkle, self.fs_block_hashes)

        self._tx_and_merkle_cache = LRUCacheWithMetrics(2 ** 17, metric_name='tx_and_merkle', namespace="wallet_server")
        self.total_transactions = None
        self.transaction_num_mapping = {}

        # Search index
        self.search_index = SearchIndex(
            self.env.es_index_prefix, self.env.database_query_timeout,
            elastic_host=env.elastic_host, elastic_port=env.elastic_port
        )

        self.genesis_bytes = bytes.fromhex(self.coin.GENESIS_HASH)

        if env.coin.NET == 'mainnet':
            self.ledger = Ledger
        elif env.coin.NET == 'testnet':
            self.ledger = TestNetLedger
        else:
            self.ledger = RegTestLedger

    def get_claim_from_txo(self, tx_num: int, tx_idx: int) -> Optional[TXOToClaimValue]:
        claim_hash_and_name = self.db.get(Prefixes.txo_to_claim.pack_key(tx_num, tx_idx))
        if not claim_hash_and_name:
            return
        return Prefixes.txo_to_claim.unpack_value(claim_hash_and_name)

    def get_repost(self, claim_hash) -> Optional[bytes]:
        repost = self.db.get(Prefixes.repost.pack_key(claim_hash))
        if repost:
            return Prefixes.repost.unpack_value(repost).reposted_claim_hash
        return

    def get_reposted_count(self, claim_hash: bytes) -> int:
        cnt = 0
        for _ in self.db.iterator(prefix=Prefixes.reposted_claim.pack_partial_key(claim_hash)):
            cnt += 1
        return cnt

    def get_activation(self, tx_num, position, is_support=False) -> int:
        activation = self.db.get(
            Prefixes.activated.pack_key(
                ACTIVATED_SUPPORT_TXO_TYPE if is_support else ACTIVATED_CLAIM_TXO_TYPE, tx_num, position
            )
        )
        if activation:
            return Prefixes.activated.unpack_value(activation).height
        return -1

    def get_supported_claim_from_txo(self, tx_num: int, position: int) -> typing.Tuple[Optional[bytes], Optional[int]]:
        key = Prefixes.support_to_claim.pack_key(tx_num, position)
        supported_claim_hash = self.db.get(key)
        if supported_claim_hash:
            packed_support_amount = self.db.get(
                Prefixes.claim_to_support.pack_key(supported_claim_hash, tx_num, position)
            )
            if packed_support_amount:
                return supported_claim_hash, Prefixes.claim_to_support.unpack_value(packed_support_amount).amount
        return None, None

    def get_support_amount(self, claim_hash: bytes):
        total = 0
        for packed in self.db.iterator(prefix=DB_PREFIXES.claim_to_support.value + claim_hash, include_key=False):
            total += Prefixes.claim_to_support.unpack_value(packed).amount
        return total

    def get_supports(self, claim_hash: bytes):
        supports = []
        for k, v in self.db.iterator(prefix=DB_PREFIXES.claim_to_support.value + claim_hash):
            unpacked_k = Prefixes.claim_to_support.unpack_key(k)
            unpacked_v = Prefixes.claim_to_support.unpack_value(v)
            supports.append((unpacked_k.tx_num, unpacked_k.position, unpacked_v.amount))
        return supports

    def _prepare_resolve_result(self, tx_num: int, position: int, claim_hash: bytes, name: str, root_tx_num: int,
                                root_position: int, activation_height: int, signature_valid: bool) -> ResolveResult:
        controlling_claim = self.get_controlling_claim(name)

        tx_hash = self.total_transactions[tx_num]
        height = bisect_right(self.tx_counts, tx_num)
        created_height = bisect_right(self.tx_counts, root_tx_num)
        last_take_over_height = controlling_claim.height

        expiration_height = self.coin.get_expiration_height(height)
        support_amount = self.get_support_amount(claim_hash)
        claim_amount = self.get_claim_txo_amount(claim_hash)

        effective_amount = support_amount + claim_amount
        channel_hash = self.get_channel_for_claim(claim_hash, tx_num, position)
        reposted_claim_hash = self.get_repost(claim_hash)

        short_url = f'{name}#{claim_hash.hex()}'
        canonical_url = short_url
        claims_in_channel = self.get_claims_in_channel_count(claim_hash)
        if channel_hash:
            channel_vals = self.get_claim_txo(channel_hash)
            if channel_vals:
                channel_name = channel_vals.name
                canonical_url = f'{channel_name}#{channel_hash.hex()}/{name}#{claim_hash.hex()}'
        return ResolveResult(
            name, claim_hash, tx_num, position, tx_hash, height, claim_amount, short_url=short_url,
            is_controlling=controlling_claim.claim_hash == claim_hash, canonical_url=canonical_url,
            last_takeover_height=last_take_over_height, claims_in_channel=claims_in_channel,
            creation_height=created_height, activation_height=activation_height,
            expiration_height=expiration_height, effective_amount=effective_amount, support_amount=support_amount,
            channel_hash=channel_hash, reposted_claim_hash=reposted_claim_hash,
            reposted=self.get_reposted_count(claim_hash),
            signature_valid=None if not channel_hash else signature_valid
        )

    def _resolve(self, normalized_name: str, claim_id: Optional[str] = None,
                 amount_order: Optional[int] = None) -> Optional[ResolveResult]:
        """
        :param normalized_name: name
        :param claim_id: partial or complete claim id
        :param amount_order: '$<value>' suffix to a url, defaults to 1 (winning) if no claim id modifier is provided
        """
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
            # resolve by partial/complete claim id
            short_claim_hash = bytes.fromhex(claim_id)
            prefix = Prefixes.claim_short_id.pack_partial_key(normalized_name, short_claim_hash)
            for k, v in self.db.iterator(prefix=prefix):
                key = Prefixes.claim_short_id.unpack_key(k)
                claim_txo = Prefixes.claim_short_id.unpack_value(v)
                signature_is_valid = self.get_claim_txo(key.claim_hash).channel_signature_is_valid
                return self._prepare_resolve_result(
                    claim_txo.tx_num, claim_txo.position, key.claim_hash, key.name, key.root_tx_num,
                    key.root_position, self.get_activation(claim_txo.tx_num, claim_txo.position),
                    signature_is_valid
                )
            return

        # resolve by amount ordering, 1 indexed
        prefix = Prefixes.effective_amount.pack_partial_key(normalized_name)
        for idx, (k, v) in enumerate(self.db.iterator(prefix=prefix)):
            if amount_order > idx + 1:
                continue
            key = Prefixes.effective_amount.unpack_key(k)
            claim_val = Prefixes.effective_amount.unpack_value(v)
            claim_txo = self.get_claim_txo(claim_val.claim_hash)
            activation = self.get_activation(key.tx_num, key.position)
            return self._prepare_resolve_result(
                key.tx_num, key.position, claim_val.claim_hash, key.name, claim_txo.root_tx_num,
                claim_txo.root_position, activation, claim_txo.channel_signature_is_valid
            )
        return

    def _resolve_claim_in_channel(self, channel_hash: bytes, normalized_name: str):
        candidates = []
        for k, v in self.db.iterator(prefix=Prefixes.channel_to_claim.pack_partial_key(channel_hash, normalized_name)):
            key = Prefixes.channel_to_claim.unpack_key(k)
            stream = Prefixes.channel_to_claim.unpack_value(v)
            effective_amount = self.get_effective_amount(stream.claim_hash)
            if not candidates or candidates[-1][-1] == effective_amount:
                candidates.append((stream.claim_hash, key.tx_num, key.position, effective_amount))
            else:
                break
        if not candidates:
            return
        return list(sorted(candidates, key=lambda item: item[1]))[0]

    def _fs_resolve(self, url) -> typing.Tuple[OptionalResolveResultOrError, OptionalResolveResultOrError]:
        try:
            parsed = URL.parse(url)
        except ValueError as e:
            return e, None

        stream = channel = resolved_channel = resolved_stream = None
        if parsed.has_stream_in_channel:
            channel = parsed.channel
            stream = parsed.stream
        elif parsed.has_channel:
            channel = parsed.channel
        elif parsed.has_stream:
            stream = parsed.stream
        if channel:
            resolved_channel = self._resolve(channel.normalized, channel.claim_id, channel.amount_order)
            if not resolved_channel:
                return None, LookupError(f'Could not find channel in "{url}".')
        if stream:
            if resolved_channel:
                stream_claim = self._resolve_claim_in_channel(resolved_channel.claim_hash, stream.normalized)
                if stream_claim:
                    stream_claim_id, stream_tx_num, stream_tx_pos, effective_amount = stream_claim
                    resolved_stream = self._fs_get_claim_by_hash(stream_claim_id)
            else:
                resolved_stream = self._resolve(stream.normalized, stream.claim_id, stream.amount_order)
                if not channel and not resolved_channel and resolved_stream and resolved_stream.channel_hash:
                    resolved_channel = self._fs_get_claim_by_hash(resolved_stream.channel_hash)
            if not resolved_stream:
                return LookupError(f'Could not find claim at "{url}".'), None

        return resolved_stream, resolved_channel

    async def fs_resolve(self, url) -> typing.Tuple[OptionalResolveResultOrError, OptionalResolveResultOrError]:
         return await asyncio.get_event_loop().run_in_executor(self.executor, self._fs_resolve, url)

    def _fs_get_claim_by_hash(self, claim_hash):
        claim = self.db.get(Prefixes.claim_to_txo.pack_key(claim_hash))
        if claim:
            v = Prefixes.claim_to_txo.unpack_value(claim)
            activation_height = self.get_activation(v.tx_num, v.position)
            return self._prepare_resolve_result(
                v.tx_num, v.position, claim_hash, v.name,
                v.root_tx_num, v.root_position, activation_height, v.channel_signature_is_valid
            )

    async def fs_getclaimbyid(self, claim_id):
        return await asyncio.get_event_loop().run_in_executor(
            self.executor, self._fs_get_claim_by_hash, bytes.fromhex(claim_id)
        )

    def get_claim_txo_amount(self, claim_hash: bytes) -> Optional[int]:
        v = self.db.get(Prefixes.claim_to_txo.pack_key(claim_hash))
        if v:
            return Prefixes.claim_to_txo.unpack_value(v).amount

    def get_support_txo_amount(self, claim_hash: bytes, tx_num: int, position: int) -> Optional[int]:
        v = self.db.get(Prefixes.claim_to_support.pack_key(claim_hash, tx_num, position))
        if v:
            return Prefixes.claim_to_support.unpack_value(v).amount

    def get_claim_txo(self, claim_hash: bytes) -> Optional[ClaimToTXOValue]:
        assert claim_hash
        v = self.db.get(Prefixes.claim_to_txo.pack_key(claim_hash))
        if v:
            return Prefixes.claim_to_txo.unpack_value(v)

    def _get_active_amount(self, claim_hash: bytes, txo_type: int, height: int) -> int:
        return sum(
            Prefixes.active_amount.unpack_value(v).amount
            for v in self.db.iterator(start=Prefixes.active_amount.pack_partial_key(
                claim_hash, txo_type, 0), stop=Prefixes.active_amount.pack_partial_key(
                claim_hash, txo_type, height), include_key=False)
        )

    def get_effective_amount(self, claim_hash: bytes, support_only=False) -> int:
        support_amount = self._get_active_amount(claim_hash, ACTIVATED_SUPPORT_TXO_TYPE, self.db_height + 1)
        if support_only:
            return support_only
        return support_amount + self._get_active_amount(claim_hash, ACTIVATED_CLAIM_TXO_TYPE, self.db_height + 1)

    def get_url_effective_amount(self, name: str, claim_hash: bytes):
        for _k, _v in self.db.iterator(prefix=Prefixes.effective_amount.pack_partial_key(name)):
            v = Prefixes.effective_amount.unpack_value(_v)
            if v.claim_hash == claim_hash:
                return Prefixes.effective_amount.unpack_key(_k)

    def get_claims_for_name(self, name):
        claims = []
        for _k, _v in self.db.iterator(prefix=Prefixes.claim_short_id.pack_partial_key(name)):
            k, v = Prefixes.claim_short_id.unpack_key(_k), Prefixes.claim_short_id.unpack_value(_v)
            # claims[v.claim_hash] = (k, v)
            if k.claim_hash not in claims:
                claims.append(k.claim_hash)
        return claims

    def get_claims_in_channel_count(self, channel_hash) -> int:
        count = 0
        for _ in self.db.iterator(prefix=Prefixes.channel_to_claim.pack_partial_key(channel_hash), include_key=False):
            count += 1
        return count

    def get_channel_for_claim(self, claim_hash, tx_num, position) -> Optional[bytes]:
        return self.db.get(Prefixes.claim_to_channel.pack_key(claim_hash, tx_num, position))

    def get_expired_by_height(self, height: int) -> Dict[bytes, Tuple[int, int, str, TxInput]]:
        expired = {}
        for _k, _v in self.db.iterator(prefix=Prefixes.claim_expiration.pack_partial_key(height)):
            k, v = Prefixes.claim_expiration.unpack_item(_k, _v)
            tx_hash = self.total_transactions[k.tx_num]
            tx = self.coin.transaction(self.db.get(DB_PREFIXES.TX_PREFIX.value + tx_hash))
            # treat it like a claim spend so it will delete/abandon properly
            # the _spend_claim function this result is fed to expects a txi, so make a mock one
            # print(f"\texpired lbry://{v.name} {v.claim_hash.hex()}")
            expired[v.claim_hash] = (
                k.tx_num, k.position, v.name,
                TxInput(prev_hash=tx_hash, prev_idx=k.position, script=tx.outputs[k.position].pk_script, sequence=0)
            )
        return expired

    def get_controlling_claim(self, name: str) -> Optional[ClaimTakeoverValue]:
        controlling = self.db.get(Prefixes.claim_takeover.pack_key(name))
        if not controlling:
            return
        return Prefixes.claim_takeover.unpack_value(controlling)

    def get_claim_txos_for_name(self, name: str):
        txos = {}
        for k, v in self.db.iterator(prefix=Prefixes.claim_short_id.pack_partial_key(name)):
            claim_hash = Prefixes.claim_short_id.unpack_key(k).claim_hash
            tx_num, nout = Prefixes.claim_short_id.unpack_value(v)
            txos[claim_hash] = tx_num, nout
        return txos

    def get_claim_metadata(self, tx_hash, nout):
        raw = self.db.get(
            DB_PREFIXES.TX_PREFIX.value + tx_hash
        )
        try:
            output = self.coin.transaction(raw).outputs[nout]
            script = OutputScript(output.pk_script)
            script.parse()
            return Claim.from_bytes(script.values['claim'])
        except:
            self.logger.error(
                "tx parsing for ES went boom %s %s", tx_hash[::-1].hex(),
                raw.hex()
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
        if not metadata.is_stream or not metadata.stream.has_fee:
            fee_amount = None
        else:
            fee_amount = int(max(metadata.stream.fee.amount or 0, 0) * 1000)
            if fee_amount >= 9223372036854775807:
                return
        reposted_claim_hash = None if not metadata.is_repost else metadata.repost.reference.claim_hash[::-1]
        reposted_claim = None
        reposted_metadata = None
        if reposted_claim_hash:
            reposted_claim = self.get_claim_txo(reposted_claim_hash)
            if not reposted_claim:
                return
            reposted_metadata = self.get_claim_metadata(
                self.total_transactions[reposted_claim.tx_num], reposted_claim.position
            )
            if not reposted_metadata:
                return
        reposted_tags = []
        reposted_languages = []
        reposted_has_source = None
        reposted_claim_type = None
        if reposted_claim:
            reposted_tx_hash = self.total_transactions[reposted_claim.tx_num]
            raw_reposted_claim_tx = self.db.get(
                DB_PREFIXES.TX_PREFIX.value + reposted_tx_hash
            )
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
            reposted_tags = [] if not reposted_metadata.is_stream else [tag for tag in reposted_metadata.stream.tags]
            reposted_languages = [] if not reposted_metadata.is_stream else (
                    [lang.language or 'none' for lang in reposted_metadata.stream.languages] or ['none']
            )
            reposted_has_source = False if not reposted_metadata.is_stream else reposted_metadata.stream.has_source
            reposted_claim_type = CLAIM_TYPES[reposted_metadata.claim_type]
        claim_tags = [] if not metadata.is_stream else [tag for tag in metadata.stream.tags]
        claim_languages = [] if not metadata.is_stream else (
                [lang.language or 'none' for lang in metadata.stream.languages] or ['none']
        )
        tags = list(set(claim_tags).union(set(reposted_tags)))
        languages = list(set(claim_languages).union(set(reposted_languages)))
        canonical_url = f'{claim.name}#{claim.claim_hash.hex()}'
        if metadata.is_signed:
            channel = self.get_claim_txo(metadata.signing_channel_hash[::-1])
            if channel:
                canonical_url = f'{channel.name}#{metadata.signing_channel_hash[::-1].hex()}/{canonical_url}'
        value = {
            'claim_hash': claim_hash[::-1],
            # 'claim_id': claim_hash.hex(),
            'claim_name': claim.name,
            'normalized': claim.name,
            'tx_id': claim.tx_hash[::-1].hex(),
            'tx_num': claim.tx_num,
            'tx_nout': claim.position,
            'amount': claim.amount,
            'timestamp': 0,  # TODO: fix
            'creation_timestamp': 0,  # TODO: fix
            'height': claim.height,
            'creation_height': claim.creation_height,
            'activation_height': claim.activation_height,
            'expiration_height': claim.expiration_height,
            'effective_amount': claim.effective_amount,
            'support_amount': claim.support_amount,
            'is_controlling': claim.is_controlling,
            'last_take_over_height': claim.last_takeover_height,

            'short_url': f'{claim.name}#{claim.claim_hash.hex()}',  # TODO: fix
            'canonical_url': canonical_url,

            'title': None if not metadata.is_stream else metadata.stream.title,
            'author': None if not metadata.is_stream else metadata.stream.author,
            'description': None if not metadata.is_stream else metadata.stream.description,
            'claim_type': CLAIM_TYPES[metadata.claim_type],
            'has_source': reposted_has_source if reposted_has_source is not None else (
                False if not metadata.is_stream else metadata.stream.has_source),
            'stream_type': None if not metadata.is_stream else STREAM_TYPES[
                guess_stream_type(metadata.stream.source.media_type)],
            'media_type': None if not metadata.is_stream else metadata.stream.source.media_type,
            'fee_amount': fee_amount,
            'fee_currency': None if not metadata.is_stream else metadata.stream.fee.currency,

            'reposted': self.get_reposted_count(claim_hash),
            'reposted_claim_hash': reposted_claim_hash,
            'reposted_claim_type': reposted_claim_type,
            'reposted_has_source': reposted_has_source,

            'channel_hash': metadata.signing_channel_hash,

            'public_key_bytes': None if not metadata.is_channel else metadata.channel.public_key_bytes,
            'public_key_hash': None if not metadata.is_channel else self.ledger.address_to_hash160(
                self.ledger.public_key_to_address(metadata.channel.public_key_bytes)
            ),
            'signature': metadata.signature,
            'signature_digest': None,  # TODO: fix
            'signature_valid': claim.signature_valid,
            'tags': tags,
            'languages': languages,
            'censor_type': 0,  # TODO: fix
            'censoring_channel_hash': None,  # TODO: fix
            'claims_in_channel': None if not metadata.is_channel else self.get_claims_in_channel_count(claim_hash)
            # 'trending_group': 0,
            # 'trending_mixed': 0,
            # 'trending_local': 0,
            # 'trending_global': 0,
        }
        if metadata.is_stream and (metadata.stream.video.duration or metadata.stream.audio.duration):
            value['duration'] = metadata.stream.video.duration or metadata.stream.audio.duration
        if metadata.is_stream and metadata.stream.release_time:
            value['release_time'] = metadata.stream.release_time
        return value

    def all_claims_producer(self, batch_size=500_000):
        batch = []
        for claim_hash, v in self.db.iterator(prefix=Prefixes.claim_to_txo.prefix):
            # TODO: fix the couple of claim txos that dont have controlling names
            if not self.db.get(Prefixes.claim_takeover.pack_key(Prefixes.claim_to_txo.unpack_value(v).name)):
                continue
            claim = self._fs_get_claim_by_hash(claim_hash[1:])
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

    def claims_producer(self, claim_hashes: Set[bytes]):
        batch = []
        for claim_hash in claim_hashes:
            claim = self._fs_get_claim_by_hash(claim_hash)
            if claim:
                batch.append(claim)
        batch.sort(key=lambda x: x.tx_hash)
        for claim in batch:
            meta = self._prepare_claim_metadata(claim.claim_hash, claim)
            if meta:
                yield meta

    def get_activated_at_height(self, height: int) -> DefaultDict[PendingActivationValue, List[PendingActivationKey]]:
        activated = defaultdict(list)
        for _k, _v in self.db.iterator(prefix=Prefixes.pending_activation.pack_partial_key(height)):
            k = Prefixes.pending_activation.unpack_key(_k)
            v = Prefixes.pending_activation.unpack_value(_v)
            activated[v].append(k)
        return activated

    def get_future_activated(self, height: int) -> DefaultDict[PendingActivationValue, List[PendingActivationKey]]:
        activated = defaultdict(list)
        start_prefix = Prefixes.pending_activation.pack_partial_key(height + 1)
        stop_prefix = Prefixes.pending_activation.pack_partial_key(height + 1 + self.coin.maxTakeoverDelay)
        for _k, _v in self.db.iterator(start=start_prefix, stop=stop_prefix):
            k = Prefixes.pending_activation.unpack_key(_k)
            v = Prefixes.pending_activation.unpack_value(_v)
            activated[v].append(k)
        return activated

    async def _read_tx_counts(self):
        if self.tx_counts is not None:
            return
        # tx_counts[N] has the cumulative number of txs at the end of
        # height N.  So tx_counts[0] is 1 - the genesis coinbase

        def get_counts():
            return tuple(
                util.unpack_be_uint64(tx_count)
                for tx_count in self.db.iterator(prefix=DB_PREFIXES.TX_COUNT_PREFIX.value, include_key=False)
            )

        tx_counts = await asyncio.get_event_loop().run_in_executor(self.executor, get_counts)
        assert len(tx_counts) == self.db_height + 1, f"{len(tx_counts)} vs {self.db_height + 1}"
        self.tx_counts = array.array('I', tx_counts)

        if self.tx_counts:
            assert self.db_tx_count == self.tx_counts[-1], \
                f"{self.db_tx_count} vs {self.tx_counts[-1]} ({len(self.tx_counts)} counts)"
        else:
            assert self.db_tx_count == 0

    async def _read_txids(self):
        def get_txids():
            return list(self.db.iterator(prefix=DB_PREFIXES.TX_HASH_PREFIX.value, include_key=False))

        start = time.perf_counter()
        self.logger.info("loading txids")
        txids = await asyncio.get_event_loop().run_in_executor(self.executor, get_txids)
        assert len(txids) == len(self.tx_counts) == 0 or len(txids) == self.tx_counts[-1]
        self.total_transactions = txids
        self.transaction_num_mapping = {
            txid: i for i, txid in enumerate(txids)
        }
        ts = time.perf_counter() - start
        self.logger.info("loaded %i txids in %ss", len(self.total_transactions), round(ts, 4))

    async def _read_headers(self):
        if self.headers is not None:
            return

        def get_headers():
            return [
                header for header in self.db.iterator(prefix=DB_PREFIXES.HEADER_PREFIX.value, include_key=False)
            ]

        headers = await asyncio.get_event_loop().run_in_executor(self.executor, get_headers)
        assert len(headers) - 1 == self.db_height, f"{len(headers)} vs {self.db_height}"
        self.headers = headers

    async def open_dbs(self):
        if self.db:
            return
        if self.executor is None:
            self.executor = ThreadPoolExecutor(1)

        assert self.db is None
        self.db = self.db_class(f'lbry-{self.env.db_engine}', True)
        if self.db.is_new:
            self.logger.info('created new db: %s', f'lbry-{self.env.db_engine}')
        else:
            self.logger.info(f'opened db: %s', f'lbry-{self.env.db_engine}')

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
        if self.db.for_sync:
            self.logger.info(f'flushing DB cache at {self.env.cache_MB:,d} MB')
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
        if self.total_transactions is None:
            await self._read_txids()
        await self._read_headers()

        # start search index
        await self.search_index.start()

    def close(self):
        self.db.close()
        self.executor.shutdown(wait=True)
        self.executor = None

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

    # Flushing
    def assert_flushed(self, flush_data):
        """Asserts state is fully flushed."""
        assert flush_data.tx_count == self.fs_tx_count == self.db_tx_count
        assert flush_data.height == self.fs_height == self.db_height
        assert flush_data.tip == self.db_tip
        assert not flush_data.block_txs
        assert not len(flush_data.put_and_delete_ops)

    def flush_dbs(self, flush_data: FlushData):
        if flush_data.height == self.db_height:
            self.assert_flushed(flush_data)
            return

        min_height = self.min_undo_height(self.db_height)
        delete_undo_keys = []
        if min_height > 0:
            delete_undo_keys.extend(
                self.db.iterator(
                    start=Prefixes.undo.pack_key(0), stop=Prefixes.undo.pack_key(min_height), include_value=False
                )
            )

        with self.db.write_batch() as batch:
            batch_put = batch.put
            batch_delete = batch.delete

            for staged_change in flush_data.put_and_delete_ops:
                if staged_change.is_put:
                    batch_put(staged_change.key, staged_change.value)
                else:
                    batch_delete(staged_change.key)
            for delete_key in delete_undo_keys:
                batch_delete(delete_key)

            self.fs_height = flush_data.height
            self.fs_tx_count = flush_data.tx_count
            self.hist_flush_count += 1
            self.hist_unflushed_count = 0
            self.utxo_flush_count = self.hist_flush_count
            self.db_height = flush_data.height
            self.db_tx_count = flush_data.tx_count
            self.db_tip = flush_data.tip
            self.last_flush_tx_count = self.fs_tx_count
            now = time.time()
            self.wall_time += now - self.last_flush
            self.last_flush = now
            self.write_db_state(batch)

    def flush_backup(self, flush_data):
        assert not flush_data.block_txs
        assert flush_data.height < self.db_height
        assert not self.hist_unflushed

        start_time = time.time()
        tx_delta = flush_data.tx_count - self.last_flush_tx_count
        ###
        self.fs_tx_count = flush_data.tx_count
        # Truncate header_mc: header count is 1 more than the height.
        self.header_mc.truncate(flush_data.height + 1)
        ###
        # Not certain this is needed, but it doesn't hurt
        self.hist_flush_count += 1
        nremoves = 0

        with self.db.write_batch() as batch:
            batch_put = batch.put
            batch_delete = batch.delete
            for op in flush_data.put_and_delete_ops:
                # print("REWIND", op)
                if op.is_put:
                    batch_put(op.key, op.value)
                else:
                    batch_delete(op.key)
            while self.fs_height > flush_data.height:
                self.fs_height -= 1

            start_time = time.time()
            if self.db.for_sync:
                block_count = flush_data.height - self.db_height
                tx_count = flush_data.tx_count - self.db_tx_count
                elapsed = time.time() - start_time
                self.logger.info(f'flushed {block_count:,d} blocks with '
                                 f'{tx_count:,d} txs in '
                                 f'{elapsed:.1f}s, committing...')

            self.utxo_flush_count = self.hist_flush_count
            self.db_height = flush_data.height
            self.db_tx_count = flush_data.tx_count
            self.db_tip = flush_data.tip

            # Flush state last as it reads the wall time.
            now = time.time()
            self.wall_time += now - self.last_flush
            self.last_flush = now
            self.last_flush_tx_count = self.fs_tx_count
            self.write_db_state(batch)

        self.logger.info(f'backing up removed {nremoves:,d} history entries')
        elapsed = self.last_flush - start_time
        self.logger.info(f'backup flush #{self.hist_flush_count:,d} took {elapsed:.1f}s. '
                         f'Height {flush_data.height:,d} txs: {flush_data.tx_count:,d} ({tx_delta:+,d})')

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
            return self.total_transactions[tx_num], tx_height
        except IndexError:
            self.logger.exception(
                "Failed to access a cached transaction, known bug #3142 "
                "should be fixed in #3205"
            )
            return None, tx_height

    def _fs_transactions(self, txids: Iterable[str]):
        tx_counts = self.tx_counts
        tx_db_get = self.db.get
        tx_cache = self._tx_and_merkle_cache
        tx_infos = {}

        for tx_hash in txids:
            cached_tx = tx_cache.get(tx_hash)
            if cached_tx:
                tx, merkle = cached_tx
            else:
                tx_hash_bytes = bytes.fromhex(tx_hash)[::-1]
                tx_num = self.transaction_num_mapping.get(tx_hash_bytes)
                tx = None
                tx_height = -1
                if tx_num is not None:
                    tx_height = bisect_right(tx_counts, tx_num)
                    tx = tx_db_get(Prefixes.tx.pack_key(tx_hash_bytes))
                if tx_height == -1:
                    merkle = {
                        'block_height': -1
                    }
                else:
                    tx_pos = tx_num - tx_counts[tx_height - 1]
                    branch, root = self.merkle.branch_and_root(
                        self.total_transactions[tx_counts[tx_height - 1]:tx_counts[tx_height]], tx_pos
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
        return await asyncio.get_event_loop().run_in_executor(self.executor, self._fs_transactions, txids)

    async def fs_block_hashes(self, height, count):
        if height + count > len(self.headers):
            raise DBError(f'only got {len(self.headers) - height:,d} headers starting at {height:,d}, not {count:,d}')
        return [self.coin.header_hash(header) for header in self.headers[height:height + count]]

    def read_history(self, hashX: bytes, limit: int = 1000) -> List[int]:
        txs = array.array('I')
        for hist in self.db.iterator(prefix=Prefixes.hashX_history.pack_partial_key(hashX), include_key=False):
            a = array.array('I')
            a.frombytes(hist)
            txs.extend(a)
            if len(txs) >= limit:
                break
        return txs.tolist()

    async def limited_history(self, hashX, *, limit=1000):
        """Return an unpruned, sorted list of (tx_hash, height) tuples of
        confirmed transactions that touched the address, earliest in
        the blockchain first.  Includes both spending and receiving
        transactions.  By default returns at most 1000 entries.  Set
        limit to None to get them all.
        """
        while True:
            history = await asyncio.get_event_loop().run_in_executor(self.executor, self.read_history, hashX, limit)
            if history is not None:
                return [(self.total_transactions[tx_num], bisect_right(self.tx_counts, tx_num)) for tx_num in history]
            self.logger.warning(f'limited_history: tx hash '
                                f'not found (reorg?), retrying...')
            await sleep(0.25)

    # -- Undo information

    def min_undo_height(self, max_height):
        """Returns a height from which we should store undo info."""
        return max_height - self.env.reorg_limit + 1

    def undo_key(self, height: int) -> bytes:
        """DB key for undo information at the given height."""
        return Prefixes.undo.pack_key(height)

    def read_undo_info(self, height: int):
        return self.db.get(Prefixes.undo.pack_key(height))

    # -- UTXO database

    def write_db_state(self, batch):
        """Write (UTXO) state to the batch."""
        batch.put(
            DB_PREFIXES.db_state.value,
            DBState(
                self.genesis_bytes, self.db_height, self.db_tx_count, self.db_tip,
                self.utxo_flush_count, int(self.wall_time), self.first_sync, self.db_version,
                self.hist_flush_count, self.hist_comp_flush_count, self.hist_comp_cursor
            ).pack()
        )

    def read_db_state(self):
        state = self.db.get(DB_PREFIXES.db_state.value)
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
            state = DBState.unpack(state)
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

    async def all_utxos(self, hashX):
        """Return all UTXOs for an address sorted in no particular order."""
        def read_utxos():
            utxos = []
            utxos_append = utxos.append
            fs_tx_hash = self.fs_tx_hash
            for db_key, db_value in self.db.iterator(prefix=Prefixes.utxo.pack_partial_key(hashX)):
                k = Prefixes.utxo.unpack_key(db_key)
                v = Prefixes.utxo.unpack_value(db_value)
                tx_hash, height = fs_tx_hash(k.tx_num)
                utxos_append(UTXO(k.tx_num, k.nout, tx_hash, height, v.amount))
            return utxos

        while True:
            utxos = await asyncio.get_event_loop().run_in_executor(self.executor, read_utxos)
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
                tx_num = self.transaction_num_mapping[tx_hash]
                hashX = self.db.get(Prefixes.hashX_utxo.pack_key(tx_hash[:4], tx_num, nout))
                utxo_value = self.db.get(Prefixes.utxo.pack_key(hashX, tx_num, nout))
                if utxo_value:
                    utxo_append((hashX, Prefixes.utxo.unpack_value(utxo_value).amount))
            return utxos
        return await asyncio.get_event_loop().run_in_executor(self.executor, lookup_utxos)
