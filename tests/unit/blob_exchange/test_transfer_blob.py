import asyncio
import tempfile
from io import BytesIO

import shutil
import os

from lbrynet.blob_exchange.serialization import BlobRequest
from torba.testcase import AsyncioTestCase
from lbrynet.conf import Config
from lbrynet.extras.daemon.storage import SQLiteStorage
from lbrynet.blob.blob_manager import BlobManager
from lbrynet.blob_exchange.server import BlobServer, BlobServerProtocol
from lbrynet.blob_exchange.client import request_blob
from lbrynet.dht.peer import KademliaPeer, PeerManager

# import logging
# logging.getLogger("lbrynet").setLevel(logging.DEBUG)


def mock_config():
    config = Config()
    config.fixed_peer_delay = 10000
    return config


class BlobExchangeTestBase(AsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_event_loop()

        self.client_dir = tempfile.mkdtemp()
        self.server_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.client_dir)
        self.addCleanup(shutil.rmtree, self.server_dir)
        self.server_config = Config(data_dir=self.server_dir, download_dir=self.server_dir, wallet=self.server_dir,
                                    reflector_servers=[])
        self.server_storage = SQLiteStorage(self.server_config, os.path.join(self.server_dir, "lbrynet.sqlite"))
        self.server_blob_manager = BlobManager(self.loop, self.server_dir, self.server_storage)
        self.server = BlobServer(self.loop, self.server_blob_manager, 'bQEaw42GXsgCAGio1nxFncJSyRmnztSCjP')

        self.client_config = Config(data_dir=self.client_dir, download_dir=self.client_dir, wallet=self.client_dir,
                                    reflector_servers=[])
        self.client_storage = SQLiteStorage(self.client_config, os.path.join(self.client_dir, "lbrynet.sqlite"))
        self.client_blob_manager = BlobManager(self.loop, self.client_dir, self.client_storage)
        self.client_peer_manager = PeerManager(self.loop)
        self.server_from_client = KademliaPeer(self.loop, "127.0.0.1", b'1' * 48, tcp_port=33333)

        await self.client_storage.open()
        await self.server_storage.open()
        await self.client_blob_manager.setup()
        await self.server_blob_manager.setup()

        self.server.start_server(33333, '127.0.0.1')
        await self.server.started_listening.wait()


class TestBlobExchange(BlobExchangeTestBase):
    async def _add_blob_to_server(self, blob_hash: str, blob_bytes: bytes):
        # add the blob on the server
        server_blob = self.server_blob_manager.get_blob(blob_hash, len(blob_bytes))
        writer = server_blob.get_blob_writer()
        writer.write(blob_bytes)
        await server_blob.verified.wait()
        self.assertTrue(os.path.isfile(server_blob.file_path))
        self.assertEqual(server_blob.get_is_verified(), True)

    async def _test_transfer_blob(self, blob_hash: str):
        client_blob = self.client_blob_manager.get_blob(blob_hash)

        # download the blob
        downloaded, transport = await request_blob(self.loop, client_blob, self.server_from_client.address,
                                                   self.server_from_client.tcp_port, 2, 3)
        self.assertIsNotNone(transport)
        self.addCleanup(transport.close)
        await client_blob.verified.wait()
        self.assertEqual(client_blob.get_is_verified(), True)
        self.assertTrue(downloaded)
        self.addCleanup(client_blob.close)

    async def test_transfer_sd_blob(self):
        sd_hash = "3e2706157a59aaa47ef52bc264fce488078b4026c0b9bab649a8f2fe1ecc5e5cad7182a2bb7722460f856831a1ac0f02"
        mock_sd_blob_bytes = b"""{"blobs": [{"blob_hash": "6f53c72de100f6f007aa1b9720632e2d049cc6049e609ad790b556dba262159f739d5a14648d5701afc84b991254206a", "blob_num": 0, "iv": "3b6110c2d8e742bff66e4314863dee7e", "length": 2097152}, {"blob_hash": "18493bc7c5164b00596153859a0faffa45765e47a6c3f12198a4f7be4658111505b7f8a15ed0162306a0672c4a9b505d", "blob_num": 1, "iv": "df973fa64e73b4ff2677d682cdc32d3e", "length": 2097152}, {"blob_num": 2, "iv": "660d2dc2645da7c7d4540a466fcb0c60", "length": 0}], "key": "6465616462656566646561646265656664656164626565666465616462656566", "stream_hash": "22423c6786584974bd6b462af47ecb03e471da0ef372fe85a4e71a78bef7560c4afb0835c689f03916105404653b7bdf", "stream_name": "746573745f66696c65", "stream_type": "lbryfile", "suggested_file_name": "746573745f66696c65"}"""
        await self._add_blob_to_server(sd_hash, mock_sd_blob_bytes)
        return await self._test_transfer_blob(sd_hash)

    async def test_transfer_blob(self):
        blob_hash = "7f5ab2def99f0ddd008da71db3a3772135f4002b19b7605840ed1034c8955431bd7079549e65e6b2a3b9c17c773073ed"
        mock_blob_bytes = b'1' * ((2 * 2 ** 20) - 1)
        await self._add_blob_to_server(blob_hash, mock_blob_bytes)
        return await self._test_transfer_blob(blob_hash)

    async def test_host_same_blob_to_multiple_peers_at_once(self):
        blob_hash = "7f5ab2def99f0ddd008da71db3a3772135f4002b19b7605840ed1034c8955431bd7079549e65e6b2a3b9c17c773073ed"
        mock_blob_bytes = b'1' * ((2 * 2 ** 20) - 1)

        second_client_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, second_client_dir)

        second_client_storage = SQLiteStorage(Config(), os.path.join(second_client_dir, "lbrynet.sqlite"))
        second_client_blob_manager = BlobManager(self.loop, second_client_dir, second_client_storage)
        server_from_second_client = KademliaPeer(self.loop, "127.0.0.1", b'1' * 48, tcp_port=33333)

        await second_client_storage.open()
        await second_client_blob_manager.setup()

        await self._add_blob_to_server(blob_hash, mock_blob_bytes)

        second_client_blob = self.client_blob_manager.get_blob(blob_hash)

        # download the blob
        await asyncio.gather(
            request_blob(
                self.loop, second_client_blob, server_from_second_client.address,
                server_from_second_client.tcp_port, 2, 3
            ),
            self._test_transfer_blob(blob_hash)
        )
        await second_client_blob.verified.wait()
        self.assertEqual(second_client_blob.get_is_verified(), True)

    async def test_host_different_blobs_to_multiple_peers_at_once(self):
        blob_hash = "7f5ab2def99f0ddd008da71db3a3772135f4002b19b7605840ed1034c8955431bd7079549e65e6b2a3b9c17c773073ed"
        mock_blob_bytes = b'1' * ((2 * 2 ** 20) - 1)

        sd_hash = "3e2706157a59aaa47ef52bc264fce488078b4026c0b9bab649a8f2fe1ecc5e5cad7182a2bb7722460f856831a1ac0f02"
        mock_sd_blob_bytes = b"""{"blobs": [{"blob_hash": "6f53c72de100f6f007aa1b9720632e2d049cc6049e609ad790b556dba262159f739d5a14648d5701afc84b991254206a", "blob_num": 0, "iv": "3b6110c2d8e742bff66e4314863dee7e", "length": 2097152}, {"blob_hash": "18493bc7c5164b00596153859a0faffa45765e47a6c3f12198a4f7be4658111505b7f8a15ed0162306a0672c4a9b505d", "blob_num": 1, "iv": "df973fa64e73b4ff2677d682cdc32d3e", "length": 2097152}, {"blob_num": 2, "iv": "660d2dc2645da7c7d4540a466fcb0c60", "length": 0}], "key": "6465616462656566646561646265656664656164626565666465616462656566", "stream_hash": "22423c6786584974bd6b462af47ecb03e471da0ef372fe85a4e71a78bef7560c4afb0835c689f03916105404653b7bdf", "stream_name": "746573745f66696c65", "stream_type": "lbryfile", "suggested_file_name": "746573745f66696c65"}"""

        second_client_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, second_client_dir)

        second_client_storage = SQLiteStorage(Config(), os.path.join(second_client_dir, "lbrynet.sqlite"))
        second_client_blob_manager = BlobManager(self.loop, second_client_dir, second_client_storage)
        server_from_second_client = KademliaPeer(self.loop, "127.0.0.1", b'1' * 48, tcp_port=33333)

        await second_client_storage.open()
        await second_client_blob_manager.setup()

        await self._add_blob_to_server(blob_hash, mock_blob_bytes)
        await self._add_blob_to_server(sd_hash, mock_sd_blob_bytes)

        second_client_blob = self.client_blob_manager.get_blob(blob_hash)

        await asyncio.gather(
            request_blob(
                self.loop, second_client_blob, server_from_second_client.address,
                server_from_second_client.tcp_port, 2, 3
            ),
            self._test_transfer_blob(sd_hash),
            second_client_blob.verified.wait()
        )
        self.assertEqual(second_client_blob.get_is_verified(), True)

    async def test_server_chunked_request(self):
        blob_hash = "7f5ab2def99f0ddd008da71db3a3772135f4002b19b7605840ed1034c8955431bd7079549e65e6b2a3b9c17c773073ed"
        server_protocol = BlobServerProtocol(self.loop, self.server_blob_manager, self.server.lbrycrd_address)
        transport = asyncio.Transport(extra={'peername': ('ip', 90)})
        received_data = BytesIO()
        transport.write = received_data.write
        server_protocol.connection_made(transport)
        blob_request = BlobRequest.make_request_for_blob_hash(blob_hash).serialize()
        for byte in blob_request:
            server_protocol.data_received(bytes([byte]))
        await asyncio.sleep(0.1)  # yield execution
        self.assertTrue(len(received_data.getvalue()) > 0)
