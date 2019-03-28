import asyncio
import tempfile
import shutil
import os
from torba.testcase import AsyncioTestCase
from lbrynet.conf import Config
from lbrynet.extras.daemon.storage import SQLiteStorage
from lbrynet.blob.blob_manager import BlobManager


class TestBlobfile(AsyncioTestCase):
    async def test_create_blob(self):
        blob_hash = "7f5ab2def99f0ddd008da71db3a3772135f4002b19b7605840ed1034c8955431bd7079549e65e6b2a3b9c17c773073ed"
        blob_bytes = b'1' * ((2 * 2 ** 20) - 1)

        loop = asyncio.get_event_loop()
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp_dir))

        storage = SQLiteStorage(Config(), os.path.join(tmp_dir, "lbrynet.sqlite"))
        blob_manager = BlobManager(loop, tmp_dir, storage)

        await storage.open()
        await blob_manager.setup()

        # add the blob on the server
        blob = blob_manager.get_blob(blob_hash, len(blob_bytes))
        self.assertEqual(blob.get_is_verified(), False)
        self.assertNotIn(blob_hash, blob_manager.completed_blob_hashes)

        writer = blob.open_for_writing()
        writer.write(blob_bytes)
        await blob.finished_writing.wait()
        self.assertTrue(os.path.isfile(blob.file_path), True)
        self.assertEqual(blob.get_is_verified(), True)
        self.assertIn(blob_hash, blob_manager.completed_blob_hashes)
