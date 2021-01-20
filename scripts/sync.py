import argparse
import asyncio
from collections import namedtuple

import apsw
from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk

from lbry.wallet.server.db.elastic_search import extract_doc, SearchIndex

es = AsyncElasticsearch()
INDEX = 'claims'


async def get_all(db):
    def exec_factory(cursor, statement, bindings):
        tpl = namedtuple('row', (d[0] for d in cursor.getdescription()))
        cursor.setrowtrace(lambda cursor, row: tpl(*row))
        return True

    db.setexectrace(exec_factory)
    total = db.execute("select count(*) as total from claim;").fetchone()[0]
    for num, claim in enumerate(db.execute(f"""
SELECT claimtrie.claim_hash as is_controlling,
       claimtrie.last_take_over_height,
       (select group_concat(tag, ' ') from tag where tag.claim_hash in (claim.claim_hash, claim.reposted_claim_hash)) as tags,
       (select group_concat(language, ' ') from language where language.claim_hash in (claim.claim_hash, claim.reposted_claim_hash)) as languages,
       claim.*
FROM claim LEFT JOIN claimtrie USING (claim_hash)
""")):
        claim = dict(claim._asdict())
        claim['censor_type'] = 0
        claim['censoring_channel_hash'] = None
        claim['tags'] = claim['tags'].split(' ') if claim['tags'] else []
        claim['languages'] = claim['languages'].split(' ') if claim['languages'] else []
        print(num, total)
        yield extract_doc(claim, INDEX)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("db_path", type=str)
    args = parser.parse_args()
    db = apsw.Connection(args.db_path, flags=apsw.SQLITE_OPEN_READONLY | apsw.SQLITE_OPEN_URI)
    index = SearchIndex('')
    await index.start()
    await index.stop()
    await async_bulk(es, get_all(db.cursor()))


if __name__ == '__main__':
    asyncio.run(main())
