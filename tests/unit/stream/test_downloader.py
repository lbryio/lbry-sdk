import os
import mock
import asyncio
import contextlib
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
        self.downloader = StreamDownloader(self.loop, self.client_blob_manager, self.sd_hash, 3, 3, self.client_dir)

    async def _test_transfer_stream(self, blob_count: int, mock_peer_search=None):
        await self.setup_stream(blob_count)

        mock_node = mock.Mock(spec=Node)

        @contextlib.asynccontextmanager
        async def _mock_peer_search(*_):
            async def _gen():
                yield [self.server_from_client]
                return

            yield _gen()

        mock_node.stream_peer_search_junction = mock_peer_search or _mock_peer_search

        self.downloader.download(mock_node)
        await self.downloader.stream_finished_event.wait()
        await self.downloader.stop()
        self.assertTrue(os.path.isfile(self.downloader.output_path))
        with open(self.downloader.output_path, 'rb') as f:
            self.assertEqual(f.read(), self.stream_bytes)

    async def test_transfer_stream(self):
        await self._test_transfer_stream(10)

    async def test_transfer_hundred_blob_stream(self):
        await self._test_transfer_stream(100)

    async def test_transfer_stream_bad_first_peer_good_second(self):
        await self.setup_stream(2)

        mock_node = mock.Mock(spec=Node)

        bad_peer = KademliaPeer(self.loop, "127.0.0.1", b'2' * 48, tcp_port=3334)

        @contextlib.asynccontextmanager
        async def mock_peer_search(*_):
            async def _gen():
                await asyncio.sleep(0.05, loop=self.loop)
                yield [bad_peer]
                await asyncio.sleep(0.1, loop=self.loop)
                yield [self.server_from_client]
                return

            yield _gen()

        mock_node.stream_peer_search_junction = mock_peer_search

        self.downloader.download(mock_node)
        await self.downloader.stream_finished_event.wait()
        await self.downloader.stop()
        self.assertTrue(os.path.isfile(self.downloader.output_path))
        with open(self.downloader.output_path, 'rb') as f:
            self.assertEqual(f.read(), self.stream_bytes)
        # self.assertIs(self.server_from_client.tcp_last_down, None)
        # self.assertIsNot(bad_peer.tcp_last_down, None)
