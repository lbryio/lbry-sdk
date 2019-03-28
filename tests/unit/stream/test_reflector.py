import os
import asyncio
import tempfile
import shutil
from torba.testcase import AsyncioTestCase
from lbrynet.conf import Config
from lbrynet.extras.daemon.storage import SQLiteStorage
from lbrynet.blob.blob_manager import BlobManager
from lbrynet.stream.stream_manager import StreamManager
from lbrynet.stream.reflector.server import ReflectorServer


class TestStreamAssembler(AsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_event_loop()
        self.key = b'deadbeef' * 4
        self.cleartext = os.urandom(20000000)

        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp_dir))
        self.storage = SQLiteStorage(Config(), os.path.join(tmp_dir, "lbrynet.sqlite"))
        await self.storage.open()
        self.blob_manager = BlobManager(self.loop, tmp_dir, self.storage)
        self.stream_manager = StreamManager(self.loop, Config(), self.blob_manager, None, self.storage, None)

        server_tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(server_tmp_dir))
        self.server_storage = SQLiteStorage(Config(), os.path.join(server_tmp_dir, "lbrynet.sqlite"))
        await self.server_storage.open()
        self.server_blob_manager = BlobManager(self.loop, server_tmp_dir, self.server_storage)

        download_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(download_dir))

        # create the stream
        file_path = os.path.join(tmp_dir, "test_file")
        with open(file_path, 'wb') as f:
            f.write(self.cleartext)

        self.stream = await self.stream_manager.create_stream(file_path)

    async def test_reflect_stream(self):
        reflector = ReflectorServer(self.server_blob_manager)
        reflector.start_server(5566, '127.0.0.1')
        await reflector.started_listening.wait()
        self.addCleanup(reflector.stop_server)
        sent = await self.stream.upload_to_reflector('127.0.0.1', 5566)
        self.assertSetEqual(
            set(sent),
            set(map(lambda b: b.blob_hash,
                    self.stream.descriptor.blobs[:-1] + [self.blob_manager.get_blob(self.stream.sd_hash)]))
        )
        server_sd_blob = self.server_blob_manager.get_blob(self.stream.sd_hash)
        self.assertTrue(server_sd_blob.get_is_verified())
        self.assertEqual(server_sd_blob.length, server_sd_blob.length)
        for blob in self.stream.descriptor.blobs[:-1]:
            server_blob = self.server_blob_manager.get_blob(blob.blob_hash)
            self.assertTrue(server_blob.get_is_verified())
            self.assertEqual(server_blob.length, blob.length)

        sent = await self.stream.upload_to_reflector('127.0.0.1', 5566)
        self.assertListEqual(sent, [])
