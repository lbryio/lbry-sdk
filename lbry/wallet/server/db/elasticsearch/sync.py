import argparse
import asyncio
import logging
import os
from collections import namedtuple
from multiprocessing import Process

import apsw
from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk

from .search import extract_doc, SearchIndex

INDEX = 'claims'


async def get_all(db, shard_num, shards_total, limit=0):
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
       claim.*
FROM claim LEFT JOIN claimtrie USING (claim_hash)
WHERE claim.height % {shards_total} = {shard_num}
ORDER BY claim.height desc
""")):
        claim = dict(claim._asdict())
        claim['censor_type'] = 0
        claim['censoring_channel_hash'] = None
        claim['tags'] = claim['tags'].split(',,') if claim['tags'] else []
        claim['languages'] = claim['languages'].split(' ') if claim['languages'] else []
        if num % 10_000 == 0:
            logging.info("%d/%d", num, total)
        yield extract_doc(claim, INDEX)
        if 0 < limit <= num:
            break


async def consume(producer):
    es = AsyncElasticsearch()
    try:
        await async_bulk(es, producer, request_timeout=120)
        await es.indices.refresh(index=INDEX)
    finally:
        await es.close()


async def make_es_index():
    index = SearchIndex('')
    try:
        return await index.start()
    finally:
        index.stop()


async def run(args, shard):
    def itsbusy(*_):
        logging.info("shard %d: db is busy, retry", shard)
        return True
    db = apsw.Connection(args.db_path, flags=apsw.SQLITE_OPEN_READONLY | apsw.SQLITE_OPEN_URI)
    db.setbusyhandler(itsbusy)
    db.cursor().execute('pragma journal_mode=wal;')
    db.cursor().execute('pragma temp_store=memory;')

    producer = get_all(db.cursor(), shard, args.clients, limit=args.blocks)
    await asyncio.gather(*(consume(producer) for _ in range(min(8, args.clients))))


def __run(args, shard):
    asyncio.run(run(args, shard))


def run_elastic_sync():
    logging.basicConfig(level=logging.INFO)
    logging.info('lbry.server starting')
    parser = argparse.ArgumentParser()
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
