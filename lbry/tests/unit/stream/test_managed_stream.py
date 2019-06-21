import os
import shutil
import unittest
from unittest import mock
import asyncio
from lbry.blob.blob_file import MAX_BLOB_SIZE
from lbry.blob_exchange.serialization import BlobResponse
from lbry.blob_exchange.server import BlobServerProtocol
from lbry.dht.node import Node
from lbry.dht.peer import KademliaPeer
from lbry.extras.daemon.storage import StoredStreamClaim
from lbry.stream.managed_stream import ManagedStream
from lbry.stream.descriptor import StreamDescriptor
from tests.unit.blob_exchange.test_transfer_blob import BlobExchangeTestBase


def get_mock_node(loop):
    mock_node = mock.Mock(spec=Node)
    mock_node.joined = asyncio.Event(loop=loop)
    mock_node.joined.set()
    return mock_node


class TestManagedStream(BlobExchangeTestBase):
    async def create_stream(self, blob_count: int = 10):
        self.stream_bytes = b''
        for _ in range(blob_count):
            self.stream_bytes += os.urandom((MAX_BLOB_SIZE - 1))
        # create the stream
        file_path = os.path.join(self.server_dir, "test_file")
        with open(file_path, 'wb') as f:
            f.write(self.stream_bytes)
        descriptor = await StreamDescriptor.create_stream(self.loop, self.server_blob_manager.blob_dir, file_path)
        self.sd_hash = descriptor.calculate_sd_hash()
        return descriptor

    async def setup_stream(self, blob_count: int = 10):
        await self.create_stream(blob_count)
        self.stream = ManagedStream(
            self.loop, self.client_config, self.client_blob_manager, self.sd_hash, self.client_dir
        )

    async def _test_transfer_stream(self, blob_count: int, mock_accumulate_peers=None, stop_when_done=True):
        await self.setup_stream(blob_count)
        mock_node = mock.Mock(spec=Node)

        def _mock_accumulate_peers(q1, q2):
            async def _task():
                pass
            q2.put_nowait([self.server_from_client])
            return q2, self.loop.create_task(_task())

        mock_node.accumulate_peers = mock_accumulate_peers or _mock_accumulate_peers
        await self.stream.save_file(node=mock_node)
        await self.stream.finished_writing.wait()
        self.assertTrue(os.path.isfile(self.stream.full_path))
        if stop_when_done:
            await self.stream.stop()
        self.assertTrue(os.path.isfile(self.stream.full_path))
        with open(self.stream.full_path, 'rb') as f:
            self.assertEqual(f.read(), self.stream_bytes)
        await asyncio.sleep(0.01)

    async def test_transfer_stream(self):
        await self._test_transfer_stream(10)
        self.assertEqual(self.stream.status, "finished")
        self.assertFalse(self.stream._running.is_set())

    async def test_delayed_stop(self):
        await self._test_transfer_stream(10, stop_when_done=False)
        self.assertEqual(self.stream.status, "finished")
        self.assertTrue(self.stream._running.is_set())
        await asyncio.sleep(0.5, loop=self.loop)
        self.assertTrue(self.stream._running.is_set())
        await asyncio.sleep(2, loop=self.loop)
        self.assertEqual(self.stream.status, "finished")
        self.assertFalse(self.stream._running.is_set())

    @unittest.SkipTest
    async def test_transfer_hundred_blob_stream(self):
        await self._test_transfer_stream(100)

    async def test_transfer_stream_bad_first_peer_good_second(self):
        await self.setup_stream(2)

        mock_node = mock.Mock(spec=Node)
        q = asyncio.Queue()

        bad_peer = KademliaPeer(self.loop, "127.0.0.1", b'2' * 48, tcp_port=3334)

        def _mock_accumulate_peers(q1, q2):
            async def _task():
                pass

            q2.put_nowait([bad_peer])
            self.loop.call_later(1, q2.put_nowait, [self.server_from_client])
            return q2, self.loop.create_task(_task())

        mock_node.accumulate_peers = _mock_accumulate_peers

        await self.stream.save_file(node=mock_node)
        await self.stream.finished_writing.wait()
        self.assertTrue(os.path.isfile(self.stream.full_path))
        with open(self.stream.full_path, 'rb') as f:
            self.assertEqual(f.read(), self.stream_bytes)
        await self.stream.stop()
        # self.assertIs(self.server_from_client.tcp_last_down, None)
        # self.assertIsNot(bad_peer.tcp_last_down, None)

    async def test_client_chunked_response(self):
        self.server.stop_server()

        class ChunkedServerProtocol(BlobServerProtocol):
            def send_response(self, responses):
                to_send = []
                while responses:
                    to_send.append(responses.pop())
                for byte in BlobResponse(to_send).serialize():
                    self.transport.write(bytes([byte]))
        self.server.server_protocol_class = ChunkedServerProtocol
        self.server.start_server(33333, '127.0.0.1')
        self.assertEqual(0, len(self.client_blob_manager.completed_blob_hashes))
        await asyncio.wait_for(self._test_transfer_stream(10), timeout=2)
        self.assertEqual(11, len(self.client_blob_manager.completed_blob_hashes))

    async def test_create_and_decrypt_one_blob_stream(self, blobs=1, corrupt=False):
        descriptor = await self.create_stream(blobs)

        # copy blob files
        shutil.copy(os.path.join(self.server_blob_manager.blob_dir, self.sd_hash),
                    os.path.join(self.client_blob_manager.blob_dir, self.sd_hash))
        self.stream = ManagedStream(self.loop, self.client_config, self.client_blob_manager, self.sd_hash,
                                    self.client_dir)

        for blob_info in descriptor.blobs[:-1]:
            shutil.copy(os.path.join(self.server_blob_manager.blob_dir, blob_info.blob_hash),
                        os.path.join(self.client_blob_manager.blob_dir, blob_info.blob_hash))
            if corrupt and blob_info.length == MAX_BLOB_SIZE:
                with open(os.path.join(self.client_blob_manager.blob_dir, blob_info.blob_hash), "rb+") as handle:
                    handle.truncate()
                    handle.flush()
        await self.stream.save_file()
        await self.stream.finished_writing.wait()
        if corrupt:
            return self.assertFalse(os.path.isfile(os.path.join(self.client_dir, "test_file")))

        with open(os.path.join(self.client_dir, "test_file"), "rb") as f:
            decrypted = f.read()
        self.assertEqual(decrypted, self.stream_bytes)

        self.assertEqual(True, self.client_blob_manager.get_blob(self.sd_hash).get_is_verified())
        self.assertEqual(
            True, self.client_blob_manager.get_blob(self.stream.descriptor.blobs[0].blob_hash).get_is_verified()
        )
        #
        # # its all blobs + sd blob - last blob, which is the same size as descriptor.blobs
        # self.assertEqual(len(descriptor.blobs), len(await downloader_storage.get_all_finished_blobs()))
        # self.assertEqual(
        #     [descriptor.sd_hash, descriptor.blobs[0].blob_hash], await downloader_storage.get_blobs_to_announce()
        # )
        #
        # await downloader_storage.close()
        # await self.storage.close()

    async def test_create_and_decrypt_multi_blob_stream(self):
        await self.test_create_and_decrypt_one_blob_stream(10)

    # async def test_create_truncate_and_handle_stream(self):
    #     # The purpose of this test is just to make sure it can finish even if a blob is corrupt/truncated
    #     await asyncio.wait_for(self.test_create_and_decrypt_one_blob_stream(corrupt=True), timeout=5)
