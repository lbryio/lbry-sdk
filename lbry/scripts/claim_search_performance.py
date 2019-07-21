import os
import time
import argparse
import asyncio
import logging
from concurrent.futures.process import ProcessPoolExecutor
from lbry.wallet.server.db.reader import search_to_bytes, initializer
from lbry.wallet.ledger import MainNetLedger

log = logging.getLogger(__name__)

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

RARE_AND_NO_MATCH_TAGS = [
    'city fix',
    'ufosssssssssssss',
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
    any_tags_combinations = [DEFAULT_ANY_TAGS, COMMON_AND_RARE, RARE_ANY_TAGS, COMMON_AND_RARE2, CITY_FIX, RARE_AND_NO_MATCH_TAGS, []]
    not_tags_combinations = [MATURE_TAGS, []]
    for no_totals in [True]:
        for offset in [0, 100, 2000]:
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
    return args


def search(constraints):
    start = time.perf_counter()
    search_to_bytes(constraints)
    return time.perf_counter() - start, constraints


async def main(db_path, max_query_time, show_passing: bool):
    start = time.perf_counter()
    args = dict(initializer=initializer, initargs=(log, db_path, MainNetLedger, max_query_time))
    workers = max(os.cpu_count(), 4)
    query_executor = ProcessPoolExecutor(workers, **args)
    args = get_args()
    print(f"Testing {len(args)} argument combinations...")
    tasks = [asyncio.get_running_loop().run_in_executor(query_executor, search, constraints) for constraints in get_args()]
    all_passed = True
    try:
        results = await asyncio.gather(*tasks)
        for ts, constraints in sorted(results, key=lambda x: x[0]):
            if ts > max_query_time / 2.0:
                print(f"[❌] [{int(ts*1000)}ms] - {constraints}")
                all_passed = False
            elif show_passing:
                print(f"[✓] [{int(ts*1000)}ms] - {constraints}")
    finally:
        query_executor.shutdown()
    if all_passed:
        print(f"[✓] all {len(args)} test queries were fast [total duration={int(time.perf_counter() - start) * 1000}ms]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--db_path', dest='db_path', default=os.path.expanduser('~/claims.db'), type=str)
    parser.add_argument('--max_time', dest='max_time', default=0.25, type=float)
    parser.add_argument('--show_passing', dest='show_passing', action='store_true', default=False)

    args = parser.parse_args()
    db_path = args.db_path
    show_passing = args.show_passing
    max_query_time = args.max_time
    asyncio.run(main(db_path, max_query_time, show_passing))
