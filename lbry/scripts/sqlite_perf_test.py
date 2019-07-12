import uvloop, asyncio, sqlite3, time, sys
from concurrent.futures import ProcessPoolExecutor
from contextvars import ContextVar


db_path = '/tmp/wallet-server/claims.db'
db = ContextVar('db')


def init():
    conn = sqlite3.connect(db_path)
    db.set(conn)


def reader():
    conn = db.get()
    start = time.time()
    conn.execute("""
        SELECT 
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
        FROM claim
            LEFT JOIN claimtrie USING (claim_hash)
            LEFT JOIN claim as channel ON (claim.channel_hash=channel.claim_hash)
        WHERE 
            EXISTS(
                SELECT 1 FROM tag WHERE claim.claim_hash=tag.claim_hash
                AND tag IN ('alexandria ocasio-cortez', 'Alien', 'alt news', 'art', 'audio',
                'automotive', 'beliefs', 'blockchain', 'dog grooming', 'economics', 'food',
                'learning', 'mature', 'nature', 'news', 'physics', 'science', 'technology')
            )
            AND NOT EXISTS(
                SELECT 1 FROM tag WHERE claim.claim_hash=tag.claim_hash AND tag IN ('nsfw', 'xxx', 'mature')
            )
        ORDER BY claim.height DESC, claim.normalized ASC
        LIMIT 20 OFFSET 100
    """).fetchall()
    elapsed = time.time() - start
    return elapsed


async def run_times(executor, iterations, show=True):
    start = time.time()
    timings = await asyncio.gather(*(
        asyncio.get_running_loop().run_in_executor(executor, reader) for _ in range(iterations)
    ))
    total = time.time() - start
    if show:
        avg = sum(timings)/len(timings)
        print(f"{iterations:4}: {total:.5f}ms total concurrent, {len(timings)*avg:.5f}ms total sequential (avg*runs)")
        print(f"      {total/len(timings):.5f}ms/query concurrent (total/runs)")
        print(f"      {avg:.5f}ms/query actual average (sum(queries)/runs)")
        sys.stdout.write('      sample:')
        for i, t in zip(range(10), timings[::-1]):
            sys.stdout.write(f' {t:.5f}ms')
        print(' ...\n' if len(timings) > 10 else '\n')


async def main():
    executor = ProcessPoolExecutor(4, initializer=init)
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
