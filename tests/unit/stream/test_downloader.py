import os
import unittest
from unittest import mock
import asyncio
from lbrynet.conf import Config
from lbrynet.stream.descriptor import StreamDescriptor
from lbrynet.stream.downloader import StreamDownloader
from lbrynet.dht.node import Node
from lbrynet.dht.peer import KademliaPeer
from lbrynet.blob.blob_file import MAX_BLOB_SIZE
from tests.unit.blob_exchange.test_transfer_blob import BlobExchangeTestBase


class TestStreamDownloader(BlobExchangeTestBase):
    async def setup_stream(self, blob_count: int = 10):
        self.stream_bytes = b''
        for _ in range(blob_count):
            self.stream_bytes += os.urandom((MAX_BLOB_SIZE - 1))
        # create the stream
        file_path = os.path.join(self.server_dir, "test_file")
        with open(file_path, 'wb') as f:
            f.write(self.stream_bytes)
        descriptor = await StreamDescriptor.create_stream(self.loop, self.server_blob_manager.blob_dir, file_path)
        self.sd_hash = descriptor.calculate_sd_hash()
        conf = Config(data_dir=self.server_dir, wallet_dir=self.server_dir, download_dir=self.server_dir,
                      reflector_servers=[])
        self.downloader = StreamDownloader(self.loop, conf, self.client_blob_manager, self.sd_hash)

    async def _test_transfer_stream(self, blob_count: int, mock_accumulate_peers=None):
        await self.setup_stream(blob_count)
        mock_node = mock.Mock(spec=Node)

        def _mock_accumulate_peers(q1, q2):
            async def _task():
                pass
            q2.put_nowait([self.server_from_client])
            return q2, self.loop.create_task(_task())

        mock_node.accumulate_peers = mock_accumulate_peers or _mock_accumulate_peers

        self.downloader.download(mock_node)
        await self.downloader.stream_finished_event.wait()
        self.downloader.stop()
        self.assertTrue(os.path.isfile(self.downloader.output_path))
        with open(self.downloader.output_path, 'rb') as f:
            self.assertEqual(f.read(), self.stream_bytes)
        await asyncio.sleep(0.01)
        self.assertTrue(self.downloader.stream_handle.closed)

    async def test_transfer_stream(self):
        await self._test_transfer_stream(10)

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

        self.downloader.download(mock_node)
        await self.downloader.stream_finished_event.wait()
        self.assertTrue(os.path.isfile(self.downloader.output_path))
        with open(self.downloader.output_path, 'rb') as f:
            self.assertEqual(f.read(), self.stream_bytes)
        # self.assertIs(self.server_from_client.tcp_last_down, None)
        # self.assertIsNot(bad_peer.tcp_last_down, None)
