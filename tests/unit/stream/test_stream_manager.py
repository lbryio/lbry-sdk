import os
import binascii
from unittest import mock
import asyncio
import time
import json
from decimal import Decimal
from tests.unit.blob_exchange.test_transfer_blob import BlobExchangeTestBase
from tests.unit.lbrynet_daemon.test_ExchangeRateManager import get_dummy_exchange_rate_manager
from lbrynet.utils import generate_id
from lbrynet.error import InsufficientFundsError, KeyFeeAboveMaxAllowed, ResolveError, DownloadSDTimeout, \
    DownloadDataTimeout
from lbrynet.wallet.manager import LbryWalletManager
from lbrynet.extras.daemon.analytics import AnalyticsManager
from lbrynet.stream.stream_manager import StreamManager
from lbrynet.stream.descriptor import StreamDescriptor
from lbrynet.dht.node import Node
from lbrynet.dht.protocol.protocol import KademliaProtocol
from lbrynet.dht.protocol.routing_table import TreeRoutingTable
from lbrynet.schema.claim import Claim


def get_mock_node(peer=None):
    def mock_accumulate_peers(q1: asyncio.Queue, q2: asyncio.Queue):
        async def _task():
            pass
        if peer:
            q2.put_nowait([peer])
        return q2, asyncio.create_task(_task())

    mock_node = mock.Mock(spec=Node)
    mock_node.protocol = mock.Mock(spec=KademliaProtocol)
    mock_node.protocol.routing_table = mock.Mock(spec=TreeRoutingTable)
    mock_node.protocol.routing_table.get_peers = lambda: []
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
        "confirmations": 1057,
        "effective_amount": "0.1",
        "has_signature": False,
        "height": 514081,
        "hex": "",
        "name": "33rpm",
        "nout": 0,
        "permanent_url": "33rpm#c49566d631226492317d06ad7fdbe1ed32925124",
        "supports": [],
        "txid": "81ac52662af926fdf639d56920069e0f63449d4cde074c61717cb99ddde40e3c",
    }
    claim_obj = Claim()
    if fee:
        if fee['currency'] == 'LBC':
            claim_obj.stream.fee.lbc = Decimal(fee['amount'])
        elif fee['currency'] == 'USD':
            claim_obj.stream.fee.usd = Decimal(fee['amount'])
    claim_obj.stream.title = "33rpm"
    claim_obj.stream.languages.append("en")
    claim_obj.stream.source.sd_hash = sd_hash
    claim_obj.stream.source.media_type = "image/png"
    claim['value'] = claim_obj
    claim['protobuf'] = binascii.hexlify(claim_obj.to_bytes()).decode()

    async def mock_resolve(*args):
        await storage.save_claims([claim])
        return {
            claim['permanent_url']: claim
        }

    mock_wallet = mock.Mock(spec=LbryWalletManager)
    mock_wallet.ledger.resolve = mock_resolve

    async def get_balance(*_):
        return balance

    mock_wallet.default_account.get_balance = get_balance
    return mock_wallet, claim['permanent_url']


class TestStreamManager(BlobExchangeTestBase):
    async def setup_stream_manager(self, balance=10.0, fee=None, old_sort=False):
        file_path = os.path.join(self.server_dir, "test_file")
        with open(file_path, 'wb') as f:
            f.write(os.urandom(20000000))
        descriptor = await StreamDescriptor.create_stream(
            self.loop, self.server_blob_manager.blob_dir, file_path, old_sort=old_sort
        )
        self.sd_hash = descriptor.sd_hash
        self.mock_wallet, self.uri = get_mock_wallet(self.sd_hash, self.client_storage, balance, fee)
        self.stream_manager = StreamManager(self.loop, self.client_config, self.client_blob_manager, self.mock_wallet,
                                            self.client_storage, get_mock_node(self.server_from_client),
                                            AnalyticsManager(self.client_config,
                                                             binascii.hexlify(generate_id()).decode(),
                                                             binascii.hexlify(generate_id()).decode()))
        self.exchange_rate_manager = get_dummy_exchange_rate_manager(time)

    async def _test_time_to_first_bytes(self, check_post, error=None, after_setup=None):
        await self.setup_stream_manager()
        if after_setup:
            after_setup()
        checked_analytics_event = False

        async def _check_post(event):
            check_post(event)
            nonlocal checked_analytics_event
            checked_analytics_event = True

        self.stream_manager.analytics_manager._post = _check_post
        if error:
            with self.assertRaises(error):
                await self.stream_manager.download_stream_from_uri(self.uri, self.exchange_rate_manager)
        else:
            await self.stream_manager.download_stream_from_uri(self.uri, self.exchange_rate_manager)
        await asyncio.sleep(0, loop=self.loop)
        self.assertTrue(checked_analytics_event)

    async def test_time_to_first_bytes(self):
        def check_post(event):
            self.assertEqual(event['event'], 'Time To First Bytes')
            total_duration = event['properties']['total_duration']
            resolve_duration = event['properties']['resolve_duration']
            head_blob_duration = event['properties']['head_blob_duration']
            sd_blob_duration = event['properties']['sd_blob_duration']
            self.assertFalse(event['properties']['added_fixed_peers'])
            self.assertTrue(total_duration >= resolve_duration + head_blob_duration + sd_blob_duration)

        await self._test_time_to_first_bytes(check_post)

    async def test_fixed_peer_delay_dht_peers_found(self):
        self.client_config.reflector_servers = [(self.server_from_client.address, self.server_from_client.tcp_port - 1)]
        server_from_client = None
        self.server_from_client, server_from_client = server_from_client, self.server_from_client

        def after_setup():
            self.stream_manager.node.protocol.routing_table.get_peers = lambda: [server_from_client]

        def check_post(event):
            self.assertEqual(event['event'], 'Time To First Bytes')
            total_duration = event['properties']['total_duration']
            resolve_duration = event['properties']['resolve_duration']
            head_blob_duration = event['properties']['head_blob_duration']
            sd_blob_duration = event['properties']['sd_blob_duration']

            self.assertEqual(event['event'], 'Time To First Bytes')
            self.assertEqual(event['properties']['tried_peers_count'], 1)
            self.assertEqual(event['properties']['active_peer_count'], 1)
            self.assertEqual(event['properties']['use_fixed_peers'], True)
            self.assertEqual(event['properties']['added_fixed_peers'], True)
            self.assertEqual(event['properties']['fixed_peer_delay'], self.client_config.fixed_peer_delay)
            self.assertGreaterEqual(total_duration, resolve_duration + head_blob_duration + sd_blob_duration)

        await self._test_time_to_first_bytes(check_post, after_setup=after_setup)

    async def test_override_fixed_peer_delay_dht_disabled(self):
        self.client_config.reflector_servers = [(self.server_from_client.address, self.server_from_client.tcp_port - 1)]
        self.client_config.components_to_skip = ['dht', 'hash_announcer']
        self.client_config.fixed_peer_delay = 9001.0
        self.server_from_client = None

        def check_post(event):
            total_duration = event['properties']['total_duration']
            resolve_duration = event['properties']['resolve_duration']
            head_blob_duration = event['properties']['head_blob_duration']
            sd_blob_duration = event['properties']['sd_blob_duration']

            self.assertEqual(event['event'], 'Time To First Bytes')
            self.assertEqual(event['properties']['tried_peers_count'], 1)
            self.assertEqual(event['properties']['active_peer_count'], 1)
            self.assertEqual(event['properties']['use_fixed_peers'], True)
            self.assertEqual(event['properties']['added_fixed_peers'], True)
            self.assertEqual(event['properties']['fixed_peer_delay'], 0.0)
            self.assertGreaterEqual(total_duration, resolve_duration + head_blob_duration + sd_blob_duration)

        start = self.loop.time()
        await self._test_time_to_first_bytes(check_post)
        self.assertTrue(self.loop.time() - start < 3)

    async def test_no_peers_timeout(self):
        # FIXME: the download should ideally fail right away if there are no peers
        # to initialize the shortlist and fixed peers are disabled
        self.server_from_client = None
        self.client_config.download_timeout = 3.0

        def check_post(event):
            self.assertEqual(event['event'], 'Time To First Bytes')
            self.assertEqual(event['properties']['error'], 'DownloadSDTimeout')
            self.assertEqual(event['properties']['tried_peers_count'], 0)
            self.assertEqual(event['properties']['active_peer_count'], 0)
            self.assertEqual(event['properties']['use_fixed_peers'], False)
            self.assertEqual(event['properties']['added_fixed_peers'], False)
            self.assertEqual(event['properties']['fixed_peer_delay'], None)

        start = self.loop.time()
        await self._test_time_to_first_bytes(check_post, DownloadSDTimeout)
        duration = self.loop.time() - start
        self.assertTrue(4.0 >= duration >= 3.0)

    async def test_download_stop_resume_delete(self):
        await self.setup_stream_manager()
        received = []
        expected_events = ['Time To First Bytes', 'Download Finished']

        async def check_post(event):
            received.append(event['event'])

        self.stream_manager.analytics_manager._post = check_post

        self.assertDictEqual(self.stream_manager.streams, {})
        stream = await self.stream_manager.download_stream_from_uri(self.uri, self.exchange_rate_manager)
        stream_hash = stream.stream_hash
        self.assertDictEqual(self.stream_manager.streams, {stream.sd_hash: stream})
        self.assertTrue(stream.running)
        self.assertFalse(stream.finished)
        self.assertTrue(os.path.isfile(os.path.join(self.client_dir, "test_file")))
        stored_status = await self.client_storage.run_and_return_one_or_none(
            "select status from file where stream_hash=?", stream_hash
        )
        self.assertEqual(stored_status, "running")

        await stream.stop()

        self.assertFalse(stream.finished)
        self.assertFalse(stream.running)
        self.assertFalse(os.path.isfile(os.path.join(self.client_dir, "test_file")))
        stored_status = await self.client_storage.run_and_return_one_or_none(
            "select status from file where stream_hash=?", stream_hash
        )
        self.assertEqual(stored_status, "stopped")

        await stream.save_file(node=self.stream_manager.node)
        await stream.finished_writing.wait()
        await asyncio.sleep(0, loop=self.loop)
        self.assertTrue(stream.finished)
        self.assertFalse(stream.running)
        self.assertTrue(os.path.isfile(os.path.join(self.client_dir, "test_file")))
        stored_status = await self.client_storage.run_and_return_one_or_none(
            "select status from file where stream_hash=?", stream_hash
        )
        self.assertEqual(stored_status, "finished")

        await self.stream_manager.delete_stream(stream, True)
        self.assertDictEqual(self.stream_manager.streams, {})
        self.assertFalse(os.path.isfile(os.path.join(self.client_dir, "test_file")))
        stored_status = await self.client_storage.run_and_return_one_or_none(
            "select status from file where stream_hash=?", stream_hash
        )
        self.assertEqual(stored_status, None)
        self.assertListEqual(expected_events, received)

    async def _test_download_error_on_start(self, expected_error, timeout=None):
        with self.assertRaises(expected_error):
            await self.stream_manager.download_stream_from_uri(self.uri, self.exchange_rate_manager, timeout)

    async def _test_download_error_analytics_on_start(self, expected_error, timeout=None):
        received = []

        async def check_post(event):
            self.assertEqual("Time To First Bytes", event['event'])
            received.append(event['properties']['error'])

        self.stream_manager.analytics_manager._post = check_post
        await self._test_download_error_on_start(expected_error, timeout)
        await asyncio.sleep(0, loop=self.loop)
        self.assertListEqual([expected_error.__name__], received)

    async def test_insufficient_funds(self):
        fee = {
            'currency': 'LBC',
            'amount': 11.0,
            'address': 'bYFeMtSL7ARuG1iMpjFyrnTe4oJHSAVNXF',
            'version': '_0_0_1'
        }
        await self.setup_stream_manager(10.0, fee)
        await self._test_download_error_on_start(InsufficientFundsError)

    async def test_fee_above_max_allowed(self):
        fee = {
            'currency': 'USD',
            'amount': 51.0,
            'address': 'bYFeMtSL7ARuG1iMpjFyrnTe4oJHSAVNXF',
            'version': '_0_0_1'
        }
        await self.setup_stream_manager(1000000.0, fee)
        await self._test_download_error_on_start(KeyFeeAboveMaxAllowed)

    async def test_resolve_error(self):
        await self.setup_stream_manager()
        self.uri = "fake"
        await self._test_download_error_on_start(ResolveError)

    async def test_download_sd_timeout(self):
        self.server.stop_server()
        await self.setup_stream_manager()
        await self._test_download_error_analytics_on_start(DownloadSDTimeout, timeout=1)

    async def test_download_data_timeout(self):
        await self.setup_stream_manager()
        with open(os.path.join(self.server_dir, self.sd_hash), 'r') as sdf:
            head_blob_hash = json.loads(sdf.read())['blobs'][0]['blob_hash']
        self.server_blob_manager.delete_blob(head_blob_hash)
        await self._test_download_error_analytics_on_start(DownloadDataTimeout, timeout=1)

    async def test_download_then_recover_stream_on_startup(self, old_sort=False):
        expected_analytics_events = [
            'Time To First Bytes',
            'Download Finished'
        ]
        received_events = []

        async def check_post(event):
            received_events.append(event['event'])

        await self.setup_stream_manager(old_sort=old_sort)
        self.stream_manager.analytics_manager._post = check_post

        self.assertDictEqual(self.stream_manager.streams, {})
        stream = await self.stream_manager.download_stream_from_uri(self.uri, self.exchange_rate_manager)
        await stream.finished_writing.wait()
        await asyncio.sleep(0, loop=self.loop)
        self.stream_manager.stop()
        self.client_blob_manager.stop()
        os.remove(os.path.join(self.client_blob_manager.blob_dir, stream.sd_hash))
        for blob in stream.descriptor.blobs[:-1]:
            os.remove(os.path.join(self.client_blob_manager.blob_dir, blob.blob_hash))
        await self.client_blob_manager.setup()
        await self.stream_manager.start()
        self.assertEqual(1, len(self.stream_manager.streams))
        self.assertListEqual([self.sd_hash], list(self.stream_manager.streams.keys()))
        for blob_hash in [stream.sd_hash] + [b.blob_hash for b in stream.descriptor.blobs[:-1]]:
            blob_status = await self.client_storage.get_blob_status(blob_hash)
            self.assertEqual('pending', blob_status)
        self.assertEqual('finished', self.stream_manager.streams[self.sd_hash].status)

        sd_blob = self.client_blob_manager.get_blob(stream.sd_hash)
        self.assertTrue(sd_blob.file_exists)
        self.assertTrue(sd_blob.get_is_verified())
        self.assertListEqual(expected_analytics_events, received_events)

    def test_download_then_recover_old_sort_stream_on_startup(self):
        return self.test_download_then_recover_stream_on_startup(old_sort=True)
