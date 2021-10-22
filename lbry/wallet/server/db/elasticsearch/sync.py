import os
import argparse
import asyncio
import logging
from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_streaming_bulk
from lbry.wallet.server.env import Env
from lbry.wallet.server.leveldb import LevelDB
from lbry.wallet.server.db.elasticsearch.search import SearchIndex, IndexVersionMismatch
from lbry.wallet.server.db.elasticsearch.constants import ALL_FIELDS


async def get_recent_claims(env, index_name='claims', db=None):
    need_open = db is None
    db = db or LevelDB(env)
    try:
        if need_open:
            db.open_db()
        if db.es_sync_height == db.db_height or db.db_height <= 0:
            return
        if need_open:
            await db.initialize_caches()
        cnt = 0
        touched_claims = set()
        deleted_claims = set()
        for height in range(db.es_sync_height, db.db_height + 1):
            touched_or_deleted = db.prefix_db.touched_or_deleted.get(height)
            touched_claims.update(touched_or_deleted.touched_claims)
            deleted_claims.update(touched_or_deleted.deleted_claims)
            touched_claims.difference_update(deleted_claims)

        for deleted in deleted_claims:
            yield {
                '_index': index_name,
                '_op_type': 'delete',
                '_id': deleted.hex()
            }
        for touched in touched_claims:
            claim = db.claim_producer(touched)
            if claim:
                yield {
                    'doc': {key: value for key, value in claim.items() if key in ALL_FIELDS},
                    '_id': claim['claim_id'],
                    '_index': index_name,
                    '_op_type': 'update',
                    'doc_as_upsert': True
                }
                cnt += 1
            else:
                logging.warning("could not sync claim %s", touched.hex())
            if cnt % 10000 == 0:
                logging.info("%i claims sent to ES", cnt)

        db.es_sync_height = db.db_height
        db.write_db_state()
        db.prefix_db.unsafe_commit()
        db.assert_db_state()

        logging.info("finished sending %i claims to ES, deleted %i", cnt, len(touched_claims), len(deleted_claims))
    finally:
        if need_open:
            db.close()


async def get_all_claims(env, index_name='claims', db=None):
    need_open = db is None
    db = db or LevelDB(env)
    if need_open:
        db.open_db()
        await db.initialize_caches()
    logging.info("Fetching claims to send ES from leveldb")
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
                logging.info("sent %i claims to ES", cnt)
    finally:
        if need_open:
            db.close()


async def make_es_index_and_run_sync(env: Env, clients=32, force=False, db=None, index_name='claims'):
    index = SearchIndex(env.es_index_prefix, elastic_host=env.elastic_host, elastic_port=env.elastic_port)
    logging.info("ES sync host: %s:%i", env.elastic_host, env.elastic_port)
    try:
        created = await index.start()
    except IndexVersionMismatch as err:
        logging.info(
            "dropping ES search index (version %s) for upgrade to version %s", err.got_version, err.expected_version
        )
        await index.delete_index()
        await index.stop()
        created = await index.start()
    finally:
        index.stop()

    es = AsyncElasticsearch([{'host': env.elastic_host, 'port': env.elastic_port}])
    if force or created:
        claim_generator = get_all_claims(env, index_name=index_name, db=db)
    else:
        claim_generator = get_recent_claims(env, index_name=index_name, db=db)
    try:
        async for ok, item in async_streaming_bulk(es, claim_generator, request_timeout=600, raise_on_error=False):
            if not ok:
                logging.warning("indexing failed for an item: %s", item)
        await es.indices.refresh(index=index_name)
    finally:
        await es.close()


def run_elastic_sync():
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('elasticsearch').setLevel(logging.WARNING)

    logging.info('lbry.server starting')
    parser = argparse.ArgumentParser(prog="lbry-hub-elastic-sync")
    parser.add_argument("-c", "--clients", type=int, default=32)
    parser.add_argument("-f", "--force", default=False, action='store_true')
    Env.contribute_to_arg_parser(parser)
    args = parser.parse_args()
    env = Env.from_arg_parser(args)

    if not os.path.exists(os.path.join(args.db_dir, 'lbry-leveldb')):
        logging.info("DB path doesnt exist, nothing to sync to ES")
        return

    asyncio.run(make_es_index_and_run_sync(env, clients=args.clients, force=args.force))
