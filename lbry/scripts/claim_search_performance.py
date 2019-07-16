import sys
import os
import time
import asyncio
import logging
from concurrent.futures.process import ProcessPoolExecutor
from lbry.wallet.server.db.reader import search_to_bytes, initializer
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
    any_tags_combinations = [DEFAULT_ANY_TAGS, []]
    not_tags_combinations = [MATURE_TAGS, []]
    for no_totals in [True]:
        for offset in [0, 20, 40, 60, 80, 100, 1000, 2000, 3000]:
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
    msg = f"offset={kwargs['offset']}, limit={kwargs['limit']}, no_totals={kwargs['no_totals']}, not_tags={kwargs.get('not_tags')}, any_tags={kwargs.get('any_tags')}, order_by={kwargs['order_by']}"
    try:
        search_to_bytes(kwargs)
        t = time.time() - start
        return t, f"{t} - {msg}"
    except Exception as err:
        return -1, f"failed: error={str(type(err))}({str(err)}) - {msg}"


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
        times = {msg: ts for ts, msg in results}
        log.info("\n".join(sorted(filter(lambda msg: times[msg] > max_query_time, times.keys()), key=lambda msg: times[msg])))
    finally:
        query_executor.shutdown()


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) >= 1:
        db_path = args[0]
    else:
        db_path = os.path.expanduser('~/claims.db')
    if len(args) >= 2:
        max_query_time = float(args[1])
    else:
        max_query_time = -3

    asyncio.run(main(db_path, max_query_time))
