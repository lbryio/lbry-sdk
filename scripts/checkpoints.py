import asyncio
import os

from lbry.extras.cli import ensure_directory_exists
from lbry.conf import Config
from lbry.wallet.header import Headers
import lbry.wallet.checkpoints


async def main():
    outpath = lbry.wallet.checkpoints.__file__
    ledger_path = os.path.join(Config().wallet_dir, 'lbc_mainnet')
    ensure_directory_exists(ledger_path)
    headers_path = os.path.join(ledger_path, 'headers')
    headers = Headers(headers_path)
    await headers.open()
    print(f"Working on headers at {outpath}")
    print("Verifying integrity, might take a while.")
    await headers.repair()
    target = ((headers.height - 100) // 1000) * 1000
    current_checkpoint_tip = max(lbry.wallet.checkpoints.HASHES.keys())
    if target <= current_checkpoint_tip:
        print(f"We have nothing to add: Local: {target}, checkpoint: {current_checkpoint_tip}")
        return
    print(f"Headers file at {headers.height}, checkpointing up to {target}."
          f"Current checkpoint at {current_checkpoint_tip}.")
    with open(outpath, 'w') as outfile:
        print('HASHES = {', file=outfile)
        for height in range(0, target, 1000):
            print(f"    {height}: '{headers.chunk_hash(height, 1000)}',", file=outfile)
        print('}', file=outfile)


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
