import os
import time
import textwrap
import argparse
import asyncio
import logging
from concurrent.futures.process import ProcessPoolExecutor
from lbry.wallet.server.db.reader import search_to_bytes, initializer, _get_claims, interpolate
from lbry.wallet.ledger import MainNetLedger

log = logging.getLogger(__name__)
log.addHandler(logging.StreamHandler())
log.setLevel(logging.CRITICAL)

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
    for no_fee in [False, True]:
        for claim_type in [None, 'stream', 'channel']:
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
                                if claim_type:
                                    kw['claim_type'] = claim_type
                                if no_fee:
                                    kw['fee_amount'] = 0
                                args.append(kw)
    print(f"-- Trying {len(args)} argument combinations")
    return args


def _search(kwargs):
    start = time.perf_counter()
    error = None
    try:
        search_to_bytes(kwargs)
    except Exception as err:
        error = str(err)
    return time.perf_counter() - start, kwargs, error


async def search(executor, kwargs):
    return await asyncio.get_running_loop().run_in_executor(
        executor, _search, kwargs
    )


async def main(db_path, max_query_time):
    args = dict(initializer=initializer, initargs=(log, db_path, MainNetLedger, 0.25))
    workers = max(os.cpu_count(), 4)
    log.info(f"using {workers} reader processes")
    query_executor = ProcessPoolExecutor(workers, **args)
    tasks = [search(query_executor, constraints) for constraints in get_args()]
    try:
        results = await asyncio.gather(*tasks)
        query_times = [
            {
                'sql': interpolate(*_get_claims("""
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
                        """, **constraints)),
                'duration': ts,
                'error': error
            }
            for ts, constraints, error in results
        ]
        errored = [query_info for query_info in query_times if query_info['error']]
        errors = {str(query_info['error']): [] for query_info in errored}
        for error in errored:
            errors[str(error['error'])].append(error['sql'])
        slow = [
            query_info for query_info in query_times
            if not query_info['error'] and query_info['duration'] > (max_query_time / 2.0)
        ]
        fast = [
            query_info for query_info in query_times
            if not query_info['error'] and query_info['duration'] <= (max_query_time / 2.0)
        ]
        print(f"-- {len(fast)} queries were fast")
        slow.sort(key=lambda query_info: query_info['duration'], reverse=True)
        print(f"-- Failing queries:")
        for error in errors:
            print(f"-- Failure: \"{error}\"")
            for failing_query in errors[error]:
                print(f"{textwrap.dedent(failing_query)};\n")
        print()
        print(f"-- Slow queries:")
        for slow_query in slow:
            print(f"-- Query took {slow_query['duration']}\n{textwrap.dedent(slow_query['sql'])};\n")
    finally:
        query_executor.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--db_path', dest='db_path', default=os.path.expanduser('~/claims.db'), type=str)
    parser.add_argument('--max_time', dest='max_time', default=0.25, type=float)
    args = parser.parse_args()
    db_path = args.db_path
    max_query_time = args.max_time
    asyncio.run(main(db_path, max_query_time))
