import struct
import logging
from decimal import Decimal
from binascii import unhexlify
from typing import Tuple, List, Optional

from sqlalchemy import func, case
from sqlalchemy.future import select, Select

from lbry.schema.tags import clean_tags
from lbry.schema.result import Censor, Outputs as ResultOutput
from lbry.schema.url import normalize_name
from lbry.blockchain.transaction import Output

from ..utils import query
from ..query_context import context
from ..tables import TX, TXO, Claim, Support
from ..constants import (
    TXO_TYPES, STREAM_TYPES, ATTRIBUTE_ARRAY_MAX_LENGTH,
    SEARCH_INTEGER_PARAMS, SEARCH_ORDER_FIELDS
)

from .txio import BASE_SELECT_TXO_COLUMNS, rows_to_txos


log = logging.getLogger(__name__)


BASE_SELECT_SUPPORT_COLUMNS = BASE_SELECT_TXO_COLUMNS + [
    Support.c.channel_hash,
    Support.c.is_signature_valid,
]


def compat_layer(**constraints):
    # for old sdk, to be removed later
    replacements = {"effective_amount": "staked_amount"}
    for old_key, new_key in replacements.items():
        if old_key in constraints:
            constraints[new_key] = constraints.pop(old_key)
    return constraints


def select_supports(cols: List = None, **constraints) -> Select:
    if cols is None:
        cols = BASE_SELECT_SUPPORT_COLUMNS
    joins = Support.join(TXO, ).join(TX)
    return query([Support], select(*cols).select_from(joins), **constraints)


def search_supports(**constraints) -> Tuple[List[Output], Optional[int]]:
    total = None
    if constraints.pop('include_total', False):
        total = search_support_count(**constraints)
    if 'claim_id' in constraints:
        constraints['claim_hash'] = unhexlify(constraints.pop('claim_id'))[::-1]
    rows = context().fetchall(select_supports(**constraints))
    txos = rows_to_txos(rows, include_tx=False)
    return txos, total


def search_support_count(**constraints) -> int:
    constraints.pop('offset', None)
    constraints.pop('limit', None)
    constraints.pop('order_by', None)
    count = context().fetchall(select_supports([func.count().label('total')], **constraints))
    return count[0]['total'] or 0


channel_claim = Claim.alias('channel')
BASE_SELECT_CLAIM_COLUMNS = BASE_SELECT_TXO_COLUMNS + [
    Claim.c.activation_height,
    Claim.c.takeover_height,
    Claim.c.creation_height,
    Claim.c.is_controlling,
    Claim.c.channel_hash,
    Claim.c.reposted_count,
    Claim.c.reposted_claim_hash,
    Claim.c.short_url,
    Claim.c.signed_claim_count,
    Claim.c.signed_support_count,
    (Claim.c.amount + Claim.c.staked_support_amount).label('staked_amount'),
    Claim.c.staked_support_amount,
    Claim.c.staked_support_count,
    Claim.c.is_signature_valid,
    case([(
        channel_claim.c.short_url.isnot(None),
        channel_claim.c.short_url + '/' + Claim.c.short_url
    )]).label('canonical_url'),
]


def select_claims(cols: List = None, for_count=False, **constraints) -> Select:
    constraints = compat_layer(**constraints)
    if cols is None:
        cols = BASE_SELECT_CLAIM_COLUMNS
    if 'order_by' in constraints:
        order_by_parts = constraints['order_by']
        if isinstance(order_by_parts, str):
            order_by_parts = [order_by_parts]
        sql_order_by = []
        for order_by in order_by_parts:
            is_asc = order_by.startswith('^')
            column = order_by[1:] if is_asc else order_by
            if column not in SEARCH_ORDER_FIELDS:
                raise NameError(f'{column} is not a valid order_by field')
            if column == 'name':
                column = 'claim_name'
            nulls_last = ''
            if column == 'release_time':
                nulls_last = ' NULLs LAST'
            sql_order_by.append(
                f"claim.{column} ASC{nulls_last}" if is_asc else f"claim.{column} DESC{nulls_last}"
            )
        constraints['order_by'] = sql_order_by

    ops = {'<=': '__lte', '>=': '__gte', '<': '__lt', '>': '__gt'}
    for constraint in SEARCH_INTEGER_PARAMS:
        if constraint in constraints:
            value = constraints.pop(constraint)
            postfix = ''
            if isinstance(value, str):
                if len(value) >= 2 and value[:2] in ops:
                    postfix, value = ops[value[:2]], value[2:]
                elif len(value) >= 1 and value[0] in ops:
                    postfix, value = ops[value[0]], value[1:]
            if constraint == 'fee_amount':
                value = Decimal(value)*1000
            constraints[f'{constraint}{postfix}'] = int(value)

    if 'sequence' in constraints:
        constraints['order_by'] = 'activation_height ASC'
        constraints['offset'] = int(constraints.pop('sequence')) - 1
        constraints['limit'] = 1
    if 'amount_order' in constraints:
        constraints['order_by'] = 'effective_amount DESC'
        constraints['offset'] = int(constraints.pop('amount_order')) - 1
        constraints['limit'] = 1

    if 'claim_id' in constraints:
        claim_id = constraints.pop('claim_id')
        if len(claim_id) == 40:
            constraints['claim_id'] = claim_id
        else:
            constraints['claim_id__like'] = f'{claim_id[:40]}%'
    elif 'claim_ids' in constraints:
        constraints['claim_id__in'] = set(constraints.pop('claim_ids'))

    if 'reposted_claim_id' in constraints:
        constraints['reposted_claim_hash'] = unhexlify(constraints.pop('reposted_claim_id'))[::-1]

    if 'name' in constraints:
        constraints['normalized'] = normalize_name(constraints.pop('name'))

    if 'public_key_id' in constraints:
        constraints['public_key_hash'] = (
            context().ledger.address_to_hash160(constraints.pop('public_key_id')))
    if 'channel_hash' in constraints:
        constraints['channel_hash'] = constraints.pop('channel_hash')
    if 'channel_ids' in constraints:
        channel_ids = constraints.pop('channel_ids')
        if channel_ids:
            constraints['channel_hash__in'] = {
                unhexlify(cid)[::-1] for cid in channel_ids
            }
    if 'not_channel_ids' in constraints:
        not_channel_ids = constraints.pop('not_channel_ids')
        if not_channel_ids:
            not_channel_ids_binary = {
                unhexlify(ncid)[::-1] for ncid in not_channel_ids
            }
            constraints['claim_hash__not_in#not_channel_ids'] = not_channel_ids_binary
            if constraints.get('has_channel_signature', False):
                constraints['channel_hash__not_in'] = not_channel_ids_binary
            else:
                constraints['null_or_not_channel__or'] = {
                    'signature_valid__is_null': True,
                    'channel_hash__not_in': not_channel_ids_binary
                }
    if 'signature_valid' in constraints:
        has_channel_signature = constraints.pop('has_channel_signature', False)
        if has_channel_signature:
            constraints['signature_valid'] = constraints.pop('signature_valid')
        else:
            constraints['null_or_signature__or'] = {
                'signature_valid__is_null': True,
                'signature_valid': constraints.pop('signature_valid')
            }
    elif constraints.pop('has_channel_signature', False):
        constraints['signature_valid__is_not_null'] = True

    if 'txid' in constraints:
        tx_hash = unhexlify(constraints.pop('txid'))[::-1]
        nout = constraints.pop('nout', 0)
        constraints['txo_hash'] = tx_hash + struct.pack('<I', nout)

    if 'claim_type' in constraints:
        claim_types = constraints.pop('claim_type')
        if isinstance(claim_types, str):
            claim_types = [claim_types]
        if claim_types:
            constraints['claim_type__in'] = {
                TXO_TYPES[claim_type] for claim_type in claim_types
            }
    if 'stream_types' in constraints:
        stream_types = constraints.pop('stream_types')
        if stream_types:
            constraints['stream_type__in'] = {
                STREAM_TYPES[stream_type] for stream_type in stream_types
            }
    if 'media_types' in constraints:
        media_types = constraints.pop('media_types')
        if media_types:
            constraints['media_type__in'] = set(media_types)

    if 'fee_currency' in constraints:
        constraints['fee_currency'] = constraints.pop('fee_currency').lower()

    _apply_constraints_for_array_attributes(constraints, 'tag', clean_tags, for_count)
    _apply_constraints_for_array_attributes(constraints, 'language', lambda _: _, for_count)
    _apply_constraints_for_array_attributes(constraints, 'location', lambda _: _, for_count)

    if 'text' in constraints:
        # TODO: fix
        constraints["search"] = constraints.pop("text")

    return query(
        [Claim],
        select(*cols)
        .select_from(
            Claim.join(TXO).join(TX)
            .join(channel_claim, Claim.c.channel_hash == channel_claim.c.claim_hash, isouter=True)
        ), **constraints
    )


def protobuf_search_claims(**constraints) -> str:
    txos, _, censor = search_claims(**constraints)
    return ResultOutput.to_base64(txos, [], blocked=censor)


def search_claims(**constraints) -> Tuple[List[Output], Optional[int], Optional[Censor]]:
    total = None
    if constraints.pop('include_total', False):
        total = search_claim_count(**constraints)
    constraints['offset'] = abs(constraints.get('offset', 0))
    constraints['limit'] = min(abs(constraints.get('limit', 10)), 50)
    ctx = context()
    search_censor = ctx.get_search_censor()
    rows = context().fetchall(select_claims(**constraints))
    txos = rows_to_txos(rows, include_tx=False)
    return txos, total, search_censor


def search_claim_count(**constraints) -> int:
    constraints.pop('offset', None)
    constraints.pop('limit', None)
    constraints.pop('order_by', None)
    count = context().fetchall(select_claims([func.count().label('total')], **constraints))
    return count[0]['total'] or 0


CLAIM_HASH_OR_REPOST_HASH_SQL = f"""
CASE WHEN claim.claim_type = {TXO_TYPES['repost']}
    THEN claim.reposted_claim_hash
    ELSE claim.claim_hash
END
"""


def _apply_constraints_for_array_attributes(constraints, attr, cleaner, for_count=False):
    any_items = set(cleaner(constraints.pop(f'any_{attr}s', []))[:ATTRIBUTE_ARRAY_MAX_LENGTH])
    all_items = set(cleaner(constraints.pop(f'all_{attr}s', []))[:ATTRIBUTE_ARRAY_MAX_LENGTH])
    not_items = set(cleaner(constraints.pop(f'not_{attr}s', []))[:ATTRIBUTE_ARRAY_MAX_LENGTH])

    all_items = {item for item in all_items if item not in not_items}
    any_items = {item for item in any_items if item not in not_items}

    any_queries = {}

    #    if attr == 'tag':
    #        common_tags = any_items & COMMON_TAGS.keys()
    #        if common_tags:
    #            any_items -= common_tags
    #        if len(common_tags) < 5:
    #            for item in common_tags:
    #                index_name = COMMON_TAGS[item]
    #                any_queries[f'#_common_tag_{index_name}'] = f"""
    #                EXISTS(
    #                    SELECT 1 FROM tag INDEXED BY tag_{index_name}_idx
    #                    WHERE {CLAIM_HASH_OR_REPOST_HASH_SQL}=tag.claim_hash
    #                    AND tag = '{item}'
    #                )
    #                """
    #        elif len(common_tags) >= 5:
    #            constraints.update({
    #                f'$any_common_tag{i}': item for i, item in enumerate(common_tags)
    #            })
    #            values = ', '.join(
    #                f':$any_common_tag{i}' for i in range(len(common_tags))
    #            )
    #            any_queries[f'#_any_common_tags'] = f"""
    #            EXISTS(
    #                SELECT 1 FROM tag WHERE {CLAIM_HASH_OR_REPOST_HASH_SQL}=tag.claim_hash
    #                AND tag IN ({values})
    #            )
    #            """

    if any_items:

        constraints.update({
            f'$any_{attr}{i}': item for i, item in enumerate(any_items)
        })
        values = ', '.join(
            f':$any_{attr}{i}' for i in range(len(any_items))
        )
        if for_count or attr == 'tag':
            any_queries[f'#_any_{attr}'] = f"""
            {CLAIM_HASH_OR_REPOST_HASH_SQL} IN (
                SELECT claim_hash FROM {attr} WHERE {attr} IN ({values})
            )
            """
        else:
            any_queries[f'#_any_{attr}'] = f"""
            EXISTS(
                SELECT 1 FROM {attr} WHERE
                    {CLAIM_HASH_OR_REPOST_HASH_SQL}={attr}.claim_hash
                AND {attr} IN ({values})
            )
            """

    if len(any_queries) == 1:
        constraints.update(any_queries)
    elif len(any_queries) > 1:
        constraints[f'ORed_{attr}_queries__any'] = any_queries

    if all_items:
        constraints[f'$all_{attr}_count'] = len(all_items)
        constraints.update({
            f'$all_{attr}{i}': item for i, item in enumerate(all_items)
        })
        values = ', '.join(
            f':$all_{attr}{i}' for i in range(len(all_items))
        )
        if for_count:
            constraints[f'#_all_{attr}'] = f"""
            {CLAIM_HASH_OR_REPOST_HASH_SQL} IN (
                SELECT claim_hash FROM {attr} WHERE {attr} IN ({values})
                GROUP BY claim_hash HAVING COUNT({attr}) = :$all_{attr}_count
            )
            """
        else:
            constraints[f'#_all_{attr}'] = f"""
                {len(all_items)}=(
                    SELECT count(*) FROM {attr} WHERE
                        {CLAIM_HASH_OR_REPOST_HASH_SQL}={attr}.claim_hash
                    AND {attr} IN ({values})
                )
            """

    if not_items:
        constraints.update({
            f'$not_{attr}{i}': item for i, item in enumerate(not_items)
        })
        values = ', '.join(
            f':$not_{attr}{i}' for i in range(len(not_items))
        )
        if for_count:
            constraints[f'#_not_{attr}'] = f"""
            {CLAIM_HASH_OR_REPOST_HASH_SQL} NOT IN (
                SELECT claim_hash FROM {attr} WHERE {attr} IN ({values})
            )
            """
        else:
            constraints[f'#_not_{attr}'] = f"""
                NOT EXISTS(
                    SELECT 1 FROM {attr} WHERE
                        {CLAIM_HASH_OR_REPOST_HASH_SQL}={attr}.claim_hash
                    AND {attr} IN ({values})
                )
            """
