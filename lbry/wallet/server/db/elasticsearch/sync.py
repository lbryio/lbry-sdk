import argparse
import asyncio
import logging
from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk
from lbry.wallet.server.env import Env
from lbry.wallet.server.coin import LBC
from lbry.wallet.server.leveldb import LevelDB
from lbry.wallet.server.db.elasticsearch.search import SearchIndex, IndexVersionMismatch
from lbry.wallet.server.db.elasticsearch.constants import ALL_FIELDS


async def get_all_claims(index_name='claims', db=None):
    env = Env(LBC)
    need_open = db is None
    db = db or LevelDB(env)
    if need_open:
        await db.open_dbs()
    try:
        cnt = 0
        async for claim in db.all_claims_producer():
            yield {
                'doc': {key: value for key, value in claim.items() if key in ALL_FIELDS},
                '_id': claim['claim_id'],
                '_index': index_name,
                '_op_type': 'update',
                'doc_as_upsert': True
            }
            cnt += 1
            if cnt % 10000 == 0:
                print(f"{cnt} claims sent")
    finally:
        if need_open:
            db.close()


async def make_es_index(index=None):
    env = Env(LBC)
    if index is None:
        index = SearchIndex('', elastic_host=env.elastic_host, elastic_port=env.elastic_port)

    try:
        return await index.start()
    except IndexVersionMismatch as err:
        logging.info(
            "dropping ES search index (version %s) for upgrade to version %s", err.got_version, err.expected_version
        )
        await index.delete_index()
        await index.stop()
        return await index.start()
    finally:
        index.stop()


async def run_sync(index_name='claims', db=None, clients=32):
    env = Env(LBC)
    logging.info("ES sync host: %s:%i", env.elastic_host, env.elastic_port)
    es = AsyncElasticsearch([{'host': env.elastic_host, 'port': env.elastic_port}])
    claim_generator = get_all_claims(index_name=index_name, db=db)

    try:
        await async_bulk(es, claim_generator, request_timeout=600)
        await es.indices.refresh(index=index_name)
    finally:
        await es.close()


def run_elastic_sync():
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('elasticsearch').setLevel(logging.WARNING)

    logging.info('lbry.server starting')
    parser = argparse.ArgumentParser(prog="lbry-hub-elastic-sync")
    # parser.add_argument("db_path", type=str)
    parser.add_argument("-c", "--clients", type=int, default=32)
    parser.add_argument("-b", "--blocks", type=int, default=0)
    parser.add_argument("-f", "--force", default=False, action='store_true')
    args = parser.parse_args()

    # if not args.force and not os.path.exists(args.db_path):
    #     logging.info("DB path doesnt exist")
    #     return

    if not args.force and not asyncio.run(make_es_index()):
        logging.info("ES is already initialized")
        return
    asyncio.run(run_sync(clients=args.clients))
