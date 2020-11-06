import logging
import itertools
from typing import List, Dict

from lbry.schema.url import URL
from lbry.schema.result import Outputs as ResultOutput
from lbry.error import ResolveCensoredError
from lbry.blockchain.transaction import Output
from . import rows_to_txos

from ..query_context import context
from .search import select_claims


log = logging.getLogger(__name__)


def resolve_claims(**constraints):
    censor = context().get_resolve_censor()
    rows = context().fetchall(select_claims(**constraints))
    rows = censor.apply(rows, level=2)
    return rows_to_txos(rows), censor


def _get_referenced_rows(txo_rows: List[Output], censor_channels: List[bytes]):
    repost_hashes = set(txo.reposted_claim.claim_hash for txo in txo_rows if txo.reposted_claim)
    channel_hashes = set(itertools.chain(
        (txo.channel.claim_hash for txo in txo_rows if txo.channel),
        censor_channels
    ))

    reposted_txos = []
    if repost_hashes:
        reposted_txos = resolve_claims(**{'claim.claim_hash__in': repost_hashes})
        if reposted_txos:
            reposted_txos = reposted_txos[0]
            channel_hashes |= set(txo.channel.claim_hash for txo in reposted_txos if txo.channel)

    channel_txos = []
    if channel_hashes:
        channel_txos = resolve_claims(**{'claim.claim_hash__in': channel_hashes})
        channel_txos = channel_txos[0] if channel_txos else []

    # channels must come first for client side inflation to work properly
    return channel_txos + reposted_txos


def protobuf_resolve(urls, **kwargs) -> str:
    txo_rows = [resolve_url(raw_url) for raw_url in urls]
    extra_txo_rows = _get_referenced_rows(
        [txo_row for txo_row in txo_rows if isinstance(txo_row, Output)],
        [txo.censor_hash for txo in txo_rows if isinstance(txo, ResolveCensoredError)]
    )
    return ResultOutput.to_base64(txo_rows, extra_txo_rows)


def resolve(urls, **kwargs) -> Dict[str, Output]:
    return {url: resolve_url(url) for url in urls}


def resolve_url(raw_url):
    try:
        url = URL.parse(raw_url)
    except ValueError as e:
        return e

    channel = None

    if url.has_channel:
        q = url.channel.to_dict()
        if set(q) == {'name'}:
            q['is_controlling'] = True
        else:
            q['order_by'] = ['^creation_height']
        matches, censor = resolve_claims(**q, limit=1)
        if matches:
            channel = matches[0]
        elif censor.censored:
            return ResolveCensoredError(raw_url, next(iter(censor.censored)))
        elif not channel:
            return LookupError(f'Could not find channel in "{raw_url}".')

    if url.has_stream:
        q = url.stream.to_dict()
        if channel is not None:
            q['order_by'] = ['^creation_height']
            q['channel_hash'] = channel.claim_hash
            q['is_signature_valid'] = True
        elif set(q) == {'name'}:
            q['is_controlling'] = True
        matches, censor = resolve_claims(**q, limit=1)
        if matches:
            stream = matches[0]
            stream.channel = channel
            return stream
        elif censor.censored:
            return ResolveCensoredError(raw_url, next(iter(censor.censored)))
        else:
            return LookupError(f'Could not find claim at "{raw_url}".')

    return channel
