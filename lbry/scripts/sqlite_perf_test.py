import uvloop, asyncio, time, sys, logging
from concurrent.futures import ProcessPoolExecutor
from lbry.wallet.server.db import reader


db_path = '/tmp/wallet-server/claims.db'
default_query_timout  = 0.25
log = logging.getLogger(__name__)
log.addHandler(logging.StreamHandler())


async def run_times(executor, iterations, show=True):
    start = time.perf_counter()
    timings = await asyncio.gather(*(asyncio.get_running_loop().run_in_executor(
        executor, reader.search_to_bytes, {
            'no_totals': True,
            'offset': 0,
            'limit': 20,
            'fee_amount': '<1',
            #'all_tags': ['funny'],
            'any_tags': [
                'crypto',
                'outdoors',
                'cars',
                'automotive'
            ],
            'not_tags': [
                'nsfw', 'xxx', 'mature'
            ]
        }
    ) for _ in range(iterations)))
    timings = [r[1]['execute_query']['total'] for r in timings]
    total = int((time.perf_counter() - start) * 100)
    if show:
        avg = sum(timings)/len(timings)
        print(f"{iterations:4}: {total}ms total concurrent, {len(timings)*avg*1000:.3f}s total sequential (avg*runs)")
        print(f"      {total/len(timings):.1f}ms/query concurrent (total/runs)")
        print(f"      {avg:.1f}ms/query actual average (sum(queries)/runs)")
        sys.stdout.write('      sample:')
        for i, t in zip(range(10), timings[::-1]):
            sys.stdout.write(f' {t}ms')
        print(' ...\n' if len(timings) > 10 else '\n')


async def main():
    executor = ProcessPoolExecutor(
        4, initializer=reader.initializer, initargs=(log, db_path, 'mainnet', default_query_timout, True)
    )
    await run_times(executor, 4, show=False)
    await run_times(executor, 1)
    await run_times(executor, 2**3)
    await run_times(executor, 2**5)
    await run_times(executor, 2**7)
    await run_times(executor, 2**9)
    await run_times(executor, 2**11)
    await run_times(executor, 2**13)
    executor.shutdown(True)

if __name__ == '__main__':
    uvloop.install()
    asyncio.run(main())
