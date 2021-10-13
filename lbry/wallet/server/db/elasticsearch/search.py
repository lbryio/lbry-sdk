import time
import asyncio
import struct
from binascii import unhexlify
from collections import Counter, deque
from decimal import Decimal
from operator import itemgetter
from typing import Optional, List, Iterable, Union

from elasticsearch import AsyncElasticsearch, NotFoundError, ConnectionError
from elasticsearch.helpers import async_streaming_bulk
from lbry.error import ResolveCensoredError, TooManyClaimSearchParametersError
from lbry.schema.result import Outputs, Censor
from lbry.schema.tags import clean_tags
from lbry.schema.url import URL, normalize_name
from lbry.utils import LRUCache
from lbry.wallet.server.db.common import CLAIM_TYPES, STREAM_TYPES
from lbry.wallet.server.db.elasticsearch.constants import INDEX_DEFAULT_SETTINGS, REPLACEMENTS, FIELDS, TEXT_FIELDS, \
    RANGE_FIELDS, ALL_FIELDS
from lbry.wallet.server.util import class_logger
from lbry.wallet.server.db.common import ResolveResult


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

    def __init__(self, index_prefix: str, search_timeout=3.0, elastic_host='localhost', elastic_port=9200,
                 half_life=0.4, whale_threshold=10000, whale_half_life=0.99):
        self.search_timeout = search_timeout
        self.sync_timeout = 600  # wont hit that 99% of the time, but can hit on a fresh import
        self.search_client: Optional[AsyncElasticsearch] = None
        self.sync_client: Optional[AsyncElasticsearch] = None
        self.index = index_prefix + 'claims'
        self.logger = class_logger(__name__, self.__class__.__name__)
        self.claim_cache = LRUCache(2 ** 15)
        self.search_cache = LRUCache(2 ** 17)
        self._elastic_host = elastic_host
        self._elastic_port = elastic_port
        self._trending_half_life = half_life
        self._trending_whale_threshold = whale_threshold
        self._trending_whale_half_life = whale_half_life

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
        await self.sync_client.indices.refresh(self.index)
        return acked

    def stop(self):
        clients = [self.sync_client, self.search_client]
        self.sync_client, self.search_client = None, None
        return asyncio.ensure_future(asyncio.gather(*(client.close() for client in clients)))

    def delete_index(self):
        return self.sync_client.indices.delete(self.index, ignore_unavailable=True)

    async def _consume_claim_producer(self, claim_producer):
        count = 0
        async for op, doc in claim_producer:
            if op == 'delete':
                yield {
                    '_index': self.index,
                    '_op_type': 'delete',
                    '_id': doc
                }
            else:
                yield {
                    'doc': {key: value for key, value in doc.items() if key in ALL_FIELDS},
                    '_id': doc['claim_id'],
                    '_index': self.index,
                    '_op_type': 'update',
                    'doc_as_upsert': True
                }
            count += 1
            if count % 100 == 0:
                self.logger.info("Indexing in progress, %d claims.", count)
        if count:
            self.logger.info("Indexing done for %d claims.", count)
        else:
            self.logger.debug("Indexing done for %d claims.", count)

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
        self.logger.debug("Indexing done.")

    def update_filter_query(self, censor_type, blockdict, channels=False):
        blockdict = {blocked.hex(): blocker.hex() for blocked, blocker in blockdict.items()}
        if channels:
            update = expand_query(channel_id__in=list(blockdict.keys()), censor_type=f"<{censor_type}")
        else:
            update = expand_query(claim_id__in=list(blockdict.keys()), censor_type=f"<{censor_type}")
        key = 'channel_id' if channels else 'claim_id'
        update['script'] = {
            "source": f"ctx._source.censor_type={censor_type}; "
                      f"ctx._source.censoring_channel_id=params[ctx._source.{key}];",
            "lang": "painless",
            "params": blockdict
        }
        return update

    async def update_trending_score(self, params):
        update_trending_score_script = """
        double softenLBC(double lbc) { Math.pow(lbc, 1.0f / 3.0f) }
        double inflateUnits(int height) {
            int renormalizationPeriod = 100000;
            double doublingRate = 400.0f;
            Math.pow(2.0, (height % renormalizationPeriod) / doublingRate)
        }
        double spikePower(double newAmount) {
            if (newAmount < 50.0) {
                0.5
            } else if (newAmount < 85.0) {
                newAmount / 100.0
            } else {
                0.85
            }
        }
        double spikeMass(double oldAmount, double newAmount) {
            double softenedChange = softenLBC(Math.abs(newAmount - oldAmount));
            double changeInSoftened = Math.abs(softenLBC(newAmount) - softenLBC(oldAmount));
            double power = spikePower(newAmount);
            if (oldAmount > newAmount) {
                -1.0 * Math.pow(changeInSoftened, power) * Math.pow(softenedChange, 1.0 - power)
            } else {
                Math.pow(changeInSoftened, power) * Math.pow(softenedChange, 1.0 - power)
            }
        }
        for (i in params.src.changes) {
            double units = inflateUnits(i.height);
            if (i.added) {
                if (ctx._source.trending_score == null) {
                    ctx._source.trending_score = (units * spikeMass(i.prev_amount, i.prev_amount + i.new_amount));
                } else {
                    ctx._source.trending_score += (units * spikeMass(i.prev_amount, i.prev_amount + i.new_amount));
                }
            } else {
                if (ctx._source.trending_score == null) {
                    ctx._source.trending_score = (units * spikeMass(i.prev_amount, i.prev_amount - i.new_amount));
                } else {
                    ctx._source.trending_score += (units * spikeMass(i.prev_amount, i.prev_amount - i.new_amount));
                }
            }
        }
        """
        start = time.perf_counter()

        def producer():
            for claim_id, claim_updates in params.items():
                yield {
                    '_id': claim_id,
                    '_index': self.index,
                    '_op_type': 'update',
                    'script': {
                        'lang': 'painless',
                        'source': update_trending_score_script,
                        'params': {'src': {
                            'changes': [
                                {
                                    'height': p.height,
                                    'added': p.added,
                                    'prev_amount': p.prev_amount * 1E-9,
                                    'new_amount': p.new_amount * 1E-9,
                                } for p in claim_updates
                            ]
                        }}
                    },
                }
        if not params:
            return
        async for ok, item in async_streaming_bulk(self.sync_client, producer(), raise_on_error=False):
            if not ok:
                self.logger.warning("updating trending failed for an item: %s", item)
        await self.sync_client.indices.refresh(self.index)
        self.logger.info("updated trending scores in %ims", int((time.perf_counter() - start) * 1000))

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
        self.claim_cache.clear()

    async def cached_search(self, kwargs):
        total_referenced = []
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
            response = [
                ResolveResult(
                    name=r['claim_name'],
                    normalized_name=r['normalized_name'],
                    claim_hash=r['claim_hash'],
                    tx_num=r['tx_num'],
                    position=r['tx_nout'],
                    tx_hash=r['tx_hash'],
                    height=r['height'],
                    amount=r['amount'],
                    short_url=r['short_url'],
                    is_controlling=r['is_controlling'],
                    canonical_url=r['canonical_url'],
                    creation_height=r['creation_height'],
                    activation_height=r['activation_height'],
                    expiration_height=r['expiration_height'],
                    effective_amount=r['effective_amount'],
                    support_amount=r['support_amount'],
                    last_takeover_height=r['last_take_over_height'],
                    claims_in_channel=r['claims_in_channel'],
                    channel_hash=r['channel_hash'],
                    reposted_claim_hash=r['reposted_claim_hash'],
                    reposted=r['reposted'],
                    signature_valid=r['signature_valid']
                ) for r in response
            ]
            extra = [
                ResolveResult(
                    name=r['claim_name'],
                    normalized_name=r['normalized_name'],
                    claim_hash=r['claim_hash'],
                    tx_num=r['tx_num'],
                    position=r['tx_nout'],
                    tx_hash=r['tx_hash'],
                    height=r['height'],
                    amount=r['amount'],
                    short_url=r['short_url'],
                    is_controlling=r['is_controlling'],
                    canonical_url=r['canonical_url'],
                    creation_height=r['creation_height'],
                    activation_height=r['activation_height'],
                    expiration_height=r['expiration_height'],
                    effective_amount=r['effective_amount'],
                    support_amount=r['support_amount'],
                    last_takeover_height=r['last_take_over_height'],
                    claims_in_channel=r['claims_in_channel'],
                    channel_hash=r['channel_hash'],
                    reposted_claim_hash=r['reposted_claim_hash'],
                    reposted=r['reposted'],
                    signature_valid=r['signature_valid']
                ) for r in await self._get_referenced_rows(total_referenced)
            ]
            result = Outputs.to_base64(
                response, extra, offset, total, censor
            )
            cache_item.result = result
            return result

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


    async def search(self, **kwargs):
        try:
            return await self.search_ahead(**kwargs)
        except NotFoundError:
            return [], 0, 0
        # return expand_result(result['hits']), 0, result.get('total', {}).get('value', 0)

    async def search_ahead(self, **kwargs):
        # 'limit_claims_per_channel' case. Fetch 1000 results, reorder, slice, inflate and return
        per_channel_per_page = kwargs.pop('limit_claims_per_channel', 0) or 0
        remove_duplicates = kwargs.pop('remove_duplicates', False)
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
                    search_hits = deque((await self.search_client.search(
                        query, index=self.index, track_total_hits=False,
                        _source_includes=['_id', 'channel_id', 'reposted_claim_id', 'creation_height']
                    ))['hits']['hits'])
                    if remove_duplicates:
                        search_hits = self.__remove_duplicates(search_hits)
                    if per_channel_per_page > 0:
                        reordered_hits = self.__search_ahead(search_hits, page_size, per_channel_per_page)
                    else:
                        reordered_hits = [(hit['_id'], hit['_source']['channel_id']) for hit in search_hits]
                    cache_item.result = reordered_hits
        result = list(await self.get_many(*(claim_id for claim_id, _ in reordered_hits[offset:(offset + page_size)])))
        return result, 0, len(reordered_hits)

    def __remove_duplicates(self, search_hits: deque) -> deque:
        known_ids = {}  # claim_id -> (creation_height, hit_id), where hit_id is either reposted claim id or original
        dropped = set()
        for hit in search_hits:
            hit_height, hit_id = hit['_source']['creation_height'], hit['_source']['reposted_claim_id'] or hit['_id']
            if hit_id not in known_ids:
                known_ids[hit_id] = (hit_height, hit['_id'])
            else:
                previous_height, previous_id = known_ids[hit_id]
                if hit_height < previous_height:
                    known_ids[hit_id] = (hit_height, hit['_id'])
                    dropped.add(previous_id)
                else:
                    dropped.add(hit['_id'])
        return deque(hit for hit in search_hits if hit['_id'] not in dropped)

    def __search_ahead(self, search_hits: list, page_size: int, per_channel_per_page: int):
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
                if per_channel_per_page > 0 and channel_counters[channel_id] < per_channel_per_page:
                    reordered_hits.append((claim_id, channel_id))
                    channel_counters[channel_id] += 1
                else:
                    next_page_hits_maybe_check_later.append((claim_id, channel_id))
            while search_hits:
                hit = search_hits.popleft()
                hit_id, hit_channel_id = hit['_id'], hit['_source']['channel_id']
                if hit_channel_id is None or per_channel_per_page <= 0:
                    reordered_hits.append((hit_id, hit_channel_id))
                elif channel_counters[hit_channel_id] < per_channel_per_page:
                    reordered_hits.append((hit_id, hit_channel_id))
                    channel_counters[hit_channel_id] += 1
                    if len(reordered_hits) % page_size == 0:
                        break
                else:
                    next_page_hits_maybe_check_later.append((hit_id, hit_channel_id))
        return reordered_hits

    async def _get_referenced_rows(self, txo_rows: List[dict]):
        txo_rows = [row for row in txo_rows if isinstance(row, dict)]
        referenced_ids = set(filter(None, map(itemgetter('reposted_claim_id'), txo_rows)))
        referenced_ids |= set(filter(None, (row['channel_id'] for row in txo_rows)))
        referenced_ids |= set(filter(None, (row['censoring_channel_id'] for row in txo_rows)))

        referenced_txos = []
        if referenced_ids:
            referenced_txos.extend(await self.get_many(*referenced_ids))
            referenced_ids = set(filter(None, (row['channel_id'] for row in referenced_txos)))

        if referenced_ids:
            referenced_txos.extend(await self.get_many(*referenced_ids))

        return referenced_txos


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
        result['reposted'] = result.pop('repost_count')
        result['signature_valid'] = result.pop('is_signature_valid')
        # result['normalized'] = result.pop('normalized_name')
        # if result['censoring_channel_hash']:
        #     result['censoring_channel_hash'] = unhexlify(result['censoring_channel_hash'])[::-1]
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
