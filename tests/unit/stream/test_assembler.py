import os
import asyncio
import tempfile
import shutil
from torba.testcase import AsyncioTestCase
from lbrynet.blob.blob_manager import BlobFileManager
from lbrynet.blob.blob_file import MAX_BLOB_SIZE
from lbrynet.extras.daemon.storage import SQLiteStorage
from lbrynet.stream.descriptor import StreamDescriptor
from lbrynet.stream.assembler import StreamAssembler


class TestStreamAssembler(AsyncioTestCase):
    def setUp(self):
        self.loop = asyncio.get_event_loop()
        self.key = b'deadbeef' * 4
        self.cleartext = b'test'

    async def test_create_and_decrypt_one_blob_stream(self):
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp_dir))
        self.storage = SQLiteStorage(os.path.join(tmp_dir, "lbrynet.sqlite"))
        await self.storage.open()
        self.blob_manager = BlobFileManager(self.loop, tmp_dir, self.storage)

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
        downloader_storage = SQLiteStorage(os.path.join(download_dir, "lbrynet.sqlite"))
        await downloader_storage.open()

        # add the blobs to the blob table (this would happen upon a blob download finishing)
        downloader_blob_manager = BlobFileManager(self.loop, download_dir, downloader_storage)
        descriptor = await downloader_blob_manager.get_stream_descriptor(sd_hash)

        # assemble the decrypted file
        assembler = StreamAssembler(self.loop, downloader_blob_manager, descriptor.sd_hash)
        await assembler.assemble_decrypted_stream(download_dir)

        with open(os.path.join(download_dir, "test_file"), "rb") as f:
            decrypted = f.read()
        self.assertEqual(decrypted, self.cleartext)
        self.assertEqual(True, self.blob_manager.get_blob(sd_hash).get_is_verified())

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
