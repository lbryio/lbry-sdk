import asyncio
from pprint import pprint

from elasticsearch import AsyncElasticsearch
from elasticsearch._async.helpers import async_scan, async_bulk

DB = {}
INDEX = 'claims'


async def generate_support_amounts(client: AsyncElasticsearch):
    async for doc in async_scan(client):
        DB[doc['_id']] = doc['_source']['support_amount']
        if len(DB) > 10:
            break
    pprint(DB)


def generate_support_to_trending():
    for claim_id, amount in DB.items():
        yield {'doc': {"trending_mixed": amount}, '_id': claim_id, '_index': INDEX, '_op_type': 'update'}


async def write_trending(client: AsyncElasticsearch):
    await async_bulk(client, generate_support_to_trending())


def get_client(host='localhost', port=9201):
    hosts = [{'host': host, 'port': port}]
    return AsyncElasticsearch(hosts, timeout=port)


async def run():
    client = get_client()
    await generate_support_amounts(client)
    await write_trending(client)
    for claim_id, value in DB.items():
        if value > 0:
            break
    doc = await client.get(INDEX, claim_id)
    pprint(doc)
    pprint(DB[claim_id])
    await client.close()


asyncio.get_event_loop().run_until_complete(run())