import asyncio
from typing import Iterable

from lbry.extras.daemon.client import daemon_rpc
from lbry.conf import Config
conf = Config()


async def sample_prefix(prefix: bytes):
    result = await daemon_rpc(conf, "claim_search", sd_hash=prefix.hex(), page_size=50)
    total_pages = result['total_pages']
    print(total_pages)
    sd_hashes = set()
    for page in range(1, total_pages + 1):
        if page > 1:
            result = await daemon_rpc(conf, "claim_search", sd_hash=prefix.hex(), page=page, page_size=50)
        for item in result['items']:
            sd_hash = item.get('value', {}).get('source', {}).get('sd_hash')
            if not sd_hash:
                print('err', item)
                continue
            sd_hashes.add(sd_hash)
        print('page', page, len(sd_hashes))
    return sd_hashes


def save_sample(name: str, samples: Iterable[str]):
    with open(name, 'wb') as outfile:
        for sample in samples:
            outfile.write(bytes.fromhex(sample))
        outfile.flush()
        print(outfile.tell())


async def main():
    samples = set()
    futs = [asyncio.ensure_future(sample_prefix(bytes([i]))) for i in range(256)]
    for i, completed in enumerate(asyncio.as_completed(futs)):
        samples.update(await completed)
        print(i, len(samples))
    print(save_sample("test.sample", samples))

if __name__ == "__main__":
    asyncio.run(main())