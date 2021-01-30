import asyncio
import struct
from binascii import hexlify, unhexlify
from decimal import Decimal
from operator import itemgetter
from typing import Optional, List, Iterable

from elasticsearch import AsyncElasticsearch, NotFoundError
from elasticsearch.helpers import async_bulk

from lbry.crypto.base58 import Base58
from lbry.error import ResolveCensoredError
from lbry.schema.result import Outputs, Censor
from lbry.schema.tags import clean_tags
from lbry.schema.url import URL, normalize_name
from lbry.wallet.server.db.common import CLAIM_TYPES, STREAM_TYPES


class SearchIndex:
    def __init__(self, index_prefix: str):
        self.client: Optional[AsyncElasticsearch] = None
        self.index = index_prefix + 'claims'

    async def start(self):
        self.client = AsyncElasticsearch()
        try:
            if await self.client.indices.exists(self.index):
                return
            await self.client.indices.create(
                self.index,
                {
                    "settings":
                        {"analysis":
                            {"analyzer": {
                                "default": {"tokenizer": "whitespace", "filter": ["lowercase", "porter_stem"]}}},
                            "index":
                                {"refresh_interval": -1,
                                 "number_of_shards": 1}
                        },
                    "mappings": {
                        "properties": {
                            "claim_id": {
                                "type": "text",
                                "index_prefixes": {
                                    "min_chars": 1,
                                    "max_chars": 10
                                }
                            },
                            "height": {"type": "integer"},
                            "claim_type": {"type": "byte"},
                        }
                    }
                }
            )
        except Exception as e:
            raise

    def stop(self):
        client = self.client
        self.client = None
        return asyncio.ensure_future(client.close())

    def delete_index(self):
        return self.client.indices.delete(self.index)

    async def sync_queue(self, claim_queue):
        if claim_queue.empty():
            return
        to_delete, to_update = [], []
        while not claim_queue.empty():
            operation, doc = claim_queue.get_nowait()
            if operation == 'delete':
                to_delete.append(doc)
            else:
                to_update.append(doc)
        await self.delete(to_delete)
        await self.client.indices.refresh(self.index)
        await self.update(to_update)
        await self.client.indices.refresh(self.index)

    async def apply_filters(self, blocked_streams, blocked_channels, filtered_streams, filtered_channels):
        def make_query(censor_type, blockdict, channels=False):
            blockdict = dict(
                (hexlify(key[::-1]).decode(), hexlify(value[::-1]).decode()) for key, value in blockdict.items())
            if channels:
                update = expand_query(channel_id__in=list(blockdict.keys()), censor_type=f"<{censor_type}")
            else:
                update = expand_query(claim_id__in=list(blockdict.keys()), censor_type=f"<{censor_type}")
            key = 'channel_id' if channels else 'claim_id'
            update['script'] = {
                "source": f"ctx._source.censor_type={censor_type}; ctx._source.censoring_channel_hash=params[ctx._source.{key}]",
                "lang": "painless",
                "params": blockdict
            }
            return update
        sync_timeout = 600  # wont hit that 99% of the time, but can hit on a fresh import
        if filtered_streams:
            await self.client.update_by_query(self.index, body=make_query(1, filtered_streams), request_timeout=sync_timeout, slices=32)
            await self.client.indices.refresh(self.index, request_timeout=sync_timeout)
        if filtered_channels:
            await self.client.update_by_query(self.index, body=make_query(1, filtered_channels, True), request_timeout=sync_timeout, slices=32)
            await self.client.indices.refresh(self.index, request_timeout=sync_timeout)
        if blocked_streams:
            await self.client.update_by_query(self.index, body=make_query(2, blocked_streams), request_timeout=sync_timeout, slices=32)
            await self.client.indices.refresh(self.index, request_timeout=sync_timeout)
        if blocked_channels:
            await self.client.update_by_query(self.index, body=make_query(2, blocked_channels, True), request_timeout=sync_timeout, slices=32)
            await self.client.indices.refresh(self.index, request_timeout=sync_timeout)

    async def update(self, claims):
        if not claims:
            return
        actions = [extract_doc(claim, self.index) for claim in claims]
        names = []
        for claim in claims:
            if claim['is_controlling']:
                names.append(claim['normalized'])
        if names:
            update = expand_query(name__in=names)
            update['script'] = {
                "source": "ctx._source.is_controlling=false",
                "lang": "painless"
            }
            await self.client.update_by_query(self.index, body=update)
        await self.client.indices.refresh(self.index)
        await async_bulk(self.client, actions)

    async def delete(self, claim_ids):
        if not claim_ids:
            return
        actions = [{'_index': self.index, '_op_type': 'delete', '_id': claim_id} for claim_id in claim_ids]
        await async_bulk(self.client, actions, raise_on_error=False)
        update = expand_query(channel_id__in=claim_ids)
        update['script'] = {
            "source": "ctx._source.signature_valid=false",
            "lang": "painless"
        }
        await self.client.update_by_query(self.index, body=update)

    async def session_query(self, query_name, function, kwargs):
        offset, total = kwargs.get('offset', 0) if isinstance(kwargs, dict) else 0, 0
        total_referenced = []
        if query_name == 'resolve':
            total_referenced, response, censor = await self.resolve(*kwargs)
        else:
            censor = Censor(Censor.SEARCH)
            response, offset, total = await self.search(**kwargs, censor_type=0)
            total_referenced.extend(response)
            censored_response, _, _ = await self.search(**kwargs, censor_type='>0')
            censor.apply(censored_response)
            total_referenced.extend(censored_response)
        return Outputs.to_base64(response, await self._get_referenced_rows(total_referenced), offset, total, censor)

    async def resolve(self, *urls):
        censor = Censor(Censor.RESOLVE)
        results = await asyncio.gather(*(self.resolve_url(url) for url in urls))
        censored = [
            result if not isinstance(result, dict) or not censor.censor(result)
            else ResolveCensoredError(url, result['censoring_channel_hash'])
            for url, result in zip(urls, results)
        ]
        return results, censored, censor

    async def search(self, **kwargs):
        if 'channel' in kwargs:
            result = await self.resolve_url(kwargs.pop('channel'))
            if not result or not isinstance(result, Iterable):
                return [], 0, 0
            kwargs['channel_id'] = result['_id']
        try:
            result = await self.client.search(expand_query(**kwargs), index=self.index)
        except NotFoundError:
            # index has no docs, fixme: log something
            return [], 0, 0
        return expand_result(result['hits']['hits']), 0, result['hits']['total']['value']

    async def resolve_url(self, raw_url):
        try:
            url = URL.parse(raw_url)
        except ValueError as e:
            return e

        channel = None

        if url.has_channel:
            query = url.channel.to_dict()
            if set(query) == {'name'}:
                query['is_controlling'] = True
            else:
                query['order_by'] = ['^creation_height']
            matches, _, _ = await self.search(**query, limit=1)
            if matches:
                channel = matches[0]
            else:
                return LookupError(f'Could not find channel in "{raw_url}".')

        if url.has_stream:
            query = url.stream.to_dict()
            if channel is not None:
                if set(query) == {'name'}:
                    # temporarily emulate is_controlling for claims in channel
                    query['order_by'] = ['effective_amount', '^height']
                else:
                    query['order_by'] = ['^channel_join']
                query['channel_id'] = channel['claim_id']
                query['signature_valid'] = True
            elif set(query) == {'name'}:
                query['is_controlling'] = True
            matches, _, _ = await self.search(**query, limit=1)
            if matches:
                return matches[0]
            else:
                return LookupError(f'Could not find claim at "{raw_url}".')

        return channel

    async def _get_referenced_rows(self, txo_rows: List[dict]):
        txo_rows = [row for row in txo_rows if isinstance(row, dict)]
        repost_hashes = set(filter(None, map(itemgetter('reposted_claim_hash'), txo_rows)))
        channel_hashes = set(filter(None, (row['channel_hash'] for row in txo_rows)))
        channel_hashes |= set(filter(None, (row['censoring_channel_hash'] for row in txo_rows)))

        reposted_txos = []
        if repost_hashes:
            reposted_txos, _, _ = await self.search(**{'claim.claim_hash__in': repost_hashes})
            channel_hashes |= set(filter(None, (row['channel_hash'] for row in reposted_txos)))

        channel_txos = []
        if channel_hashes:
            channel_txos, _, _ = await self.search(**{'claim.claim_hash__in': channel_hashes})

        # channels must come first for client side inflation to work properly
        return channel_txos + reposted_txos


def extract_doc(doc, index):
    doc['claim_id'] = hexlify(doc.pop('claim_hash')[::-1]).decode()
    if doc['reposted_claim_hash'] is not None:
        doc['reposted_claim_id'] = hexlify(doc.pop('reposted_claim_hash')[::-1]).decode()
    else:
        doc['reposted_claim_id'] = None
    channel_hash = doc.pop('channel_hash')
    doc['channel_id'] = hexlify(channel_hash[::-1]).decode() if channel_hash else channel_hash
    channel_hash = doc.pop('censoring_channel_hash')
    doc['censoring_channel_hash'] = hexlify(channel_hash[::-1]).decode() if channel_hash else channel_hash
    txo_hash = doc.pop('txo_hash')
    doc['tx_id'] = hexlify(txo_hash[:32][::-1]).decode()
    doc['tx_nout'] = struct.unpack('<I', txo_hash[32:])[0]
    doc['is_controlling'] = bool(doc['is_controlling'])
    doc['signature'] = hexlify(doc.pop('signature') or b'').decode() or None
    doc['signature_digest'] = hexlify(doc.pop('signature_digest') or b'').decode() or None
    doc['public_key_bytes'] = hexlify(doc.pop('public_key_bytes') or b'').decode() or None
    doc['public_key_hash'] = hexlify(doc.pop('public_key_hash') or b'').decode() or None
    doc['signature_valid'] = bool(doc['signature_valid'])
    doc['claim_type'] = doc.get('claim_type', 0) or 0
    doc['stream_type'] = int(doc.get('stream_type', 0) or 0)
    return {'doc': doc, '_id': doc['claim_id'], '_index': index, '_op_type': 'update',
           'doc_as_upsert': True}


FIELDS = ['is_controlling', 'last_take_over_height', 'claim_id', 'claim_name', 'normalized', 'tx_position', 'amount',
          'timestamp', 'creation_timestamp', 'height', 'creation_height', 'activation_height', 'expiration_height',
          'release_time', 'short_url', 'canonical_url', 'title', 'author', 'description', 'claim_type', 'reposted',
          'stream_type', 'media_type', 'fee_amount', 'fee_currency', 'duration', 'reposted_claim_hash', 'censor_type',
          'claims_in_channel', 'channel_join', 'signature_valid', 'effective_amount', 'support_amount',
          'trending_group', 'trending_mixed', 'trending_local', 'trending_global', 'channel_id', 'tx_id', 'tx_nout',
          'signature', 'signature_digest', 'public_key_bytes', 'public_key_hash', 'public_key_id', '_id', 'tags',
          'reposted_claim_id']
TEXT_FIELDS = ['author', 'canonical_url', 'channel_id', 'claim_name', 'description',
               'media_type', 'normalized', 'public_key_bytes', 'public_key_hash', 'short_url', 'signature',
               'signature_digest', 'stream_type', 'title', 'tx_id', 'fee_currency', 'reposted_claim_id', 'tags']
RANGE_FIELDS = ['height', 'fee_amount', 'duration', 'reposted', 'release_time', 'censor_type']
REPLACEMENTS = {
    'name': 'normalized',
    'txid': 'tx_id',
    'claim_hash': '_id'
}


def expand_query(**kwargs):
    if 'name' in kwargs:
        kwargs['name'] = normalize_name(kwargs.pop('name'))
    query = {'must': [], 'must_not': []}
    collapse = None
    for key, value in kwargs.items():
        if value is None or isinstance(value, list) and len(value) == 0:
            continue
        key = key.replace('claim.', '')
        many = key.endswith('__in') or isinstance(value, list)
        if many:
            key = key.replace('__in', '')
        key = REPLACEMENTS.get(key, key)
        if key in FIELDS:
            partial_id = False
            if key == 'claim_type':
                if isinstance(value, str):
                    value = CLAIM_TYPES[value]
                else:
                    value = [CLAIM_TYPES[claim_type] for claim_type in value]
            if key == '_id':
                if isinstance(value, Iterable):
                    value = [hexlify(item[::-1]).decode() for item in value]
                else:
                    value = hexlify(value[::-1]).decode()
            if not many and key in ('_id', 'claim_id') and len(value) < 20:
                partial_id = True
            if key == 'public_key_id':
                key = 'public_key_hash'
                value = hexlify(Base58.decode(value)[1:21]).decode()
            if key == 'signature_valid':
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
                    value = Decimal(value)*1000
                query['must'].append({"range": {key: {ops[operator]: value}}})
            elif many:
                query['must'].append({"terms": {key: value}})
            else:
                if key == 'fee_amount':
                    value = Decimal(value)*1000
                query['must'].append({"term": {key: {"value": value}}})
        elif key == 'not_channel_ids':
            for channel_id in value:
                query['must_not'].append({"term": {'channel_id.keyword': channel_id}})
                query['must_not'].append({"term": {'_id': channel_id}})
        elif key == 'channel_ids':
            query['must'].append({"terms": {'channel_id.keyword': value}})
        elif key == 'media_types':
            query['must'].append({"terms": {'media_type.keyword': value}})
        elif key == 'stream_types':
            query['must'].append({"terms": {'stream_type': [STREAM_TYPES[stype] for stype in value]}})
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
        elif key == 'limit_claims_per_channel':
            collapse = ('channel_id.keyword', value)
    if kwargs.get('has_channel_signature'):
        query['must'].append({"exists": {"field": "signature_digest"}})
        if 'signature_valid' in kwargs:
            query['must'].append({"term": {"signature_valid": bool(kwargs["signature_valid"])}})
    elif 'signature_valid' in kwargs:
        query.setdefault('should', [])
        query["minimum_should_match"] = 1
        query['should'].append({"bool": {"must_not": {"exists": {"field": "signature_digest"}}}})
        query['should'].append({"term": {"signature_valid": bool(kwargs["signature_valid"])}})
    if 'text' in kwargs:
        return {"query":
                    {"simple_query_string":
                         {"query": kwargs["text"], "fields": [
                             "claim_name^4", "channel_name^8", "title^1", "description^.5", "author^1", "tags^.5"
                         ]}}}
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
        for value in kwargs['order_by']:
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


def expand_result(results):
    inner_hits = []
    for result in results:
        if result.get("inner_hits"):
            for _, inner_hit in result["inner_hits"].items():
                inner_hits.extend(inner_hit["hits"]["hits"])
            continue
        result.update(result.pop('_source'))
        result['claim_hash'] = unhexlify(result['claim_id'])[::-1]
        if result['reposted_claim_id']:
            result['reposted_claim_hash'] = unhexlify(result['reposted_claim_id'])[::-1]
        else:
            result['reposted_claim_hash'] = None
        result['channel_hash'] = unhexlify(result['channel_id'])[::-1] if result['channel_id'] else None
        result['txo_hash'] = unhexlify(result['tx_id'])[::-1] + struct.pack('<I', result['tx_nout'])
        result['tx_hash'] = unhexlify(result['tx_id'])[::-1]
        if result['censoring_channel_hash']:
            result['censoring_channel_hash'] = unhexlify(result['censoring_channel_hash'])[::-1]
    if inner_hits:
        return expand_result(inner_hits)
    return results
