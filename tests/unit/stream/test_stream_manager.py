import os
import shutil
import binascii
from unittest import mock
import asyncio
import json
from decimal import Decimal
from tests.unit.blob_exchange.test_transfer_blob import BlobExchangeTestBase
from lbry.testcase import get_fake_exchange_rate_manager
from lbry.utils import generate_id
from lbry.error import InsufficientFundsError
from lbry.error import KeyFeeAboveMaxAllowedError, ResolveError, DownloadSDTimeoutError, DownloadDataTimeoutError
from lbry.wallet import WalletManager, Wallet, Ledger, Transaction, Input, Output, Database
from lbry.wallet.constants import CENT, NULL_HASH32
from lbry.wallet.network import ClientSession
from lbry.conf import Config
from lbry.extras.daemon.analytics import AnalyticsManager
from lbry.stream.stream_manager import StreamManager
from lbry.stream.descriptor import StreamDescriptor
from lbry.dht.node import Node
from lbry.dht.protocol.protocol import KademliaProtocol
from lbry.dht.protocol.routing_table import TreeRoutingTable
from lbry.schema.claim import Claim


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


def get_output(amount=CENT, pubkey_hash=NULL_HASH32):
    return Transaction() \
        .add_outputs([Output.pay_pubkey_hash(amount, pubkey_hash)]) \
        .outputs[0]


def get_input():
    return Input.spend(get_output())


def get_transaction(txo=None):
    return Transaction() \
        .add_inputs([get_input()]) \
        .add_outputs([txo or Output.pay_pubkey_hash(CENT, NULL_HASH32)])


def get_claim_transaction(claim_name, claim=b''):
    return get_transaction(
        Output.pay_claim_name_pubkey_hash(CENT, claim_name, claim, NULL_HASH32)
    )


async def get_mock_wallet(sd_hash, storage, balance=10.0, fee=None):
    claim = Claim()
    if fee:
        if fee['currency'] == 'LBC':
            claim.stream.fee.lbc = Decimal(fee['amount'])
        elif fee['currency'] == 'USD':
            claim.stream.fee.usd = Decimal(fee['amount'])
    claim.stream.title = "33rpm"
    claim.stream.languages.append("en")
    claim.stream.source.sd_hash = sd_hash
    claim.stream.source.media_type = "image/png"

    tx = get_claim_transaction("33rpm", claim.to_bytes())
    tx.height = 514081
    txo = tx.outputs[0]
    txo.meta.update({
        "permanent_url": "33rpm#c49566d631226492317d06ad7fdbe1ed32925124",

    })

    class FakeHeaders:
        def estimated_timestamp(self, height):
            return 1984

        def __init__(self, height):
            self.height = height

        def __getitem__(self, item):
            return {'timestamp': 1984}

    wallet = Wallet()
    ledger = Ledger({
        'db': Database(':memory:'),
        'headers': FakeHeaders(514082)
    })
    await ledger.db.open()
    wallet.generate_account(ledger)
    manager = WalletManager()
    manager.config = Config()
    manager.wallets.append(wallet)
    manager.ledgers[Ledger] = ledger
    manager.ledger.network.client = ClientSession(
        network=manager.ledger.network, server=('fakespv.lbry.com', 50001)
    )

    async def mock_resolve(*args, **kwargs):
        result = {txo.meta['permanent_url']: txo}
        claims = [
            StreamManager._convert_to_old_resolve_output(manager, result)[txo.meta['permanent_url']]
        ]
        await storage.save_claims(claims)
        return result
    manager.ledger.resolve = mock_resolve

    async def get_balance(*_):
        return balance
    manager.get_balance = get_balance

    return manager, txo.meta['permanent_url']


class TestStreamManager(BlobExchangeTestBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.client_config.share_usage_data = True

    async def setup_stream_manager(self, balance=10.0, fee=None, old_sort=False):
        file_path = os.path.join(self.server_dir, "test_file")
        with open(file_path, 'wb') as f:
            f.write(os.urandom(20000000))
        descriptor = await StreamDescriptor.create_stream(
            self.loop, self.server_blob_manager.blob_dir, file_path, old_sort=old_sort
        )
        self.sd_hash = descriptor.sd_hash
        self.mock_wallet, self.uri = await get_mock_wallet(self.sd_hash, self.client_storage, balance, fee)
        self.stream_manager = StreamManager(self.loop, self.client_config, self.client_blob_manager, self.mock_wallet,
                                            self.client_storage, get_mock_node(self.server_from_client),
                                            AnalyticsManager(self.client_config,
                                                             binascii.hexlify(generate_id()).decode(),
                                                             binascii.hexlify(generate_id()).decode()))
        self.exchange_rate_manager = get_fake_exchange_rate_manager()

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
            self.assertEqual(event['properties']['wallet_server'], "fakespv.lbry.com:50001")
            self.assertGreaterEqual(total_duration, resolve_duration + head_blob_duration + sd_blob_duration)

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
            self.assertEqual(event['properties']['connection_failures_count'], 0)
            self.assertTrue(event['properties']['use_fixed_peers'])
            self.assertTrue(event['properties']['added_fixed_peers'])
            self.assertEqual(event['properties']['fixed_peer_delay'], self.client_config.fixed_peer_delay)
            self.assertGreaterEqual(total_duration, resolve_duration + head_blob_duration + sd_blob_duration)

        await self._test_time_to_first_bytes(check_post, after_setup=after_setup)

    async def test_tcp_connection_failure_analytics(self):
        self.client_config.download_timeout = 3.0

        def after_setup():
            self.server.stop_server()

        def check_post(event):
            self.assertEqual(event['event'], 'Time To First Bytes')
            self.assertIsNone(event['properties']['head_blob_duration'])
            self.assertIsNone(event['properties']['sd_blob_duration'])
            self.assertFalse(event['properties']['added_fixed_peers'])
            self.assertEqual(event['properties']['connection_failures_count'],  1)
            self.assertEqual(
                event['properties']['error_message'], f'Failed to download sd blob {self.sd_hash} within timeout.'
            )

        await self._test_time_to_first_bytes(check_post, DownloadSDTimeoutError, after_setup=after_setup)

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
            self.assertTrue(event['properties']['use_fixed_peers'])
            self.assertTrue(event['properties']['added_fixed_peers'])
            self.assertEqual(event['properties']['fixed_peer_delay'], 0.0)
            self.assertGreaterEqual(total_duration, resolve_duration + head_blob_duration + sd_blob_duration)

        start = self.loop.time()
        await self._test_time_to_first_bytes(check_post)
        self.assertLess(self.loop.time() - start, 3)

    async def test_no_peers_timeout(self):
        # FIXME: the download should ideally fail right away if there are no peers
        # to initialize the shortlist and fixed peers are disabled
        self.server_from_client = None
        self.client_config.download_timeout = 3.0

        def check_post(event):
            self.assertEqual(event['event'], 'Time To First Bytes')
            self.assertEqual(event['properties']['error'], 'DownloadSDTimeoutError')
            self.assertEqual(event['properties']['tried_peers_count'], 0)
            self.assertEqual(event['properties']['active_peer_count'], 0)
            self.assertFalse(event['properties']['use_fixed_peers'])
            self.assertFalse(event['properties']['added_fixed_peers'])
            self.assertIsNone(event['properties']['fixed_peer_delay'])
            self.assertEqual(
                event['properties']['error_message'], f'Failed to download sd blob {self.sd_hash} within timeout.'
            )

        start = self.loop.time()
        await self._test_time_to_first_bytes(check_post, DownloadSDTimeoutError)
        duration = self.loop.time() - start
        self.assertLessEqual(duration, 5)
        self.assertGreaterEqual(duration, 3.0)

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

        stream.node = self.stream_manager.node
        await stream.save_file()
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
        self.assertIsNone(stored_status)
        self.assertListEqual(expected_events, received)

    async def _test_download_error_on_start(self, expected_error, timeout=None):
        error = None
        try:
            await self.stream_manager.download_stream_from_uri(self.uri, self.exchange_rate_manager, timeout)
        except Exception as err:
            if isinstance(err, asyncio.CancelledError):  # TODO: remove when updated to 3.8
                raise
            error = err
        self.assertEqual(expected_error, type(error))

    async def _test_download_error_analytics_on_start(self, expected_error, error_message, timeout=None):
        received = []

        async def check_post(event):
            self.assertEqual("Time To First Bytes", event['event'])
            self.assertEqual(event['properties']['error_message'], error_message)
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
        await self._test_download_error_on_start(InsufficientFundsError, "")

    async def test_fee_above_max_allowed(self):
        fee = {
            'currency': 'USD',
            'amount': 51.0,
            'address': 'bYFeMtSL7ARuG1iMpjFyrnTe4oJHSAVNXF',
            'version': '_0_0_1'
        }
        await self.setup_stream_manager(1000000.0, fee)
        await self._test_download_error_on_start(KeyFeeAboveMaxAllowedError, "")

    async def test_resolve_error(self):
        await self.setup_stream_manager()
        self.uri = "fake"
        await self._test_download_error_on_start(ResolveError)

    async def test_download_sd_timeout(self):
        self.server.stop_server()
        await self.setup_stream_manager()
        await self._test_download_error_analytics_on_start(
            DownloadSDTimeoutError, f'Failed to download sd blob {self.sd_hash} within timeout.', timeout=1
        )

    async def test_download_data_timeout(self):
        await self.setup_stream_manager()
        with open(os.path.join(self.server_dir, self.sd_hash), 'r') as sdf:
            head_blob_hash = json.loads(sdf.read())['blobs'][0]['blob_hash']
        self.server_blob_manager.delete_blob(head_blob_hash)
        await self._test_download_error_analytics_on_start(
            DownloadDataTimeoutError, f'Failed to download data blobs for sd hash {self.sd_hash} within timeout.', timeout=1
        )

    async def test_unexpected_error(self):
        await self.setup_stream_manager()
        err_msg = f"invalid blob directory '{self.client_dir}'"
        shutil.rmtree(self.client_dir)
        await self._test_download_error_analytics_on_start(
            OSError, err_msg, timeout=1
        )
        os.mkdir(self.client_dir)  # so the test cleanup doesn't error

    async def test_non_head_data_timeout(self):
        await self.setup_stream_manager()
        with open(os.path.join(self.server_dir, self.sd_hash), 'r') as sdf:
            last_blob_hash = json.loads(sdf.read())['blobs'][-2]['blob_hash']
        self.server_blob_manager.delete_blob(last_blob_hash)
        self.client_config.blob_download_timeout = 0.1
        stream = await self.stream_manager.download_stream_from_uri(self.uri, self.exchange_rate_manager)
        await stream.started_writing.wait()
        self.assertEqual('running', stream.status)
        self.assertIsNotNone(stream.full_path)
        self.assertGreater(stream.written_bytes, 0)
        await stream.finished_write_attempt.wait()
        self.assertEqual('stopped', stream.status)
        self.assertIsNone(stream.full_path)
        self.assertEqual(0, stream.written_bytes)

        self.stream_manager.stop()
        await self.stream_manager.start()
        self.assertEqual(1, len(self.stream_manager.streams))
        stream = list(self.stream_manager.streams.values())[0]
        self.assertEqual('stopped', stream.status)
        self.assertIsNone(stream.full_path)
        self.assertEqual(0, stream.written_bytes)

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
