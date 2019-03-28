import os
import asyncio
import tempfile
import shutil

from torba.testcase import AsyncioTestCase
from lbrynet.conf import Config
from lbrynet.blob.blob_file import MAX_BLOB_SIZE
from lbrynet.extras.daemon.storage import SQLiteStorage
from lbrynet.blob.blob_manager import BlobManager
from lbrynet.stream.assembler import StreamAssembler
from lbrynet.stream.descriptor import StreamDescriptor
from lbrynet.stream.stream_manager import StreamManager


class TestStreamAssembler(AsyncioTestCase):
    def setUp(self):
        self.loop = asyncio.get_event_loop()
        self.key = b'deadbeef' * 4
        self.cleartext = b'test'

    async def test_create_and_decrypt_one_blob_stream(self, corrupt=False):
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp_dir))
        self.storage = SQLiteStorage(Config(), ":memory:")
        await self.storage.open()
        self.blob_manager = BlobManager(self.loop, tmp_dir, self.storage)

        download_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(download_dir))

        # create the stream
        file_path = os.path.join(tmp_dir, "test_file")
        with open(file_path, 'wb') as f:
            f.write(self.cleartext)

        sd = await StreamDescriptor.create_stream(self.loop, tmp_dir, file_path, key=self.key)

        # copy blob files
        sd_hash = sd.calculate_sd_hash()
        shutil.copy(os.path.join(tmp_dir, sd_hash), os.path.join(download_dir, sd_hash))
        for blob_info in sd.blobs:
            if blob_info.blob_hash:
                shutil.copy(os.path.join(tmp_dir, blob_info.blob_hash), os.path.join(download_dir, blob_info.blob_hash))
                if corrupt and blob_info.length == MAX_BLOB_SIZE:
                    with open(os.path.join(download_dir, blob_info.blob_hash), "rb+") as handle:
                        handle.truncate()
                        handle.flush()

        downloader_storage = SQLiteStorage(Config(), os.path.join(download_dir, "lbrynet.sqlite"))
        await downloader_storage.open()

        # add the blobs to the blob table (this would happen upon a blob download finishing)
        downloader_blob_manager = BlobManager(self.loop, download_dir, downloader_storage)
        descriptor = await downloader_blob_manager.get_stream_descriptor(sd_hash)

        # assemble the decrypted file
        assembler = StreamAssembler(self.loop, downloader_blob_manager, descriptor.sd_hash)
        await assembler.assemble_decrypted_stream(download_dir)
        if corrupt:
            return self.assertFalse(os.path.isfile(os.path.join(download_dir, "test_file")))

        with open(os.path.join(download_dir, "test_file"), "rb") as f:
            decrypted = f.read()
        self.assertEqual(decrypted, self.cleartext)
        self.assertEqual(True, self.blob_manager.get_blob(sd_hash).get_is_verified())
        self.assertEqual(True, self.blob_manager.get_blob(descriptor.blobs[0].blob_hash).get_is_verified())
        # its all blobs + sd blob - last blob, which is the same size as descriptor.blobs
        self.assertEqual(len(descriptor.blobs), len(await downloader_storage.get_all_finished_blobs()))
        self.assertEqual(
            [descriptor.sd_hash, descriptor.blobs[0].blob_hash], await downloader_storage.get_blobs_to_announce()
        )

        await downloader_storage.close()
        await self.storage.close()

    async def test_create_and_decrypt_multi_blob_stream(self):
        self.cleartext = b'test\n' * 20000000
        await self.test_create_and_decrypt_one_blob_stream()

    async def test_create_and_decrypt_padding(self):
        for i in range(16):
            self.cleartext = os.urandom((MAX_BLOB_SIZE*2) + i)
            await self.test_create_and_decrypt_one_blob_stream()

        for i in range(16):
            self.cleartext = os.urandom((MAX_BLOB_SIZE*2) - i)
            await self.test_create_and_decrypt_one_blob_stream()

    async def test_create_and_decrypt_random(self):
        self.cleartext = os.urandom(20000000)
        await self.test_create_and_decrypt_one_blob_stream()

    async def test_create_managed_stream_announces(self):
        # setup a blob manager
        storage = SQLiteStorage(Config(), ":memory:")
        await storage.open()
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp_dir))
        blob_manager = BlobManager(self.loop, tmp_dir, storage)
        stream_manager = StreamManager(self.loop, Config(), blob_manager, None, storage, None)
        # create the stream
        download_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(download_dir))
        file_path = os.path.join(download_dir, "test_file")
        with open(file_path, 'wb') as f:
            f.write(b'testtest')

        stream = await stream_manager.create_stream(file_path)
        self.assertEqual(
            [stream.sd_hash, stream.descriptor.blobs[0].blob_hash],
            await storage.get_blobs_to_announce())

    async def test_create_truncate_and_handle_stream(self):
        self.cleartext = b'potato' * 1337 * 5279
        # The purpose of this test is just to make sure it can finish even if a blob is corrupt/truncated
        await asyncio.wait_for(self.test_create_and_decrypt_one_blob_stream(corrupt=True), timeout=5)
