import asyncio
import tempfile
import shutil
import os
from torba.testcase import AsyncioTestCase
from lbrynet.storage import SQLiteStorage
from lbrynet.blob.blob_manager import BlobFileManager

from lbrynet import conf
from lbrynet.extras.reflector import reflector

if typing.TYPE_CHECKING:
    from lbrynet.stream.descriptor import StreamDescriptor
    from lbrynet.blob.blob_manager import BlobFileManager

# TODO: reflect from stream
# TODO: reflecto from blob
# TODO: reflect from all saved blobs
# TODO: reflect from blob_hashes



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
