import asyncio
import struct
from binascii import unhexlify
from collections import Counter, deque
from decimal import Decimal
from operator import itemgetter
from typing import Optional, List, Iterable, Union

from elasticsearch import AsyncElasticsearch, NotFoundError, ConnectionError
from elasticsearch.helpers import async_streaming_bulk

from lbry.crypto.base58 import Base58
from lbry.error import ResolveCensoredError, claim_id as parse_claim_id
from lbry.schema.result import Outputs, Censor
from lbry.schema.tags import clean_tags
from lbry.schema.url import URL, normalize_name
from lbry.utils import LRUCache
from lbry.wallet.server.db.common import CLAIM_TYPES, STREAM_TYPES
from lbry.wallet.server.db.elasticsearch.constants import INDEX_DEFAULT_SETTINGS, REPLACEMENTS, FIELDS, TEXT_FIELDS, \
    RANGE_FIELDS
from lbry.wallet.server.util import class_logger


class ChannelResolution(str):
    @classmethod
    def lookup_error(cls, url):
        return LookupError(f'Could not find channel in "{url}".')


class StreamResolution(str):
    @classmethod
    def lookup_error(cls, url):
        return LookupError(f'Could not find claim at "{url}".')


class IndexVersionMismatch(Exception):
    def __init__(self, got_version, expected_version):
        self.got_version = got_version
        self.expected_version = expected_version


class SearchIndex:
    VERSION = 1

    def __init__(self, index_prefix: str, search_timeout=3.0, elastic_host='localhost', elastic_port=9200):
        self.search_timeout = search_timeout
        self.sync_timeout = 600  # wont hit that 99% of the time, but can hit on a fresh import
        self.search_client: Optional[AsyncElasticsearch] = None
        self.sync_client: Optional[AsyncElasticsearch] = None
        self.index = index_prefix + 'claims'
        self.logger = class_logger(__name__, self.__class__.__name__)
        self.claim_cache = LRUCache(2 ** 15)
        self.short_id_cache = LRUCache(2 ** 17)
        self.search_cache = LRUCache(2 ** 17)
        self.resolution_cache = LRUCache(2 ** 17)
        self._elastic_host = elastic_host
        self._elastic_port = elastic_port

    async def get_index_version(self) -> int:
        try:
            template = await self.sync_client.indices.get_template(self.index)
            return template[self.index]['version']
        except NotFoundError:
            return 0

    async def set_index_version(self, version):
        await self.sync_client.indices.put_template(
            self.index, body={'version': version, 'index_patterns': ['ignored']}, ignore=400
        )

    async def start(self) -> bool:
        if self.sync_client:
            return False
        hosts = [{'host': self._elastic_host, 'port': self._elastic_port}]
        self.sync_client = AsyncElasticsearch(hosts, timeout=self.sync_timeout)
        self.search_client = AsyncElasticsearch(hosts, timeout=self.search_timeout)
        while True:
            try:
                await self.sync_client.cluster.health(wait_for_status='yellow')
                break
            except ConnectionError:
                self.logger.warning("Failed to connect to Elasticsearch. Waiting for it!")
                await asyncio.sleep(1)

        res = await self.sync_client.indices.create(self.index, INDEX_DEFAULT_SETTINGS, ignore=400)
        acked = res.get('acknowledged', False)
        if acked:
            await self.set_index_version(self.VERSION)
            return acked
        index_version = await self.get_index_version()
        if index_version != self.VERSION:
            self.logger.error("es search index has an incompatible version: %s vs %s", index_version, self.VERSION)
            raise IndexVersionMismatch(index_version, self.VERSION)
        return acked

    def stop(self):
        clients = [self.sync_client, self.search_client]
        self.sync_client, self.search_client = None, None
        return asyncio.ensure_future(asyncio.gather(*(client.close() for client in clients)))

    def delete_index(self):
        return self.sync_client.indices.delete(self.index, ignore_unavailable=True)

    async def _consume_claim_producer(self, claim_producer):
        count = 0
        for op, doc in claim_producer:
            if op == 'delete':
                yield {'_index': self.index, '_op_type': 'delete', '_id': doc}
            else:
                yield extract_doc(doc, self.index)
            count += 1
            if count % 100 == 0:
                self.logger.info("Indexing in progress, %d claims.", count)
        self.logger.info("Indexing done for %d claims.", count)

    async def claim_consumer(self, claim_producer):
        touched = set()
        async for ok, item in async_streaming_bulk(self.sync_client, self._consume_claim_producer(claim_producer),
                                                   raise_on_error=False):
            if not ok:
                self.logger.warning("indexing failed for an item: %s", item)
            else:
                item = item.popitem()[1]
                touched.add(item['_id'])
        await self.sync_client.indices.refresh(self.index)
        self.logger.info("Indexing done.")

    def update_filter_query(self, censor_type, blockdict, channels=False):
        blockdict = {key[::-1].hex(): value[::-1].hex() for key, value in blockdict.items()}
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

    async def apply_filters(self, blocked_streams, blocked_channels, filtered_streams, filtered_channels):
        if filtered_streams:
            await self.sync_client.update_by_query(
                self.index, body=self.update_filter_query(Censor.SEARCH, filtered_streams), slices=4)
            await self.sync_client.indices.refresh(self.index)
        if filtered_channels:
            await self.sync_client.update_by_query(
                self.index, body=self.update_filter_query(Censor.SEARCH, filtered_channels), slices=4)
            await self.sync_client.indices.refresh(self.index)
            await self.sync_client.update_by_query(
                self.index, body=self.update_filter_query(Censor.SEARCH, filtered_channels, True), slices=4)
            await self.sync_client.indices.refresh(self.index)
        if blocked_streams:
            await self.sync_client.update_by_query(
                self.index, body=self.update_filter_query(Censor.RESOLVE, blocked_streams), slices=4)
            await self.sync_client.indices.refresh(self.index)
        if blocked_channels:
            await self.sync_client.update_by_query(
                self.index, body=self.update_filter_query(Censor.RESOLVE, blocked_channels), slices=4)
            await self.sync_client.indices.refresh(self.index)
            await self.sync_client.update_by_query(
                self.index, body=self.update_filter_query(Censor.RESOLVE, blocked_channels, True), slices=4)
            await self.sync_client.indices.refresh(self.index)
        self.clear_caches()

    def clear_caches(self):
        self.search_cache.clear()
        self.short_id_cache.clear()
        self.claim_cache.clear()
        self.resolution_cache.clear()

    async def session_query(self, query_name, kwargs):
        offset, total = kwargs.get('offset', 0) if isinstance(kwargs, dict) else 0, 0
        total_referenced = []
        if query_name == 'resolve':
            total_referenced, response, censor = await self.resolve(*kwargs)
        else:
            cache_item = ResultCacheItem.from_cache(str(kwargs), self.search_cache)
            if cache_item.result is not None:
                return cache_item.result
            async with cache_item.lock:
                if cache_item.result:
                    return cache_item.result
                censor = Censor(Censor.SEARCH)
                if kwargs.get('no_totals'):
                    response, offset, total = await self.search(**kwargs, censor_type=Censor.NOT_CENSORED)
                else:
                    response, offset, total = await self.search(**kwargs)
                censor.apply(response)
                total_referenced.extend(response)
                if censor.censored:
                    response, _, _ = await self.search(**kwargs, censor_type=Censor.NOT_CENSORED)
                    total_referenced.extend(response)
                result = Outputs.to_base64(
                    response, await self._get_referenced_rows(total_referenced), offset, total, censor
                )
                cache_item.result = result
                return result
        return Outputs.to_base64(response, await self._get_referenced_rows(total_referenced), offset, total, censor)

    async def resolve(self, *urls):
        censor = Censor(Censor.RESOLVE)
        results = [await self.resolve_url(url) for url in urls]
        # just heat the cache
        await self.populate_claim_cache(*filter(lambda x: isinstance(x, str), results))
        results = [self._get_from_cache_or_error(url, result) for url, result in zip(urls, results)]

        censored = [
            result if not isinstance(result, dict) or not censor.censor(result)
            else ResolveCensoredError(url, result['censoring_channel_hash'])
            for url, result in zip(urls, results)
        ]
        return results, censored, censor

    def _get_from_cache_or_error(self, url: str, resolution: Union[LookupError, StreamResolution, ChannelResolution]):
        cached = self.claim_cache.get(resolution)
        return cached or (resolution if isinstance(resolution, LookupError) else resolution.lookup_error(url))

    async def get_many(self, *claim_ids):
        await self.populate_claim_cache(*claim_ids)
        return filter(None, map(self.claim_cache.get, claim_ids))

    async def populate_claim_cache(self, *claim_ids):
        missing = [claim_id for claim_id in claim_ids if self.claim_cache.get(claim_id) is None]
        if missing:
            results = await self.search_client.mget(
                index=self.index, body={"ids": missing}
            )
            for result in expand_result(filter(lambda doc: doc['found'], results["docs"])):
                self.claim_cache.set(result['claim_id'], result)

    async def full_id_from_short_id(self, name, short_id, channel_id=None):
        key = '#'.join((channel_id or '', name, short_id))
        if key not in self.short_id_cache:
            query = {'name': name, 'claim_id': short_id}
            if channel_id:
                query['channel_id'] = channel_id
                query['order_by'] = ['^channel_join']
                query['signature_valid'] = True
            else:
                query['order_by'] = '^creation_height'
            result, _, _ = await self.search(**query, limit=1)
            if len(result) == 1:
                result = result[0]['claim_id']
                self.short_id_cache[key] = result
        return self.short_id_cache.get(key, None)

    async def search(self, **kwargs):
        if 'channel' in kwargs:
            kwargs['channel_id'] = await self.resolve_url(kwargs.pop('channel'))
            if not kwargs['channel_id'] or not isinstance(kwargs['channel_id'], str):
                return [], 0, 0
        try:
            return await self.search_ahead(**kwargs)
        except NotFoundError:
            return [], 0, 0
        return expand_result(result['hits']), 0, result.get('total', {}).get('value', 0)

    async def search_ahead(self, **kwargs):
        # 'limit_claims_per_channel' case. Fetch 1000 results, reorder, slice, inflate and return
        per_channel_per_page = kwargs.pop('limit_claims_per_channel')
        page_size = kwargs.pop('limit', 10)
        offset = kwargs.pop('offset', 0)
        kwargs['limit'] = 1000
        cache_item = ResultCacheItem.from_cache(f"ahead{per_channel_per_page}{kwargs}", self.search_cache)
        if cache_item.result is not None:
            reordered_hits = cache_item.result
        else:
            async with cache_item.lock:
                if cache_item.result:
                    reordered_hits = cache_item.result
                else:
                    query = expand_query(**kwargs)
                    reordered_hits = await self.__search_ahead(query, page_size, per_channel_per_page)
                    cache_item.result = reordered_hits
        result = list(await self.get_many(*(claim_id for claim_id, _ in reordered_hits[offset:(offset + page_size)])))
        return result, 0, len(reordered_hits)

    async def __search_ahead(self, query: dict, page_size: int, per_channel_per_page: int):
        search_hits = deque((await self.search_client.search(
            query, index=self.index, track_total_hits=False, _source_includes=['_id', 'channel_id']
        ))['hits']['hits'])
        reordered_hits = []
        channel_counters = Counter()
        next_page_hits_maybe_check_later = deque()
        while search_hits or next_page_hits_maybe_check_later:
            if reordered_hits and len(reordered_hits) % page_size == 0:
                channel_counters.clear()
            elif not reordered_hits:
                pass
            else:
                break  # means last page was incomplete and we are left with bad replacements
            for _ in range(len(next_page_hits_maybe_check_later)):
                claim_id, channel_id = next_page_hits_maybe_check_later.popleft()
                if channel_counters[channel_id] < per_channel_per_page:
                    reordered_hits.append((claim_id, channel_id))
                    channel_counters[channel_id] += 1
                else:
                    next_page_hits_maybe_check_later.append((claim_id, channel_id))
            while search_hits:
                hit = search_hits.popleft()
                hit_id, hit_channel_id = hit['_id'], hit['_source']['channel_id']
                if hit_channel_id is None:
                    reordered_hits.append((hit_id, hit_channel_id))
                elif channel_counters[hit_channel_id] < per_channel_per_page:
                    reordered_hits.append((hit_id, hit_channel_id))
                    channel_counters[hit_channel_id] += 1
                    if len(reordered_hits) % page_size == 0:
                        break
                else:
                    next_page_hits_maybe_check_later.append((hit_id, hit_channel_id))
        return reordered_hits

    async def resolve_url(self, raw_url):
        if raw_url not in self.resolution_cache:
            self.resolution_cache[raw_url] = await self._resolve_url(raw_url)
        return self.resolution_cache[raw_url]

    async def _resolve_url(self, raw_url):
        try:
            url = URL.parse(raw_url)
        except ValueError as e:
            return e

        stream = LookupError(f'Could not find claim at "{raw_url}".')

        channel_id = await self.resolve_channel_id(url)
        if isinstance(channel_id, LookupError):
            return channel_id
        stream = (await self.resolve_stream(url, channel_id if isinstance(channel_id, str) else None)) or stream
        if url.has_stream:
            return StreamResolution(stream)
        else:
            return ChannelResolution(channel_id)

    async def resolve_channel_id(self, url: URL):
        if not url.has_channel:
            return
        if url.channel.is_fullid:
            return url.channel.claim_id
        if url.channel.is_shortid:
            channel_id = await self.full_id_from_short_id(url.channel.name, url.channel.claim_id)
            if not channel_id:
                return LookupError(f'Could not find channel in "{url}".')
            return channel_id

        query = url.channel.to_dict()
        if set(query) == {'name'}:
            query['is_controlling'] = True
        else:
            query['order_by'] = ['^creation_height']
        matches, _, _ = await self.search(**query, limit=1)
        if matches:
            channel_id = matches[0]['claim_id']
        else:
            return LookupError(f'Could not find channel in "{url}".')
        return channel_id

    async def resolve_stream(self, url: URL, channel_id: str = None):
        if not url.has_stream:
            return None
        if url.has_channel and channel_id is None:
            return None
        query = url.stream.to_dict()
        if url.stream.claim_id is not None:
            if url.stream.is_fullid:
                claim_id = url.stream.claim_id
            else:
                claim_id = await self.full_id_from_short_id(query['name'], query['claim_id'], channel_id)
            return claim_id

        if channel_id is not None:
            if set(query) == {'name'}:
                # temporarily emulate is_controlling for claims in channel
                query['order_by'] = ['effective_amount', '^height']
            else:
                query['order_by'] = ['^channel_join']
            query['channel_id'] = channel_id
            query['signature_valid'] = True
        elif set(query) == {'name'}:
            query['is_controlling'] = True
        matches, _, _ = await self.search(**query, limit=1)
        if matches:
            return matches[0]['claim_id']

    async def _get_referenced_rows(self, txo_rows: List[dict]):
        txo_rows = [row for row in txo_rows if isinstance(row, dict)]
        referenced_ids = set(filter(None, map(itemgetter('reposted_claim_id'), txo_rows)))
        referenced_ids |= set(filter(None, (row['channel_id'] for row in txo_rows)))
        referenced_ids |= set(map(parse_claim_id, filter(None, (row['censoring_channel_hash'] for row in txo_rows))))

        referenced_txos = []
        if referenced_ids:
            referenced_txos.extend(await self.get_many(*referenced_ids))
            referenced_ids = set(filter(None, (row['channel_id'] for row in referenced_txos)))

        if referenced_ids:
            referenced_txos.extend(await self.get_many(*referenced_ids))

        return referenced_txos


def extract_doc(doc, index):
    doc['claim_id'] = doc.pop('claim_hash')[::-1].hex()
    if doc['reposted_claim_hash'] is not None:
        doc['reposted_claim_id'] = doc.pop('reposted_claim_hash')[::-1].hex()
    else:
        doc['reposted_claim_id'] = None
    channel_hash = doc.pop('channel_hash')
    doc['channel_id'] = channel_hash[::-1].hex() if channel_hash else channel_hash
    channel_hash = doc.pop('censoring_channel_hash')
    doc['censoring_channel_hash'] = channel_hash[::-1].hex() if channel_hash else channel_hash
    txo_hash = doc.pop('txo_hash')
    doc['tx_id'] = txo_hash[:32][::-1].hex()
    doc['tx_nout'] = struct.unpack('<I', txo_hash[32:])[0]
    doc['is_controlling'] = bool(doc['is_controlling'])
    doc['signature'] = (doc.pop('signature') or b'').hex() or None
    doc['signature_digest'] = (doc.pop('signature_digest') or b'').hex() or None
    doc['public_key_bytes'] = (doc.pop('public_key_bytes') or b'').hex() or None
    doc['public_key_hash'] = (doc.pop('public_key_hash') or b'').hex() or None
    doc['signature_valid'] = bool(doc['signature_valid'])
    doc['claim_type'] = doc.get('claim_type', 0) or 0
    doc['stream_type'] = int(doc.get('stream_type', 0) or 0)
    doc['has_source'] = bool(doc['has_source'])
    return {'doc': doc, '_id': doc['claim_id'], '_index': index, '_op_type': 'update', 'doc_as_upsert': True}


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
    for key, value in kwargs.items():
        key = key.replace('claim.', '')
        many = key.endswith('__in') or isinstance(value, list)
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
            if key == '_id':
                if isinstance(value, Iterable):
                    value = [item[::-1].hex() for item in value]
                else:
                    value = value[::-1].hex()
            if not many and key in ('_id', 'claim_id') and len(value) < 20:
                partial_id = True
            if key == 'public_key_id':
                key = 'public_key_hash'
                value = Base58.decode(value)[1:21].hex()
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
        elif key == 'not_claim_id':
            query['must_not'].extend([{"term": {'claim_id.keyword': cid}} for cid in value])
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


def expand_result(results):
    inner_hits = []
    expanded = []
    for result in results:
        if result.get("inner_hits"):
            for _, inner_hit in result["inner_hits"].items():
                inner_hits.extend(inner_hit["hits"]["hits"])
            continue
        result = result['_source']
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
        expanded.append(result)
    if inner_hits:
        return expand_result(inner_hits)
    return expanded


class ResultCacheItem:
    __slots__ = '_result', 'lock', 'has_result'

    def __init__(self):
        self.has_result = asyncio.Event()
        self.lock = asyncio.Lock()
        self._result = None

    @property
    def result(self) -> str:
        return self._result

    @result.setter
    def result(self, result: str):
        self._result = result
        if result is not None:
            self.has_result.set()

    @classmethod
    def from_cache(cls, cache_key, cache):
        cache_item = cache.get(cache_key)
        if cache_item is None:
            cache_item = cache[cache_key] = ResultCacheItem()
        return cache_item
