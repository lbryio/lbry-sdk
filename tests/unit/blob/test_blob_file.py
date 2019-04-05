import asyncio
import tempfile
import shutil
import os
from torba.testcase import AsyncioTestCase
from lbrynet.error import InvalidDataError, InvalidBlobHashError
from lbrynet.conf import Config
from lbrynet.extras.daemon.storage import SQLiteStorage
from lbrynet.blob.blob_manager import BlobManager
from lbrynet.blob.blob_file import BlobFile, BlobBuffer, AbstractBlob


class TestBlob(AsyncioTestCase):
    blob_hash = "7f5ab2def99f0ddd008da71db3a3772135f4002b19b7605840ed1034c8955431bd7079549e65e6b2a3b9c17c773073ed"
    blob_bytes = b'1' * ((2 * 2 ** 20) - 1)

    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()

    def _get_blob(self, blob_class=AbstractBlob, blob_directory=None):
        blob = blob_class(self.loop, self.blob_hash, len(self.blob_bytes), blob_directory=blob_directory)
        self.assertFalse(blob.get_is_verified())
        self.addCleanup(blob.close)
        return blob

    async def _test_create_blob(self, blob_class=AbstractBlob, blob_directory=None):
        blob = self._get_blob(blob_class, blob_directory)
        writer = blob.get_blob_writer()
        writer.write(self.blob_bytes)
        await blob.verified.wait()
        self.assertTrue(blob.get_is_verified())
        return blob

    async def _test_close_writers_on_finished(self, blob_class=AbstractBlob, blob_directory=None):
        blob = self._get_blob(blob_class, blob_directory=blob_directory)
        writers = [blob.get_blob_writer() for _ in range(5)]
        self.assertEqual(5, len(blob.writers))

        # test that writing too much causes the writer to fail with InvalidDataError and to be removed
        with self.assertRaises(InvalidDataError):
            writers[1].write(self.blob_bytes * 2)
            await writers[1].finished
        await asyncio.sleep(0, loop=self.loop)
        self.assertEqual(4, len(blob.writers))

        # write the blob
        other = writers[2]
        writers[3].write(self.blob_bytes)
        await blob.verified.wait()

        self.assertTrue(blob.get_is_verified())
        self.assertEqual(0, len(blob.writers))
        with self.assertRaises(IOError):
            other.write(self.blob_bytes)

    def _test_ioerror_if_length_not_set(self, blob_class=AbstractBlob, blob_directory=None):
        blob = blob_class(self.loop, self.blob_hash, blob_directory=blob_directory)
        self.addCleanup(blob.close)
        writer = blob.get_blob_writer()
        with self.assertRaises(IOError):
            writer.write(b'')

    async def _test_invalid_blob_bytes(self, blob_class=AbstractBlob, blob_directory=None):
        blob = blob_class(self.loop, self.blob_hash, len(self.blob_bytes), blob_directory=blob_directory)
        self.addCleanup(blob.close)
        writer = blob.get_blob_writer()
        writer.write(self.blob_bytes[:-4] + b'fake')
        with self.assertRaises(InvalidBlobHashError):
            await writer.finished

    async def test_invalid_blob_bytes(self):
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp_dir))
        await self._test_invalid_blob_bytes(BlobBuffer)
        await self._test_invalid_blob_bytes(BlobFile, tmp_dir)

    def test_ioerror_if_length_not_set(self):
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp_dir))
        self._test_ioerror_if_length_not_set(BlobBuffer)
        self._test_ioerror_if_length_not_set(BlobFile, tmp_dir)

    async def test_create_blob_file(self):
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp_dir))
        blob = await self._test_create_blob(BlobFile, tmp_dir)
        self.assertIsInstance(blob, BlobFile)
        self.assertTrue(os.path.isfile(blob.file_path))

        for _ in range(2):
            with blob.reader_context() as reader:
                self.assertEqual(self.blob_bytes, reader.read())

    async def test_create_blob_buffer(self):
        blob = await self._test_create_blob(BlobBuffer)
        self.assertIsInstance(blob, BlobBuffer)
        self.assertIsNotNone(blob._verified_bytes)

        # check we can only read the bytes once, and that the buffer is torn down
        with blob.reader_context() as reader:
            self.assertEqual(self.blob_bytes, reader.read())
        self.assertIsNone(blob._verified_bytes)
        with self.assertRaises(OSError):
            with blob.reader_context() as reader:
                self.assertEqual(self.blob_bytes, reader.read())
        self.assertIsNone(blob._verified_bytes)

    async def test_close_writers_on_finished(self):
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp_dir))
        await self._test_close_writers_on_finished(BlobBuffer)
        await self._test_close_writers_on_finished(BlobFile, tmp_dir)

    async def test_delete(self):
        blob_buffer = await self._test_create_blob(BlobBuffer)
        self.assertIsNotNone(blob_buffer._verified_bytes)
        self.assertTrue(blob_buffer.get_is_verified())
        blob_buffer.delete()
        self.assertIsNone(blob_buffer._verified_bytes)
        self.assertFalse(blob_buffer.get_is_verified())

        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp_dir))

        blob_file = await self._test_create_blob(BlobFile, tmp_dir)
        self.assertTrue(os.path.isfile(blob_file.file_path))
        self.assertTrue(blob_file.get_is_verified())
        blob_file.delete()
        self.assertFalse(os.path.isfile(blob_file.file_path))
        self.assertFalse(blob_file.get_is_verified())

    async def test_delete_corrupt(self):
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp_dir))
        blob = BlobFile(self.loop, self.blob_hash, len(self.blob_bytes), blob_directory=tmp_dir)
        writer = blob.get_blob_writer()
        writer.write(self.blob_bytes)
        await blob.verified.wait()
        blob.close()
        blob = BlobFile(self.loop, self.blob_hash, len(self.blob_bytes), blob_directory=tmp_dir)
        self.assertTrue(blob.get_is_verified())

        with open(blob.file_path, 'wb+') as f:
            f.write(b'\x00')
        blob = BlobFile(self.loop, self.blob_hash, len(self.blob_bytes), blob_directory=tmp_dir)
        self.assertFalse(blob.get_is_verified())
        self.assertFalse(os.path.isfile(blob.file_path))

    def test_invalid_blob_hash(self):
        self.assertRaises(InvalidBlobHashError, BlobBuffer, self.loop, '', len(self.blob_bytes))
        self.assertRaises(InvalidBlobHashError, BlobBuffer, self.loop, 'x' * 96, len(self.blob_bytes))
        self.assertRaises(InvalidBlobHashError, BlobBuffer, self.loop, 'a' * 97, len(self.blob_bytes))

    async def _test_close_reader(self, blob_class=AbstractBlob, blob_directory=None):
        blob = await self._test_create_blob(blob_class, blob_directory)
        reader = blob.reader_context()
        self.assertEqual(0, len(blob.readers))

        async def read_blob_buffer():
            with reader as read_handle:
                self.assertEqual(1, len(blob.readers))
                await asyncio.sleep(2, loop=self.loop)
                self.assertEqual(0, len(blob.readers))
                return read_handle.read()

        self.loop.call_later(1, blob.close)
        with self.assertRaises(ValueError) as err:
            read_task = self.loop.create_task(read_blob_buffer())
            await read_task
            self.assertEqual(err.exception, ValueError("I/O operation on closed file"))

    async def test_close_reader(self):
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp_dir))
        await self._test_close_reader(BlobBuffer)
        await self._test_close_reader(BlobFile, tmp_dir)
