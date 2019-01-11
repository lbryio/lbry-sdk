import os
import random
import asyncio
import tempfile
import shutil
import mock
import contextlib
from torba.testcase import AsyncioTestCase
from lbrynet.blob.blob_manager import BlobFileManager
from lbrynet.storage import SQLiteStorage
from lbrynet.stream.descriptor import StreamDescriptor
from lbrynet.blob_exchange.server import BlobServer
from lbrynet.peer import PeerManager
from lbrynet.stream.downloader import StreamDownloader
from lbrynet.dht.node import Node


def iv_gen():
    while True:
        yield b'1' * 16


class TestStreamDownloader(AsyncioTestCase):
    async def test_transfer_stream(self):
        key = b'deadbeef' * 4
        loop = asyncio.get_event_loop()
        client_dir = tempfile.mkdtemp()
        server_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(client_dir))
        self.addCleanup(lambda: shutil.rmtree(server_dir))
        client_storage = SQLiteStorage(os.path.join(client_dir, "lbrynet.sqlite"))
        server_storage = SQLiteStorage(os.path.join(server_dir, "lbrynet.sqlite"))
        client_blob_manager = BlobFileManager(loop, client_dir, client_storage)
        server_blob_manager = BlobFileManager(loop, server_dir, server_storage)
        server = BlobServer(loop, server_blob_manager, 'bQEaw42GXsgCAGio1nxFncJSyRmnztSCjP')
        client_peer_manager = PeerManager(loop)
        server_from_client = client_peer_manager.make_peer("127.0.0.1", b'1' * 48, tcp_port=3333)

        await client_storage.open()
        await server_storage.open()
        await client_blob_manager.setup()
        await server_blob_manager.setup()

        rnd = random.Random(9393)
        stream_bytes = b''
        stream_size = 1000
        for _ in range(stream_size):
            stream_bytes += bytes(rnd.getrandbits(8))
        print(len(stream_bytes))
        # create the stream
        file_path = os.path.join(server_dir, "test_file")
        with open(file_path, 'wb') as f:
            f.write(stream_bytes)

        descriptor = await StreamDescriptor.create_stream(
            self.loop, server_blob_manager, file_path, key=key, iv_generator=iv_gen()
        )
        server.start_server(3333, '127.0.0.1')
        await server.started_listening.wait()
        sd_hash = descriptor.calculate_sd_hash()
        downloader = StreamDownloader(loop, client_blob_manager, sd_hash, 3, 3, client_dir)
        mock_node = mock.Mock(spec=Node)

        @contextlib.asynccontextmanager
        async def mock_peer_search(*_):
            async def _gen():
                yield [server_from_client]
                return
            yield _gen()

        mock_node.peer_search_junction = mock_peer_search
        downloader.download(mock_node)
        await downloader.stream_finished_event.wait()
        self.assertTrue(os.path.isfile(downloader.output_path))
        with open(downloader.output_path, 'rb') as f:
            self.assertEqual(f.read(), stream_bytes)
