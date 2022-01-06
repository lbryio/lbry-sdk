from decimal import Decimal
from typing import Iterable

from lbry.error import TooManyClaimSearchParametersError
from lbry.schema.tags import clean_tags
from lbry.schema.url import normalize_name
from lbry.wallet.server.db.common import CLAIM_TYPES, STREAM_TYPES
from lbry.wallet.server.db.elasticsearch.constants import REPLACEMENTS, FIELDS, TEXT_FIELDS, RANGE_FIELDS


def expand_query(**kwargs):
    if "amount_order" in kwargs:
        kwargs["limit"] = 1
        kwargs["order_by"] = "effective_amount"
        kwargs["offset"] = int(kwargs["amount_order"]) - 1
    if 'name' in kwargs:
        kwargs['name'] = normalize_name(kwargs.pop('name'))
    if kwargs.get('is_controlling') is False:
        kwargs.pop('is_controlling')
    query = {'must': [], 'must_not': []}
    collapse = None
    if 'fee_currency' in kwargs and kwargs['fee_currency'] is not None:
        kwargs['fee_currency'] = kwargs['fee_currency'].upper()
    for key, value in kwargs.items():
        key = key.replace('claim.', '')
        many = key.endswith('__in') or isinstance(value, list)
        if many and len(value) > 2048:
            raise TooManyClaimSearchParametersError(key, 2048)
        if many:
            key = key.replace('__in', '')
            value = list(filter(None, value))
        if value is None or isinstance(value, list) and len(value) == 0:
            continue
        key = REPLACEMENTS.get(key, key)
        if key in FIELDS:
            partial_id = False
            if key == 'claim_type':
                if isinstance(value, str):
                    value = CLAIM_TYPES[value]
                else:
                    value = [CLAIM_TYPES[claim_type] for claim_type in value]
            elif key == 'stream_type':
                value = [STREAM_TYPES[value]] if isinstance(value, str) else list(map(STREAM_TYPES.get, value))
            if key == '_id':
                if isinstance(value, Iterable):
                    value = [item[::-1].hex() for item in value]
                else:
                    value = value[::-1].hex()
            if not many and key in ('_id', 'claim_id') and len(value) < 20:
                partial_id = True
            if key in ('signature_valid', 'has_source'):
                continue  # handled later
            if key in TEXT_FIELDS:
                key += '.keyword'
            ops = {'<=': 'lte', '>=': 'gte', '<': 'lt', '>': 'gt'}
            if partial_id:
                query['must'].append({"prefix": {"claim_id": value}})
            elif key in RANGE_FIELDS and isinstance(value, str) and value[0] in ops:
                operator_length = 2 if value[:2] in ops else 1
                operator, value = value[:operator_length], value[operator_length:]
                if key == 'fee_amount':
                    value = str(Decimal(value)*1000)
                query['must'].append({"range": {key: {ops[operator]: value}}})
            elif many:
                query['must'].append({"terms": {key: value}})
            else:
                if key == 'fee_amount':
                    value = str(Decimal(value)*1000)
                query['must'].append({"term": {key: {"value": value}}})
        elif key == 'not_channel_ids':
            for channel_id in value:
                query['must_not'].append({"term": {'channel_id.keyword': channel_id}})
                query['must_not'].append({"term": {'_id': channel_id}})
        elif key == 'channel_ids':
            query['must'].append({"terms": {'channel_id.keyword': value}})
        elif key == 'claim_ids':
            query['must'].append({"terms": {'claim_id.keyword': value}})
        elif key == 'media_types':
            query['must'].append({"terms": {'media_type.keyword': value}})
        elif key == 'any_languages':
            query['must'].append({"terms": {'languages': clean_tags(value)}})
        elif key == 'any_languages':
            query['must'].append({"terms": {'languages': value}})
        elif key == 'all_languages':
            query['must'].extend([{"term": {'languages': tag}} for tag in value])
        elif key == 'any_tags':
            query['must'].append({"terms": {'tags.keyword': clean_tags(value)}})
        elif key == 'all_tags':
            query['must'].extend([{"term": {'tags.keyword': tag}} for tag in clean_tags(value)])
        elif key == 'not_tags':
            query['must_not'].extend([{"term": {'tags.keyword': tag}} for tag in clean_tags(value)])
        elif key == 'not_claim_id':
            query['must_not'].extend([{"term": {'claim_id.keyword': cid}} for cid in value])
        elif key == 'limit_claims_per_channel':
            collapse = ('channel_id.keyword', value)
    if kwargs.get('has_channel_signature'):
        query['must'].append({"exists": {"field": "signature"}})
        if 'signature_valid' in kwargs:
            query['must'].append({"term": {"is_signature_valid": bool(kwargs["signature_valid"])}})
    elif 'signature_valid' in kwargs:
        query.setdefault('should', [])
        query["minimum_should_match"] = 1
        query['should'].append({"bool": {"must_not": {"exists": {"field": "signature"}}}})
        query['should'].append({"term": {"is_signature_valid": bool(kwargs["signature_valid"])}})
    if 'has_source' in kwargs:
        query.setdefault('should', [])
        query["minimum_should_match"] = 1
        is_stream_or_repost = {"terms": {"claim_type": [CLAIM_TYPES['stream'], CLAIM_TYPES['repost']]}}
        query['should'].append(
            {"bool": {"must": [{"match": {"has_source": kwargs['has_source']}}, is_stream_or_repost]}})
        query['should'].append({"bool": {"must_not": [is_stream_or_repost]}})
        query['should'].append({"bool": {"must": [{"term": {"reposted_claim_type": CLAIM_TYPES['channel']}}]}})
    if kwargs.get('text'):
        query['must'].append(
                    {"simple_query_string":
                         {"query": kwargs["text"], "fields": [
                             "claim_name^4", "channel_name^8", "title^1", "description^.5", "author^1", "tags^.5"
                         ]}})
    query = {
        "_source": {"excludes": ["description", "title"]},
        'query': {'bool': query},
        "sort": [],
    }
    if "limit" in kwargs:
        query["size"] = kwargs["limit"]
    if 'offset' in kwargs:
        query["from"] = kwargs["offset"]
    if 'order_by' in kwargs:
        if isinstance(kwargs["order_by"], str):
            kwargs["order_by"] = [kwargs["order_by"]]
        for value in kwargs['order_by']:
            if 'trending_group' in value:
                # fixme: trending_mixed is 0 for all records on variable decay, making sort slow.
                continue
            is_asc = value.startswith('^')
            value = value[1:] if is_asc else value
            value = REPLACEMENTS.get(value, value)
            if value in TEXT_FIELDS:
                value += '.keyword'
            query['sort'].append({value: "asc" if is_asc else "desc"})
    if collapse:
        query["collapse"] = {
            "field": collapse[0],
            "inner_hits": {
                "name": collapse[0],
                "size": collapse[1],
                "sort": query["sort"]
            }
        }
    return query
