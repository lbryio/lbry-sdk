import os
import time
import argparse
import asyncio
import logging
from concurrent.futures.process import ProcessPoolExecutor
from lbry.wallet.server.db.reader import search_to_bytes, initializer, _get_claims, interpolate
from lbry.wallet.ledger import MainNetLedger

log = logging.getLogger(__name__)
log.addHandler(logging.StreamHandler())
log.setLevel(logging.INFO)

DEFAULT_ANY_TAGS = [
    'blockchain',
    'news',
    'learning',
    'technology',
    'automotive',
    'economics',
    'food',
    'science',
    'art',
    'nature'
]

COMMON_AND_RARE = [
    'gaming',
    'ufos'
]

COMMON_AND_RARE2 = [
    'city fix',
    'gaming'
]

RARE_ANY_TAGS = [
    'city fix',
    'ufos',
]

CITY_FIX = [
    'city fix'
]

MATURE_TAGS = [
    'porn',
    'nsfw',
    'mature',
    'xxx'
]

ORDER_BY = [
    [
        "trending_global",
        "trending_mixed",
    ],
    [
        "release_time"
    ],
    [
        "effective_amount"
    ]
]


def get_args(limit=20):
    args = []
    any_tags_combinations = [DEFAULT_ANY_TAGS, COMMON_AND_RARE, RARE_ANY_TAGS, COMMON_AND_RARE2, CITY_FIX, []]
    not_tags_combinations = [MATURE_TAGS, []]
    for no_totals in [True]:
        for offset in [0, 100]:
            for any_tags in any_tags_combinations:
                for not_tags in not_tags_combinations:
                    for order_by in ORDER_BY:
                        kw = {
                            'order_by': order_by,
                            'offset': offset,
                            'limit': limit,
                            'no_totals': no_totals
                        }
                        if not_tags:
                            kw['not_tags'] = not_tags
                        if any_tags:
                            kw['any_tags'] = any_tags
                        args.append(kw)
    print(len(args), "argument combinations")
    return args


def _search(kwargs):
    start = time.time()
    try:
        search_to_bytes(kwargs)
        t = time.time() - start
        return t, kwargs
    except Exception as err:
        return -1, f"failed: error={str(type(err))}({str(err)})"


async def search(executor, kwargs):
    try:
        return await asyncio.get_running_loop().run_in_executor(
            executor, _search, kwargs
        )
    except Exception as err:
        return f"failed (err={str(type(err))}({err}))- {kwargs}"


async def main(db_path, max_query_time):
    args = dict(initializer=initializer, initargs=(log, db_path, MainNetLedger, 0.25))
    workers = max(os.cpu_count(), 4)
    log.info(f"using {workers} reader processes")
    query_executor = ProcessPoolExecutor(workers, **args)
    tasks = [search(query_executor, constraints) for constraints in get_args()]
    try:
        results = await asyncio.gather(*tasks)
        for ts, constraints in results:
            if ts >= max_query_time:
                sql = interpolate(*_get_claims("""
        claimtrie.claim_hash as is_controlling,
        claimtrie.last_take_over_height,
        claim.claim_hash, claim.txo_hash,
        claim.claims_in_channel,
        claim.height, claim.creation_height,
        claim.activation_height, claim.expiration_height,
        claim.effective_amount, claim.support_amount,
        claim.trending_group, claim.trending_mixed,
        claim.trending_local, claim.trending_global,
        claim.short_url, claim.canonical_url,
        claim.channel_hash, channel.txo_hash AS channel_txo_hash,
        channel.height AS channel_height, claim.signature_valid
        """, **constraints))
                print(f"Query took {int(ts * 1000)}ms\n{sql}")
    finally:
        query_executor.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--db_path', dest='db_path', default=os.path.expanduser('~/claims.db'), type=str)
    parser.add_argument('--max_time', dest='max_time', default=0.0, type=float)
    args = parser.parse_args()
    db_path = args.db_path
    max_query_time = args.max_time
    asyncio.run(main(db_path, max_query_time))
