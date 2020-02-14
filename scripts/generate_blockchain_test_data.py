import asyncio
from lbry.blockchain import Lbrycrd


async def main():
    chain = Lbrycrd.regtest()
    print(f'Generating: {chain.data_path}')
    await chain.ensure()
    await chain.start()
    await chain.generate(200)
    step = 10
    for block in range(200):
        for i in range(0, 200, step):
            print(f'claim-{block}-{i}-{i + step}')
            await asyncio.gather(*(
                chain.claim_name(f'claim-{block}-{i + tx}', 'beef' * 4000, '0.001')
                for tx in range(1, step + 1)
            ))
        await chain.generate(5)
    print('done!')


asyncio.run(main())
