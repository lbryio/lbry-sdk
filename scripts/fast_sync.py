import os.path
import asyncio
from lbry.blockchain import Lbrycrd
from lbry.blockchain.sync import BlockSync


async def main():
    chain = Lbrycrd(os.path.expanduser('~/.lbrycrd'), False)
    sync = BlockSync(chain, use_process_pool=True)
    if os.path.exists(sync.db.sync_db.db_file_path):
        os.remove(sync.db.sync_db.db_file_path)
    await sync.db.open()
    await sync.load_blocks()
    #await chain.stop(False)

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print('exiting')
