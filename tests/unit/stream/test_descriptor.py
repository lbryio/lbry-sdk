import os
import asyncio
import tempfile
import shutil
from torba.testcase import AsyncioTestCase
from lbrynet.blob.blob_manager import BlobFileManager
from lbrynet.blob.blob_file import MAX_BLOB_SIZE
from lbrynet.storage import SQLiteStorage
from lbrynet.stream.descriptor import StreamDescriptor
from lbrynet.stream.assembler import StreamAssembler


# expected_sd_hash = "3e2706157a59aaa47ef52bc264fce488078b4026c0b9bab649a8f2fe1ecc5e5cad7182a2bb7722460f856831a1ac0f02"
#
#
# b"""{"blobs": [{"blob_hash": "6f53c72de100f6f007aa1b9720632e2d049cc6049e609ad790b556dba262159f739d5a14648d5701afc84b991254206a", "blob_num": 0, "iv": "3b6110c2d8e742bff66e4314863dee7e", "length": 2097152}, {"blob_hash": "18493bc7c5164b00596153859a0faffa45765e47a6c3f12198a4f7be4658111505b7f8a15ed0162306a0672c4a9b505d", "blob_num": 1, "iv": "df973fa64e73b4ff2677d682cdc32d3e", "length": 2097152}, {"blob_num": 2, "iv": "660d2dc2645da7c7d4540a466fcb0c60", "length": 0}], "key": "6465616462656566646561646265656664656164626565666465616462656566", "stream_hash": "22423c6786584974bd6b462af47ecb03e471da0ef372fe85a4e71a78bef7560c4afb0835c689f03916105404653b7bdf", "stream_name": "746573745f66696c65", "stream_type": "lbryfile", "suggested_file_name": "746573745f66696c65"}"""


class TestStreamDescriptor(AsyncioTestCase):
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

        sd = await StreamDescriptor.create_stream(self.loop, self.blob_manager, file_path, key=self.key)

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
