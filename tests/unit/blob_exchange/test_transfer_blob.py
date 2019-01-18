import asyncio
import tempfile
import shutil
import os
from torba.testcase import AsyncioTestCase
from lbrynet.storage import SQLiteStorage
from lbrynet.blob.blob_manager import BlobFileManager
from lbrynet.blob_exchange.server import BlobServer
from lbrynet.blob_exchange.client import BlobExchangeClientProtocol, request_blob
from lbrynet.dht.peer import KademliaPeer, PeerManager

# import logging
# logging.getLogger("lbrynet").setLevel(logging.DEBUG)


class BlobExchangeTestBase(AsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_event_loop()

        self.client_dir = tempfile.mkdtemp()
        self.server_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.client_dir)
        self.addCleanup(shutil.rmtree, self.server_dir)

        self.server_storage = SQLiteStorage(os.path.join(self.server_dir, "lbrynet.sqlite"))
        self.server_blob_manager = BlobFileManager(self.loop, self.server_dir, self.server_storage)
        self.server = BlobServer(self.loop, self.server_blob_manager, 'bQEaw42GXsgCAGio1nxFncJSyRmnztSCjP')

        self.client_storage = SQLiteStorage(os.path.join(self.client_dir, "lbrynet.sqlite"))
        self.client_blob_manager = BlobFileManager(self.loop, self.client_dir, self.client_storage)
        self.client_peer_manager = PeerManager(self.loop)
        self.server_from_client = KademliaPeer(self.loop, "127.0.0.1", b'1' * 48, tcp_port=33333)

        await self.client_storage.open()
        await self.server_storage.open()
        await self.client_blob_manager.setup()
        await self.server_blob_manager.setup()

        self.server.start_server(33333, '127.0.0.1')
        await self.server.started_listening.wait()


class TestBlobExchange(BlobExchangeTestBase):
    async def _test_transfer_blob(self, blob_hash: str, blob_bytes: bytes):
        # add the blob on the server
        server_blob = self.server_blob_manager.get_blob(blob_hash, len(blob_bytes))
        writer = server_blob.open_for_writing()
        writer.write(blob_bytes)
        await server_blob.finished_writing.wait()
        self.assertTrue(os.path.isfile(server_blob.file_path))
        self.assertEqual(server_blob.get_is_verified(), True)

        client_blob = self.client_blob_manager.get_blob(blob_hash)
        protocol = BlobExchangeClientProtocol(self.loop, 2)

        # download the blob
        downloaded = await request_blob(self.loop, client_blob, protocol, self.server_from_client.address,
                                        self.server_from_client.tcp_port, 2)
        await protocol.close()
        self.assertEqual(client_blob.get_is_verified(), True)
        self.assertTrue(downloaded)

    async def test_transfer_sd_blob(self):
        sd_hash = "3e2706157a59aaa47ef52bc264fce488078b4026c0b9bab649a8f2fe1ecc5e5cad7182a2bb7722460f856831a1ac0f02"
        mock_sd_blob_bytes = b"""{"blobs": [{"blob_hash": "6f53c72de100f6f007aa1b9720632e2d049cc6049e609ad790b556dba262159f739d5a14648d5701afc84b991254206a", "blob_num": 0, "iv": "3b6110c2d8e742bff66e4314863dee7e", "length": 2097152}, {"blob_hash": "18493bc7c5164b00596153859a0faffa45765e47a6c3f12198a4f7be4658111505b7f8a15ed0162306a0672c4a9b505d", "blob_num": 1, "iv": "df973fa64e73b4ff2677d682cdc32d3e", "length": 2097152}, {"blob_num": 2, "iv": "660d2dc2645da7c7d4540a466fcb0c60", "length": 0}], "key": "6465616462656566646561646265656664656164626565666465616462656566", "stream_hash": "22423c6786584974bd6b462af47ecb03e471da0ef372fe85a4e71a78bef7560c4afb0835c689f03916105404653b7bdf", "stream_name": "746573745f66696c65", "stream_type": "lbryfile", "suggested_file_name": "746573745f66696c65"}"""
        return await self._test_transfer_blob(sd_hash, mock_sd_blob_bytes)

    async def test_transfer_blob(self):
        blob_hash = "7f5ab2def99f0ddd008da71db3a3772135f4002b19b7605840ed1034c8955431bd7079549e65e6b2a3b9c17c773073ed"
        mock_blob_bytes = b'1' * ((2 * 2 ** 20) - 1)
        return await self._test_transfer_blob(blob_hash, mock_blob_bytes)
