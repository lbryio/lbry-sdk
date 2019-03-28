import asyncio
import tempfile
import shutil
import os
from torba.testcase import AsyncioTestCase
from lbrynet.conf import Config
from lbrynet.extras.daemon.storage import SQLiteStorage
from lbrynet.blob.blob_manager import BlobManager


class TestBlobManager(AsyncioTestCase):
    async def test_sync_blob_manager_on_startup(self):
        loop = asyncio.get_event_loop()
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp_dir))

        storage = SQLiteStorage(Config(), os.path.join(tmp_dir, "lbrynet.sqlite"))
        blob_manager = BlobManager(loop, tmp_dir, storage)

        # add a blob file
        blob_hash = "7f5ab2def99f0ddd008da71db3a3772135f4002b19b7605840ed1034c8955431bd7079549e65e6b2a3b9c17c773073ed"
        blob_bytes = b'1' * ((2 * 2 ** 20) - 1)
        with open(os.path.join(blob_manager.blob_dir, blob_hash), 'wb') as f:
            f.write(blob_bytes)

        # it should not have been added automatically on startup
        await storage.open()
        await blob_manager.setup()
        self.assertSetEqual(blob_manager.completed_blob_hashes, set())

        # make sure we can add the blob
        await blob_manager.blob_completed(blob_manager.get_blob(blob_hash, len(blob_bytes)))
        self.assertSetEqual(blob_manager.completed_blob_hashes, {blob_hash})

        # stop the blob manager and restart it, make sure the blob is there
        blob_manager.stop()
        self.assertSetEqual(blob_manager.completed_blob_hashes, set())
        await blob_manager.setup()
        self.assertSetEqual(blob_manager.completed_blob_hashes, {blob_hash})

        # test that the blob is removed upon the next startup after the file being manually deleted
        blob_manager.stop()

        # manually delete the blob file and restart the blob manager
        os.remove(os.path.join(blob_manager.blob_dir, blob_hash))
        await blob_manager.setup()
        self.assertSetEqual(blob_manager.completed_blob_hashes, set())

        # check that the deleted blob was updated in the database
        self.assertEqual(
            'pending', (
                await storage.run_and_return_one_or_none('select status from blob where blob_hash=?', blob_hash)
            )
        )
