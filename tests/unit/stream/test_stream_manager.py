import os
import binascii
from unittest import mock
import asyncio
import time
from tests.unit.blob_exchange.test_transfer_blob import BlobExchangeTestBase
from tests.unit.lbrynet_daemon.test_ExchangeRateManager import get_dummy_exchange_rate_manager

from lbrynet.extras.wallet.manager import LbryWalletManager
from lbrynet.stream.stream_manager import StreamManager
from lbrynet.stream.descriptor import StreamDescriptor
from lbrynet.dht.node import Node
from lbrynet.schema.claim import ClaimDict


def get_mock_node(peer):
    def mock_accumulate_peers(q1: asyncio.Queue, q2: asyncio.Queue):
        async def _task():
            pass

        q2.put_nowait([peer])
        return q2, asyncio.create_task(_task())

    mock_node = mock.Mock(spec=Node)
    mock_node.accumulate_peers = mock_accumulate_peers
    return mock_node


def get_mock_wallet(sd_hash, storage):
    claim = {
        "address": "bYFeMtSL7ARuG1iMpjFyrnTe4oJHSAVNXF",
        "amount": "0.1",
        "claim_id": "c49566d631226492317d06ad7fdbe1ed32925124",
        "claim_sequence": 1,
        "decoded_claim": True,
        "depth": 1057,
        "effective_amount": "0.1",
        "has_signature": False,
        "height": 514081,
        "hex": "",
        "name": "33rpm",
        "nout": 0,
        "permanent_url": "33rpm#c49566d631226492317d06ad7fdbe1ed32925124",
        "supports": [],
        "txid": "81ac52662af926fdf639d56920069e0f63449d4cde074c61717cb99ddde40e3c",
        "value": {
            "claimType": "streamType",
            "stream": {
                "metadata": {
                    "author": "",
                    "description": "",
                    "language": "en",
                    "license": "None",
                    "licenseUrl": "",
                    "nsfw": False,
                    "preview": "",
                    "thumbnail": "",
                    "title": "33rpm",
                    "version": "_0_1_0"
                },
                "source": {
                    "contentType": "image/png",
                    "source": sd_hash,
                    "sourceType": "lbry_sd_hash",
                    "version": "_0_0_1"
                },
                "version": "_0_0_1"
            },
            "version": "_0_0_1"
        }
    }
    claim_dict = ClaimDict.load_dict(claim['value'])
    claim['hex'] = binascii.hexlify(claim_dict.serialized).decode()

    async def mock_resolve(*args):
        await storage.save_claims([claim])
        return {
            claim['permanent_url']: claim
        }

    mock_wallet = mock.Mock(spec=LbryWalletManager)
    mock_wallet.resolve = mock_resolve
    return mock_wallet, claim['permanent_url']


class TestStreamManager(BlobExchangeTestBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        file_path = os.path.join(self.server_dir, "test_file")
        with open(file_path, 'wb') as f:
            f.write(os.urandom(20000000))
        descriptor = await StreamDescriptor.create_stream(self.loop, self.server_blob_manager.blob_dir, file_path)
        self.sd_hash = descriptor.calculate_sd_hash()
        self.mock_wallet, self.uri = get_mock_wallet(self.sd_hash, self.client_storage)
        self.stream_manager = StreamManager(self.loop, self.client_config, self.client_blob_manager, self.mock_wallet,
                                            self.client_storage, get_mock_node(self.server_from_client))
        self.exchange_rate_manager = get_dummy_exchange_rate_manager(time)

    async def test_download_from_uri(self):
        self.assertSetEqual(self.stream_manager.streams, set())
        stream = await self.stream_manager.download_stream_from_uri(self.uri, self.exchange_rate_manager)
        self.assertTrue(stream.running)
        self.assertFalse(stream.finished)
        await stream.downloader.stream_finished_event.wait()
        self.assertTrue(stream.finished)
        self.assertFalse(stream.running)
