import asyncio
import tempfile
from io import BytesIO
from unittest import mock

import shutil
import os
import copy

from lbry.blob_exchange.serialization import BlobRequest
from lbry.testcase import AsyncioTestCase
from lbry.conf import Config
from lbry.extras.daemon.storage import SQLiteStorage
from lbry.extras.daemon.daemon import Daemon
from lbry.blob.blob_manager import BlobManager
from lbry.blob_exchange.server import BlobServer, BlobServerProtocol
from lbry.blob_exchange.client import request_blob
from lbry.dht.peer import PeerManager, make_kademlia_peer
from lbry.dht.node import Node

# import logging
# logging.getLogger("lbry").setLevel(logging.DEBUG)


def mock_config():
    config = Config(save_files=True)
    config.fixed_peer_delay = 10000
    return config


class BlobExchangeTestBase(AsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_event_loop()
        self.client_wallet_dir = tempfile.mkdtemp()
        self.client_dir = tempfile.mkdtemp()
        self.server_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.client_wallet_dir)
        self.addCleanup(shutil.rmtree, self.client_dir)
        self.addCleanup(shutil.rmtree, self.server_dir)
        self.server_config = Config(
            data_dir=self.server_dir,
            download_dir=self.server_dir,
            wallet=self.server_dir,
            save_files=True,
            fixed_peers=[]
        )
        self.server_config.transaction_cache_size = 10000
        self.server_storage = SQLiteStorage(self.server_config, os.path.join(self.server_dir, "lbrynet.sqlite"))
        self.server_blob_manager = BlobManager(self.loop, self.server_dir, self.server_storage, self.server_config)
        self.server = BlobServer(self.loop, self.server_blob_manager, 'bQEaw42GXsgCAGio1nxFncJSyRmnztSCjP')

        self.client_config = Config(
            data_dir=self.client_dir,
            download_dir=self.client_dir,
            wallet=self.client_wallet_dir,
            save_files=True,
            fixed_peers=[],
            tracker_servers=[]
        )
        self.client_config.transaction_cache_size = 10000
        self.client_storage = SQLiteStorage(self.client_config, os.path.join(self.client_dir, "lbrynet.sqlite"))
        self.client_blob_manager = BlobManager(self.loop, self.client_dir, self.client_storage, self.client_config)
        self.client_peer_manager = PeerManager(self.loop)
        self.server_from_client = make_kademlia_peer(b'1' * 48, "127.0.0.1", tcp_port=33333, allow_localhost=True)

        await self.client_storage.open()
        await self.server_storage.open()
        await self.client_blob_manager.setup()
        await self.server_blob_manager.setup()

        self.server.start_server(33333, '127.0.0.1')
        self.addCleanup(self.server.stop_server)
        await self.server.started_listening.wait()


class TestBlobExchange(BlobExchangeTestBase):
    async def _add_blob_to_server(self, blob_hash: str, blob_bytes: bytes):
        # add the blob on the server
        server_blob = self.server_blob_manager.get_blob(blob_hash, len(blob_bytes))
        writer = server_blob.get_blob_writer()
        writer.write(blob_bytes)
        await server_blob.verified.wait()
        self.assertTrue(os.path.isfile(server_blob.file_path))
        self.assertTrue(server_blob.get_is_verified())
        self.assertTrue(writer.closed())

    async def _test_transfer_blob(self, blob_hash: str):
        client_blob = self.client_blob_manager.get_blob(blob_hash)

        # download the blob
        downloaded, transport = await request_blob(self.loop, client_blob, self.server_from_client.address,
                                                   self.server_from_client.tcp_port, 2, 3)
        self.assertIsNotNone(transport)
        self.addCleanup(transport.close)
        await client_blob.verified.wait()
        self.assertTrue(client_blob.get_is_verified())
        self.assertTrue(downloaded)
        client_blob.close()

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
        second_client_conf = Config(save_files=True)
        second_client_storage = SQLiteStorage(second_client_conf, os.path.join(second_client_dir, "lbrynet.sqlite"))
        second_client_blob_manager = BlobManager(
            self.loop, second_client_dir, second_client_storage, second_client_conf
        )
        server_from_second_client = make_kademlia_peer(b'1' * 48, "127.0.0.1", tcp_port=33333, allow_localhost=True)

        await second_client_storage.open()
        await second_client_blob_manager.setup()

        await self._add_blob_to_server(blob_hash, mock_blob_bytes)

        second_client_blob = second_client_blob_manager.get_blob(blob_hash)

        # download the blob
        await asyncio.gather(
            request_blob(
                self.loop, second_client_blob, server_from_second_client.address,
                server_from_second_client.tcp_port, 2, 3
            ),
            self._test_transfer_blob(blob_hash)
        )
        await second_client_blob.verified.wait()
        self.assertTrue(second_client_blob.get_is_verified())

    async def test_blob_writers_concurrency(self):
        blob_hash = "7f5ab2def99f0ddd008da71db3a3772135f4002b19b7605840ed1034c8955431bd7079549e65e6b2a3b9c17c773073ed"
        mock_blob_bytes = b'1' * ((2 * 2 ** 20) - 1)
        blob = self.server_blob_manager.get_blob(blob_hash)
        write_blob = blob._write_blob
        write_called_count = 0

        async def _wrap_write_blob(blob_bytes):
            nonlocal write_called_count
            write_called_count += 1
            await write_blob(blob_bytes)

        def wrap_write_blob(blob_bytes):
            return asyncio.create_task(_wrap_write_blob(blob_bytes))

        blob._write_blob = wrap_write_blob

        writer1 = blob.get_blob_writer(peer_port=1)
        writer2 = blob.get_blob_writer(peer_port=2)
        reader1_ctx_before_write = blob.reader_context()

        with self.assertRaises(OSError):
            blob.get_blob_writer(peer_port=2)
        with self.assertRaises(OSError):
            with blob.reader_context():
                pass

        blob.set_length(len(mock_blob_bytes))
        results = {}

        def check_finished_callback(writer, num):
            def inner(writer_future: asyncio.Future):
                results[num] = writer_future.result()
            writer.finished.add_done_callback(inner)

        check_finished_callback(writer1, 1)
        check_finished_callback(writer2, 2)

        def write_task(writer):
            async def _inner():
                writer.write(mock_blob_bytes)
            return self.loop.create_task(_inner())

        await asyncio.gather(write_task(writer1), write_task(writer2), loop=self.loop)

        self.assertDictEqual({1: mock_blob_bytes, 2: mock_blob_bytes}, results)
        self.assertEqual(1, write_called_count)
        await blob.verified.wait()
        self.assertTrue(blob.get_is_verified())
        self.assertDictEqual({}, blob.writers)

        with reader1_ctx_before_write as f:
            self.assertEqual(mock_blob_bytes, f.read())
        with blob.reader_context() as f:
            self.assertEqual(mock_blob_bytes, f.read())
        with blob.reader_context() as f:
            blob.close()
            with self.assertRaises(ValueError):
                f.read()
        self.assertListEqual([], blob.readers)

    async def test_host_different_blobs_to_multiple_peers_at_once(self):
        blob_hash = "7f5ab2def99f0ddd008da71db3a3772135f4002b19b7605840ed1034c8955431bd7079549e65e6b2a3b9c17c773073ed"
        mock_blob_bytes = b'1' * ((2 * 2 ** 20) - 1)

        sd_hash = "3e2706157a59aaa47ef52bc264fce488078b4026c0b9bab649a8f2fe1ecc5e5cad7182a2bb7722460f856831a1ac0f02"
        mock_sd_blob_bytes = b"""{"blobs": [{"blob_hash": "6f53c72de100f6f007aa1b9720632e2d049cc6049e609ad790b556dba262159f739d5a14648d5701afc84b991254206a", "blob_num": 0, "iv": "3b6110c2d8e742bff66e4314863dee7e", "length": 2097152}, {"blob_hash": "18493bc7c5164b00596153859a0faffa45765e47a6c3f12198a4f7be4658111505b7f8a15ed0162306a0672c4a9b505d", "blob_num": 1, "iv": "df973fa64e73b4ff2677d682cdc32d3e", "length": 2097152}, {"blob_num": 2, "iv": "660d2dc2645da7c7d4540a466fcb0c60", "length": 0}], "key": "6465616462656566646561646265656664656164626565666465616462656566", "stream_hash": "22423c6786584974bd6b462af47ecb03e471da0ef372fe85a4e71a78bef7560c4afb0835c689f03916105404653b7bdf", "stream_name": "746573745f66696c65", "stream_type": "lbryfile", "suggested_file_name": "746573745f66696c65"}"""

        second_client_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, second_client_dir)
        second_client_conf = Config(save_files=True)

        second_client_storage = SQLiteStorage(second_client_conf, os.path.join(second_client_dir, "lbrynet.sqlite"))
        second_client_blob_manager = BlobManager(
            self.loop, second_client_dir, second_client_storage, second_client_conf
        )
        server_from_second_client = make_kademlia_peer(b'1' * 48, "127.0.0.1", tcp_port=33333, allow_localhost=True)

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
        self.assertTrue(second_client_blob.get_is_verified())

    async def test_server_chunked_request(self):
        blob_hash = "7f5ab2def99f0ddd008da71db3a3772135f4002b19b7605840ed1034c8955431bd7079549e65e6b2a3b9c17c773073ed"
        server_protocol = BlobServerProtocol(self.loop, self.server_blob_manager, self.server.lbrycrd_address)
        transport = mock.Mock(spec=asyncio.Transport)
        transport.get_extra_info = lambda k: {'peername': ('ip', 90)}[k]
        received_data = BytesIO()
        transport.is_closing = lambda: received_data.closed
        transport.write = received_data.write
        server_protocol.connection_made(transport)
        blob_request = BlobRequest.make_request_for_blob_hash(blob_hash).serialize()
        for byte in blob_request:
            server_protocol.data_received(bytes([byte]))
        await asyncio.sleep(0.1)  # yield execution
        self.assertGreater(len(received_data.getvalue()), 0)

    async def test_idle_timeout(self):
        self.server.idle_timeout = 1

        blob_hash = "7f5ab2def99f0ddd008da71db3a3772135f4002b19b7605840ed1034c8955431bd7079549e65e6b2a3b9c17c773073ed"
        mock_blob_bytes = b'1' * ((2 * 2 ** 20) - 1)
        await self._add_blob_to_server(blob_hash, mock_blob_bytes)
        client_blob = self.client_blob_manager.get_blob(blob_hash)

        # download the blob
        downloaded, protocol = await request_blob(self.loop, client_blob, self.server_from_client.address,
                                                   self.server_from_client.tcp_port, 2, 3)
        self.assertIsNotNone(protocol)
        self.assertFalse(protocol.transport.is_closing())
        await client_blob.verified.wait()
        self.assertTrue(client_blob.get_is_verified())
        self.assertTrue(downloaded)
        client_blob.delete()

        # wait for less than the idle timeout
        await asyncio.sleep(0.5, loop=self.loop)

        # download the blob again
        downloaded, protocol2 = await request_blob(self.loop, client_blob, self.server_from_client.address,
                                                   self.server_from_client.tcp_port, 2, 3,
                                                    connected_protocol=protocol)
        self.assertIs(protocol, protocol2)
        self.assertFalse(protocol.transport.is_closing())
        await client_blob.verified.wait()
        self.assertTrue(client_blob.get_is_verified())
        self.assertTrue(downloaded)
        client_blob.delete()

        # check that the connection times out from the server side
        await asyncio.sleep(0.9, loop=self.loop)
        self.assertFalse(protocol.transport.is_closing())
        self.assertIsNotNone(protocol.transport._sock)
        await asyncio.sleep(0.1, loop=self.loop)
        self.assertIsNone(protocol.transport)

    def test_max_request_size(self):
        protocol = BlobServerProtocol(self.loop, self.server_blob_manager, 'bQEaw42GXsgCAGio1nxFncJSyRmnztSCjP')
        called = asyncio.Event()
        protocol.close = called.set
        protocol.data_received(b'0' * 1199)
        self.assertFalse(called.is_set())
        protocol.data_received(b'0')
        self.assertTrue(called.is_set())

    def test_bad_json(self):
        protocol = BlobServerProtocol(self.loop, self.server_blob_manager, 'bQEaw42GXsgCAGio1nxFncJSyRmnztSCjP')
        called = asyncio.Event()
        protocol.close = called.set
        protocol.data_received(b'{{0}')
        self.assertTrue(called.is_set())

    def test_no_request(self):
        protocol = BlobServerProtocol(self.loop, self.server_blob_manager, 'bQEaw42GXsgCAGio1nxFncJSyRmnztSCjP')
        called = asyncio.Event()
        protocol.close = called.set
        protocol.data_received(b'{}')
        self.assertTrue(called.is_set())

    async def test_transfer_timeout(self):
        self.server.transfer_timeout = 1

        blob_hash = "7f5ab2def99f0ddd008da71db3a3772135f4002b19b7605840ed1034c8955431bd7079549e65e6b2a3b9c17c773073ed"
        mock_blob_bytes = b'1' * ((2 * 2 ** 20) - 1)
        await self._add_blob_to_server(blob_hash, mock_blob_bytes)
        client_blob = self.client_blob_manager.get_blob(blob_hash)
        server_blob = self.server_blob_manager.get_blob(blob_hash)

        async def sendfile(writer):
            await asyncio.sleep(2, loop=self.loop)
            return 0

        server_blob.sendfile = sendfile

        with self.assertRaises(asyncio.CancelledError):
            await request_blob(self.loop, client_blob, self.server_from_client.address,
                               self.server_from_client.tcp_port, 2, 3)

    async def test_download_blob_using_jsonrpc_blob_get(self):
        blob_hash = "7f5ab2def99f0ddd008da71db3a3772135f4002b19b7605840ed1034c8955431bd7079549e65e6b2a3b9c17c773073ed"
        mock_blob_bytes = b'1' * ((2 * 2 ** 20) - 1)
        await self._add_blob_to_server(blob_hash, mock_blob_bytes)

        # setup RPC Daemon
        daemon_config = copy.deepcopy(self.client_config)
        daemon_config.fixed_peers = [(self.server_from_client.address, self.server_from_client.tcp_port)]
        daemon = Daemon(daemon_config)

        mock_node = mock.Mock(spec=Node)

        def _mock_accumulate_peers(q1, q2=None):
            async def _task():
                pass
            q2 = q2 or asyncio.Queue(loop=self.loop)
            return q2, self.loop.create_task(_task())

        mock_node.accumulate_peers = _mock_accumulate_peers
        with mock.patch('lbry.extras.daemon.componentmanager.ComponentManager.all_components_running',
                        return_value=True):
            with mock.patch('lbry.extras.daemon.daemon.Daemon.dht_node', new_callable=mock.PropertyMock) \
                    as daemon_mock_dht:
                with mock.patch('lbry.extras.daemon.daemon.Daemon.blob_manager', new_callable=mock.PropertyMock) \
                        as daemon_mock_blob_manager:
                    daemon_mock_dht.return_value = mock_node
                    daemon_mock_blob_manager.return_value = self.client_blob_manager
                    result = await daemon.jsonrpc_blob_get(blob_hash, read=True)
                    self.assertIsNotNone(result)
                    self.assertEqual(mock_blob_bytes.decode(), result, "Downloaded blob is different than server blob")
