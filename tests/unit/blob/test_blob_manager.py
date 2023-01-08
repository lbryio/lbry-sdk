import tempfile
import shutil
import os
from lbry.testcase import AsyncioTestCase
from lbry.conf import Config
from lbry.extras.daemon.storage import SQLiteStorage
from lbry.blob.blob_manager import BlobManager


class TestBlobManager(AsyncioTestCase):
    async def setup_blob_manager(self, save_blobs=True):
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp_dir))
        self.config = Config(save_blobs=save_blobs)
        self.storage = SQLiteStorage(self.config, os.path.join(tmp_dir, "lbrynet.sqlite"))
        self.blob_manager = BlobManager(self.loop, tmp_dir, self.storage, self.config)
        await self.storage.open()

    async def test_memory_blobs_arent_verified_but_real_ones_are(self):
        for save_blobs in (False, True):
            await self.setup_blob_manager(save_blobs=save_blobs)
            # add a blob file
            blob_hash = "7f5ab2def99f0ddd008da71db3a3772135f4002b19b7605840ed1034c8955431bd7079549e65e6b2a3b9c17c773073ed"
            blob_bytes = b'1' * ((2 * 2 ** 20) - 1)
            blob = self.blob_manager.get_blob(blob_hash, len(blob_bytes))
            blob.save_verified_blob(blob_bytes)
            await blob.verified.wait()
            self.assertTrue(blob.get_is_verified())
            self.blob_manager.blob_completed(blob)
            self.assertEqual(self.blob_manager.is_blob_verified(blob_hash), save_blobs)

    async def test_sync_blob_file_manager_on_startup(self):
        await self.setup_blob_manager(save_blobs=True)

        # add a blob file
        blob_hash = "7f5ab2def99f0ddd008da71db3a3772135f4002b19b7605840ed1034c8955431bd7079549e65e6b2a3b9c17c773073ed"
        blob_bytes = b'1' * ((2 * 2 ** 20) - 1)
        with open(os.path.join(self.blob_manager._blob_dir(blob_hash)[0], blob_hash), 'wb') as f:
            f.write(blob_bytes)

        # it should not have been added automatically on startup

        await self.blob_manager.setup()
        self.assertSetEqual(self.blob_manager.completed_blob_hashes, set())

        # make sure we can add the blob
        await self.blob_manager.blob_completed(self.blob_manager.get_blob(blob_hash, len(blob_bytes)))
        self.assertSetEqual(self.blob_manager.completed_blob_hashes, {blob_hash})

        # stop the blob manager and restart it, make sure the blob is there
        self.blob_manager.stop()
        self.assertSetEqual(self.blob_manager.completed_blob_hashes, set())
        await self.blob_manager.setup()
        self.assertSetEqual(self.blob_manager.completed_blob_hashes, {blob_hash})

        # test that the blob is removed upon the next startup after the file being manually deleted
        self.blob_manager.stop()

        # manually delete the blob file and restart the blob manager
        os.remove(os.path.join(self.blob_manager._blob_dir(blob_hash)[0], blob_hash))
        await self.blob_manager.setup()
        self.assertSetEqual(self.blob_manager.completed_blob_hashes, set())

        # check that the deleted blob was updated in the database
        self.assertEqual(
            'pending', (
                await self.storage.run_and_return_one_or_none('select status from blob where blob_hash=?', blob_hash)
            )
        )
