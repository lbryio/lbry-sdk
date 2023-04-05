import os
import asyncio
import tempfile
import shutil
import json

from lbry.blob.blob_file import BlobFile
from lbry.testcase import AsyncioTestCase
from lbry.conf import Config
from lbry.error import InvalidStreamDescriptorError
from lbry.extras.daemon.storage import SQLiteStorage
from lbry.blob.blob_manager import BlobManager
from lbry.stream.descriptor import StreamDescriptor, sanitize_file_name


class TestStreamDescriptor(AsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_event_loop()
        self.key = b'deadbeef' * 4
        self.cleartext = os.urandom(20000000)
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp_dir))
        self.conf = Config()
        self.storage = SQLiteStorage(self.conf, ":memory:")
        await self.storage.open()
        self.blob_manager = BlobManager(self.loop, self.tmp_dir, self.storage, self.conf)

        self.file_path = os.path.join(self.tmp_dir, "test_file")
        with open(self.file_path, 'wb') as f:
            f.write(self.cleartext)

        self.descriptor = await StreamDescriptor.create_stream(self.loop, self.blob_manager, self.file_path, key=self.key)
        self.sd_hash = self.descriptor.calculate_sd_hash()
        self.sd_dict = json.loads(self.descriptor.as_json())

    def _write_sd(self):
        with open(os.path.join(self.tmp_dir, self.sd_hash), 'wb') as f:
            f.write(json.dumps(self.sd_dict, sort_keys=True).encode())

    async def _test_invalid_sd(self):
        self._write_sd()
        with self.assertRaises(InvalidStreamDescriptorError):
            await self.blob_manager.get_stream_descriptor(self.sd_hash)

    async def test_load_sd_blob(self):
        self._write_sd()
        descriptor = await self.blob_manager.get_stream_descriptor(self.sd_hash)
        self.assertEqual(descriptor.calculate_sd_hash(), self.sd_hash)

    async def test_missing_terminator(self):
        self.sd_dict['blobs'].pop()
        await self._test_invalid_sd()

    async def test_terminator_not_at_end(self):
        terminator = self.sd_dict['blobs'].pop()
        self.sd_dict['blobs'] = [terminator] + self.sd_dict['blobs']
        await self._test_invalid_sd()

    async def test_terminator_has_blob_hash(self):
        self.sd_dict['blobs'][-1]['blob_hash'] = '1' * 96
        await self._test_invalid_sd()

    async def test_blob_order(self):
        terminator = self.sd_dict['blobs'].pop()
        self.sd_dict['blobs'].reverse()
        self.sd_dict['blobs'].append(terminator)
        await self._test_invalid_sd()

    async def test_skip_blobs(self):
        self.sd_dict['blobs'][-2]['blob_num'] = self.sd_dict['blobs'][-2]['blob_num'] + 1
        await self._test_invalid_sd()

    async def test_invalid_stream_hash(self):
        self.sd_dict['blobs'][-2]['blob_hash'] = '1' * 96
        await self._test_invalid_sd()

    async def test_zero_length_blob(self):
        self.sd_dict['blobs'][-2]['length'] = 0
        await self._test_invalid_sd()

    def test_sanitize_file_name(self):
        self.assertEqual(sanitize_file_name(' t/-?t|.g.ext '), 't-t.g.ext')
        self.assertEqual(sanitize_file_name('end_dot .'), 'end_dot')
        self.assertEqual(sanitize_file_name('.file\0\0'), '.file')
        self.assertEqual(sanitize_file_name('test n\16ame.ext'), 'test name.ext')
        self.assertEqual(sanitize_file_name('COM8.ext', default_file_name='default1'), 'default1.ext')
        self.assertEqual(sanitize_file_name('LPT2', default_file_name='default2'), 'default2')
        self.assertEqual(sanitize_file_name('', default_file_name=''), '')


class TestRecoverOldStreamDescriptors(AsyncioTestCase):
    async def test_old_key_sort_sd_blob(self):
        loop = asyncio.get_event_loop()
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp_dir))
        self.conf = Config()
        storage = SQLiteStorage(self.conf, ":memory:")
        await storage.open()
        blob_manager = BlobManager(loop, tmp_dir, storage, self.conf)

        sd_bytes = b'{"stream_name": "4f62616d6120446f6e6b65792d322e73746c", "blobs": [{"length": 1153488, "blob_num' \
                   b'": 0, "blob_hash": "9fa32a249ce3f2d4e46b78599800f368b72f2a7f22b81df443c7f6bdbef496bd61b4c0079c7' \
                   b'3d79c8bb9be9a6bf86592", "iv": "0bf348867244019c9e22196339016ea6"}, {"length": 0, "blob_num": 1,' \
                   b' "iv": "9f36abae16955463919b07ed530a3d18"}], "stream_type": "lbryfile", "key": "a03742b87628aa7' \
                   b'228e48f1dcd207e48", "suggested_file_name": "4f62616d6120446f6e6b65792d322e73746c", "stream_hash' \
                   b'": "b43f4b1379780caf60d20aa06ac38fb144df61e514ebfa97537018ba73bce8fe37ae712f473ff0ba0be0eef44e1' \
                   b'60207"}'
        sd_hash = '9313d1807551186126acc3662e74d9de29cede78d4f133349ace846273ef116b9bb86be86c54509eb84840e4b032f6b2'
        stream_hash = 'b43f4b1379780caf60d20aa06ac38fb144df61e514ebfa97537018ba73bce8fe37ae712f473ff0ba0be0eef44e160207'

        blob = blob_manager.get_blob(sd_hash)
        blob.set_length(len(sd_bytes))
        writer = blob.get_blob_writer()
        writer.write(sd_bytes)
        await blob.verified.wait()
        descriptor = await StreamDescriptor.from_stream_descriptor_blob(
            loop, blob_manager, blob
        )
        self.assertEqual(stream_hash, descriptor.get_stream_hash())
        self.assertEqual(sd_hash, descriptor.calculate_old_sort_sd_hash())
        self.assertNotEqual(sd_hash, descriptor.calculate_sd_hash())

    async def test_decode_corrupt_blob_raises_proper_exception_and_deletes_corrupt_file(self):
        loop = asyncio.get_event_loop()
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp_dir))
        self.conf = Config()
        storage = SQLiteStorage(self.conf, ":memory:")
        await storage.open()
        blob_manager = BlobManager(loop, tmp_dir, storage, self.conf)

        sd_hash = '9313d1807551186126acc3662e74d9de29cede78d4f133349ace846273ef116b9bb86be86c54509eb84840e4b032f6b2'
        with open(os.path.join(tmp_dir, sd_hash), 'wb') as handle:
            handle.write(b'doesnt work')
        blob = BlobFile(loop, sd_hash, blob_manager=blob_manager)
        self.assertTrue(blob.file_exists)
        self.assertIsNotNone(blob.length)
        with self.assertRaises(InvalidStreamDescriptorError):
            await StreamDescriptor.from_stream_descriptor_blob(
                loop, tmp_dir, blob
            )
        self.assertFalse(blob.file_exists)
        # fixme: this is an emergency PR, please move this to blob_file tests later
        self.assertIsNone(blob.length)
