import os
import asyncio
import tempfile
import shutil
from lbry.testcase import AsyncioTestCase
from lbry.conf import Config
from lbry.extras.daemon.storage import SQLiteStorage
from lbry.blob.blob_manager import BlobManager
from lbry.stream.stream_manager import StreamManager
from lbry.stream.reflector.server import ReflectorServer


class TestReflector(AsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_event_loop()
        self.key = b'deadbeef' * 4
        self.cleartext = os.urandom(20000000)

        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp_dir))
        self.conf = Config()
        self.storage = SQLiteStorage(self.conf, os.path.join(tmp_dir, "lbrynet.sqlite"))
        await self.storage.open()
        self.blob_manager = BlobManager(self.loop, tmp_dir, self.storage, self.conf)
        self.addCleanup(self.blob_manager.stop)
        self.stream_manager = StreamManager(self.loop, Config(), self.blob_manager, None, self.storage, None)

        server_tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(server_tmp_dir))
        self.server_conf = Config()
        self.server_storage = SQLiteStorage(self.server_conf, os.path.join(server_tmp_dir, "lbrynet.sqlite"))
        await self.server_storage.open()
        self.server_blob_manager = BlobManager(self.loop, server_tmp_dir, self.server_storage, self.server_conf)
        self.addCleanup(self.server_blob_manager.stop)

        download_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(download_dir))

        # create the stream
        file_path = os.path.join(tmp_dir, "test_file")
        with open(file_path, 'wb') as f:
            f.write(self.cleartext)
        self.stream_manager.config.reflect_streams = False
        self.stream = await self.stream_manager.create(file_path)

    async def _test_reflect_stream(self, response_chunk_size=50, partial_needs=False):
        reflector = ReflectorServer(self.server_blob_manager, response_chunk_size=response_chunk_size,
                                    partial_needs=partial_needs)
        reflector.start_server(5566, '127.0.0.1')
        if partial_needs:
            server_blob = self.server_blob_manager.get_blob(self.stream.sd_hash)
            client_blob = self.blob_manager.get_blob(self.stream.sd_hash)
            with client_blob.reader_context() as handle:
                server_blob.set_length(client_blob.get_length())
                writer = server_blob.get_blob_writer('nobody', 0)
                writer.write(handle.read())
            self.server_blob_manager.blob_completed(server_blob)
        await reflector.started_listening.wait()
        self.addCleanup(reflector.stop_server)
        self.assertEqual(0, self.stream.reflector_progress)
        sent = await self.stream.upload_to_reflector('127.0.0.1', 5566)
        self.assertEqual(100, self.stream.reflector_progress)
        if partial_needs:
            self.assertFalse(self.stream.is_fully_reflected)
            send_more = await self.stream.upload_to_reflector('127.0.0.1', 5566)
            self.assertGreater(len(send_more), 0)
            sent.extend(send_more)
            sent.append(self.stream.sd_hash)
        self.assertSetEqual(
            set(sent),
            set(map(lambda b: b.blob_hash,
                    self.stream.descriptor.blobs[:-1] + [self.blob_manager.get_blob(self.stream.sd_hash)]))
        )
        send_more = await self.stream.upload_to_reflector('127.0.0.1', 5566)
        self.assertEqual(len(send_more), 0)
        self.assertTrue(self.stream.is_fully_reflected)
        server_sd_blob = self.server_blob_manager.get_blob(self.stream.sd_hash)
        self.assertTrue(server_sd_blob.get_is_verified())
        self.assertEqual(server_sd_blob.length, server_sd_blob.length)
        for blob in self.stream.descriptor.blobs[:-1]:
            server_blob = self.server_blob_manager.get_blob(blob.blob_hash)
            self.assertTrue(server_blob.get_is_verified())
            self.assertEqual(server_blob.length, blob.length)

        sent = await self.stream.upload_to_reflector('127.0.0.1', 5566)
        self.assertListEqual(sent, [])

    async def test_reflect_stream(self):
        return await asyncio.wait_for(self._test_reflect_stream(response_chunk_size=50), 3, loop=self.loop)

    async def test_reflect_stream_but_reflector_changes_its_mind(self):
        return await asyncio.wait_for(self._test_reflect_stream(partial_needs=True), 3, loop=self.loop)

    async def test_reflect_stream_small_response_chunks(self):
        return await asyncio.wait_for(self._test_reflect_stream(response_chunk_size=30), 3, loop=self.loop)

    async def test_announces(self):
        to_announce = await self.storage.get_blobs_to_announce()
        self.assertIn(self.stream.sd_hash, to_announce, "sd blob not set to announce")
        self.assertIn(self.stream.descriptor.blobs[0].blob_hash, to_announce, "head blob not set to announce")

    async def test_result_from_disconnect_mid_sd_transfer(self):
        stop = asyncio.Event()
        incoming = asyncio.Event()
        reflector = ReflectorServer(
            self.server_blob_manager, response_chunk_size=50, stop_event=stop, incoming_event=incoming
        )
        reflector.start_server(5566, '127.0.0.1')
        await reflector.started_listening.wait()
        self.addCleanup(reflector.stop_server)
        self.assertEqual(0, self.stream.reflector_progress)
        reflect_task = asyncio.create_task(self.stream.upload_to_reflector('127.0.0.1', 5566))
        await incoming.wait()
        stop.set()
        # this used to raise (and then propagate) a CancelledError
        self.assertListEqual(await reflect_task, [])
        self.assertFalse(self.stream.is_fully_reflected)
        self.assertFalse(self.server_blob_manager.get_blob(self.stream.sd_hash).get_is_verified())

    async def test_result_from_disconnect_after_sd_transfer(self):
        stop = asyncio.Event()
        incoming = asyncio.Event()
        not_incoming = asyncio.Event()
        reflector = ReflectorServer(
            self.server_blob_manager, response_chunk_size=50, stop_event=stop, incoming_event=incoming,
            not_incoming_event=not_incoming
        )
        reflector.start_server(5566, '127.0.0.1')
        await reflector.started_listening.wait()
        self.addCleanup(reflector.stop_server)
        self.assertEqual(0, self.stream.reflector_progress)
        reflect_task = asyncio.create_task(self.stream.upload_to_reflector('127.0.0.1', 5566))
        await incoming.wait()
        await not_incoming.wait()
        stop.set()
        sent = await reflect_task
        self.assertListEqual([self.stream.sd_hash], sent)
        self.assertTrue(self.server_blob_manager.get_blob(self.stream.sd_hash).get_is_verified())
        self.assertFalse(self.stream.is_fully_reflected)

    async def test_result_from_disconnect_after_data_transfer(self):
        stop = asyncio.Event()
        incoming = asyncio.Event()
        not_incoming = asyncio.Event()
        reflector = ReflectorServer(
            self.server_blob_manager, response_chunk_size=50, stop_event=stop, incoming_event=incoming,
            not_incoming_event=not_incoming
        )
        reflector.start_server(5566, '127.0.0.1')
        await reflector.started_listening.wait()
        self.addCleanup(reflector.stop_server)
        self.assertEqual(0, self.stream.reflector_progress)
        reflect_task = asyncio.create_task(self.stream.upload_to_reflector('127.0.0.1', 5566))
        await incoming.wait()
        await not_incoming.wait()
        await incoming.wait()
        await not_incoming.wait()
        stop.set()
        sent = await reflect_task
        self.assertListEqual([self.stream.sd_hash, self.stream.descriptor.blobs[0].blob_hash], sent)
        self.assertTrue(self.server_blob_manager.get_blob(self.stream.sd_hash).get_is_verified())
        self.assertTrue(self.server_blob_manager.get_blob(self.stream.descriptor.blobs[0].blob_hash).get_is_verified())
        self.assertFalse(self.stream.is_fully_reflected)

    async def test_result_from_disconnect_mid_data_transfer(self):
        stop = asyncio.Event()
        incoming = asyncio.Event()
        not_incoming = asyncio.Event()
        reflector = ReflectorServer(
            self.server_blob_manager, response_chunk_size=50, stop_event=stop, incoming_event=incoming,
            not_incoming_event=not_incoming
        )
        reflector.start_server(5566, '127.0.0.1')
        await reflector.started_listening.wait()
        self.addCleanup(reflector.stop_server)
        self.assertEqual(0, self.stream.reflector_progress)
        reflect_task = asyncio.create_task(self.stream.upload_to_reflector('127.0.0.1', 5566))
        await incoming.wait()
        await not_incoming.wait()
        await incoming.wait()
        stop.set()
        self.assertListEqual(await reflect_task, [self.stream.sd_hash])
        self.assertTrue(self.server_blob_manager.get_blob(self.stream.sd_hash).get_is_verified())
        self.assertFalse(
            self.server_blob_manager.get_blob(self.stream.descriptor.blobs[0].blob_hash).get_is_verified()
        )
        self.assertFalse(self.stream.is_fully_reflected)

    async def test_delete_file_during_reflector_upload(self):
        stop = asyncio.Event()
        incoming = asyncio.Event()
        not_incoming = asyncio.Event()
        reflector = ReflectorServer(
            self.server_blob_manager, response_chunk_size=50, stop_event=stop, incoming_event=incoming,
            not_incoming_event=not_incoming
        )
        reflector.start_server(5566, '127.0.0.1')
        await reflector.started_listening.wait()
        self.addCleanup(reflector.stop_server)
        self.assertEqual(0, self.stream.reflector_progress)
        reflect_task = asyncio.create_task(self.stream.upload_to_reflector('127.0.0.1', 5566))
        await incoming.wait()
        await not_incoming.wait()
        await incoming.wait()
        await self.stream_manager.delete(self.stream, delete_file=True)
        # this used to raise OSError when it can't read the deleted blob for the upload
        sent = await reflect_task
        self.assertListEqual([self.stream.sd_hash], sent)
        self.assertTrue(self.server_blob_manager.get_blob(self.stream.sd_hash).get_is_verified())
        self.assertFalse(
            self.server_blob_manager.get_blob(self.stream.descriptor.blobs[0].blob_hash).get_is_verified()
        )
        self.assertFalse(self.stream.is_fully_reflected)
