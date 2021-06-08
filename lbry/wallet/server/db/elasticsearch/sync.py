import argparse
import asyncio
import logging
import os
from collections import namedtuple
from multiprocessing import Process

import apsw
from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk
from lbry.wallet.server.env import Env
from lbry.wallet.server.coin import LBC
from lbry.wallet.server.db.elasticsearch.search import extract_doc, SearchIndex, IndexVersionMismatch


async def get_all(db, shard_num, shards_total, limit=0, index_name='claims'):
    logging.info("shard %d starting", shard_num)
    def exec_factory(cursor, statement, bindings):
        tpl = namedtuple('row', (d[0] for d in cursor.getdescription()))
        cursor.setrowtrace(lambda cursor, row: tpl(*row))
        return True

    db.setexectrace(exec_factory)
    total = db.execute(f"select count(*) as total from claim where height % {shards_total} = {shard_num};").fetchone()[0]
    for num, claim in enumerate(db.execute(f"""
SELECT claimtrie.claim_hash as is_controlling,
       claimtrie.last_take_over_height,
       (select group_concat(tag, ',,') from tag where tag.claim_hash in (claim.claim_hash, claim.reposted_claim_hash)) as tags,
       (select group_concat(language, ' ') from language where language.claim_hash in (claim.claim_hash, claim.reposted_claim_hash)) as languages,
       (select cr.has_source from claim cr where cr.claim_hash = claim.reposted_claim_hash) as reposted_has_source,
       (select cr.claim_type from claim cr where cr.claim_hash = claim.reposted_claim_hash) as reposted_claim_type,
       claim.*
FROM claim LEFT JOIN claimtrie USING (claim_hash)
WHERE claim.height % {shards_total} = {shard_num}
ORDER BY claim.height desc
""")):
        claim = dict(claim._asdict())
        claim['has_source'] = bool(claim.pop('reposted_has_source') or claim['has_source'])
        claim['censor_type'] = 0
        claim['censoring_channel_hash'] = None
        claim['tags'] = claim['tags'].split(',,') if claim['tags'] else []
        claim['languages'] = claim['languages'].split(' ') if claim['languages'] else []
        if num % 10_000 == 0:
            logging.info("%d/%d", num, total)
        yield extract_doc(claim, index_name)
        if 0 < limit <= num:
            break


async def consume(producer, index_name):
    env = Env(LBC)
    logging.info("ES sync host: %s:%i", env.elastic_host, env.elastic_port)
    es = AsyncElasticsearch([{'host': env.elastic_host, 'port': env.elastic_port}])
    try:
        await async_bulk(es, producer, request_timeout=120)
        await es.indices.refresh(index=index_name)
    finally:
        await es.close()


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


async def run(db_path, clients, blocks, shard, index_name='claims'):
    def itsbusy(*_):
        logging.info("shard %d: db is busy, retry", shard)
        return True
    db = apsw.Connection(db_path, flags=apsw.SQLITE_OPEN_READONLY | apsw.SQLITE_OPEN_URI)
    db.setbusyhandler(itsbusy)
    db.cursor().execute('pragma journal_mode=wal;')
    db.cursor().execute('pragma temp_store=memory;')

    producer = get_all(db.cursor(), shard, clients, limit=blocks, index_name=index_name)
    await asyncio.gather(*(consume(producer, index_name=index_name) for _ in range(min(8, clients))))


def __run(args, shard):
    asyncio.run(run(args.db_path, args.clients, args.blocks, shard))


def run_elastic_sync():
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('elasticsearch').setLevel(logging.WARNING)

    logging.info('lbry.server starting')
    parser = argparse.ArgumentParser(prog="lbry-hub-elastic-sync")
    parser.add_argument("db_path", type=str)
    parser.add_argument("-c", "--clients", type=int, default=16)
    parser.add_argument("-b", "--blocks", type=int, default=0)
    parser.add_argument("-f", "--force", default=False, action='store_true')
    args = parser.parse_args()
    processes = []

    if not args.force and not os.path.exists(args.db_path):
        logging.info("DB path doesnt exist")
        return

    if not args.force and not asyncio.run(make_es_index()):
        logging.info("ES is already initialized")
        return
    for i in range(args.clients):
        processes.append(Process(target=__run, args=(args, i)))
        processes[-1].start()
    for process in processes:
        process.join()
        process.close()
