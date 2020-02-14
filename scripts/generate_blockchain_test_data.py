import asyncio
from lbry.blockchain import Lbrycrd


async def main():
    chain = Lbrycrd.regtest()
    print(f'Generating: {chain.data_path}')
    await chain.ensure()
    await chain.start()
    chain.subscribe()
    await chain.generate(200)
    await chain.on_block.where(lambda e: e['msg'] == 199)
    await chain.claim_name(f'foo', 'beef' * 4000, '0.001')
    await chain.generate(1)
    await chain.stop(False)

    await asyncio.sleep(3)  # give lbrycrd time to stop

    await chain.start('-reindex')
    await chain.generate(1)
    await chain.stop(False)


asyncio.run(main())
