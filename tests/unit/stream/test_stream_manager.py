import os
import binascii
from unittest import mock
import asyncio
import time
from tests.unit.blob_exchange.test_transfer_blob import BlobExchangeTestBase
from tests.unit.lbrynet_daemon.test_ExchangeRateManager import get_dummy_exchange_rate_manager
from lbrynet.error import InsufficientFundsError, KeyFeeAboveMaxAllowed
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
    mock_node.joined = asyncio.Event()
    mock_node.joined.set()
    return mock_node


def get_mock_wallet(sd_hash, storage, balance=10.0, fee=None):
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
    if fee:
        claim['value']['stream']['metadata']['fee'] = fee
    claim_dict = ClaimDict.load_dict(claim['value'])
    claim['hex'] = binascii.hexlify(claim_dict.serialized).decode()

    async def mock_resolve(*args):
        await storage.save_claims([claim])
        return {
            claim['permanent_url']: claim
        }

    mock_wallet = mock.Mock(spec=LbryWalletManager)
    mock_wallet.resolve = mock_resolve

    async def get_balance(*_):
        return balance

    mock_wallet.default_account.get_balance = get_balance
    return mock_wallet, claim['permanent_url']


class TestStreamManager(BlobExchangeTestBase):
    async def setup_stream_manager(self, balance=10.0, fee=None, old_sort=False):
        file_path = os.path.join(self.server_dir, "test_file")
        with open(file_path, 'wb') as f:
            f.write(os.urandom(20000000))
        descriptor = await StreamDescriptor.create_stream(self.loop, self.server_blob_manager.blob_dir, file_path,
                                                          old_sort=old_sort)
        self.sd_hash = descriptor.sd_hash
        self.mock_wallet, self.uri = get_mock_wallet(self.sd_hash, self.client_storage, balance, fee)
        self.stream_manager = StreamManager(self.loop, self.client_config, self.client_blob_manager, self.mock_wallet,
                                            self.client_storage, get_mock_node(self.server_from_client))
        self.exchange_rate_manager = get_dummy_exchange_rate_manager(time)

    async def test_download_stop_resume_delete(self):
        await self.setup_stream_manager()
        self.assertSetEqual(self.stream_manager.streams, set())
        stream = await self.stream_manager.download_stream_from_uri(self.uri, self.exchange_rate_manager)
        stream_hash = stream.stream_hash
        self.assertSetEqual(self.stream_manager.streams, {stream})
        self.assertTrue(stream.running)
        self.assertFalse(stream.finished)
        self.assertTrue(os.path.isfile(os.path.join(self.client_dir, "test_file")))
        stored_status = await self.client_storage.run_and_return_one_or_none(
            "select status from file where stream_hash=?", stream_hash
        )
        self.assertEqual(stored_status, "running")

        await self.stream_manager.stop_stream(stream)

        self.assertFalse(stream.finished)
        self.assertFalse(stream.running)
        self.assertFalse(os.path.isfile(os.path.join(self.client_dir, "test_file")))
        stored_status = await self.client_storage.run_and_return_one_or_none(
            "select status from file where stream_hash=?", stream_hash
        )
        self.assertEqual(stored_status, "stopped")

        await self.stream_manager.start_stream(stream)
        await stream.downloader.stream_finished_event.wait()
        await asyncio.sleep(0.01)
        self.assertTrue(stream.finished)
        self.assertFalse(stream.running)
        self.assertTrue(os.path.isfile(os.path.join(self.client_dir, "test_file")))
        stored_status = await self.client_storage.run_and_return_one_or_none(
            "select status from file where stream_hash=?", stream_hash
        )
        self.assertEqual(stored_status, "finished")

        await self.stream_manager.delete_stream(stream, True)
        self.assertSetEqual(self.stream_manager.streams, set())
        self.assertFalse(os.path.isfile(os.path.join(self.client_dir, "test_file")))
        stored_status = await self.client_storage.run_and_return_one_or_none(
            "select status from file where stream_hash=?", stream_hash
        )
        self.assertEqual(stored_status, None)

    async def test_insufficient_funds(self):
        fee = {
            'currency': 'LBC',
            'amount': 11.0,
            'address': 'bYFeMtSL7ARuG1iMpjFyrnTe4oJHSAVNXF',
            'version': '_0_0_1'
        }
        await self.setup_stream_manager(10.0, fee)
        with self.assertRaises(InsufficientFundsError):
            await self.stream_manager.download_stream_from_uri(self.uri, self.exchange_rate_manager)

    async def test_fee_above_max_allowed(self):
        fee = {
            'currency': 'USD',
            'amount': 51.0,
            'address': 'bYFeMtSL7ARuG1iMpjFyrnTe4oJHSAVNXF',
            'version': '_0_0_1'
        }
        await self.setup_stream_manager(1000000.0, fee)
        with self.assertRaises(KeyFeeAboveMaxAllowed):
            await self.stream_manager.download_stream_from_uri(self.uri, self.exchange_rate_manager)

    async def test_download_then_recover_stream_on_startup(self, old_sort=False):
        await self.setup_stream_manager(old_sort=old_sort)
        self.assertSetEqual(self.stream_manager.streams, set())
        stream = await self.stream_manager.download_stream_from_uri(self.uri, self.exchange_rate_manager)
        await stream.downloader.stream_finished_event.wait()
        self.stream_manager.stop()
        self.client_blob_manager.stop()
        os.remove(os.path.join(self.client_blob_manager.blob_dir, stream.sd_hash))
        for blob in stream.descriptor.blobs[:-1]:
            os.remove(os.path.join(self.client_blob_manager.blob_dir, blob.blob_hash))
        await self.client_blob_manager.setup()
        await self.stream_manager.start()
        self.assertEqual(1, len(self.stream_manager.streams))
        self.assertEqual(stream.sd_hash, list(self.stream_manager.streams)[0].sd_hash)
        self.assertEqual('stopped', list(self.stream_manager.streams)[0].status)

        sd_blob = self.client_blob_manager.get_blob(stream.sd_hash)
        self.assertTrue(sd_blob.file_exists)
        self.assertTrue(sd_blob.get_is_verified())

    def test_download_then_recover_old_sort_stream_on_startup(self):
        return self.test_download_then_recover_stream_on_startup(old_sort=True)
