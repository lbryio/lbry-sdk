import six
import tempfile
import logging
from types import SimpleNamespace

from twisted.internet import defer
from orchstr8.testcase import IntegrationTestCase, d2f
from lbrynet.core.cryptoutils import get_lbry_hash_obj

import lbryschema
lbryschema.BLOCKCHAIN_NAME = 'lbrycrd_regtest'

from lbrynet import conf as lbry_conf
from lbrynet.daemon.Daemon import Daemon
from lbrynet.wallet.manager import LbryWalletManager
from lbrynet.daemon.Components import WalletComponent, FileManagerComponent, SessionComponent, DatabaseComponent
from lbrynet.daemon.ComponentManager import ComponentManager
from lbrynet.file_manager.EncryptedFileManager import EncryptedFileManager


log = logging.getLogger(__name__)


class FakeAnalytics:
    def send_new_channel(self):
        pass

    def shutdown(self):
        pass

    def send_claim_action(self, action):
        pass


class FakeBlob:
    def __init__(self):
        self.data = []
        self.blob_hash = 'abc'
        self.length = 3

    def write(self, data):
        self.data.append(data)

    def close(self):
        if self.data:
            h = get_lbry_hash_obj()
            h.update(b'hi')
            return defer.succeed(h.hexdigest())
        return defer.succeed(None)

    def get_is_verified(self):
        return True

    def open_for_reading(self):
        return six.StringIO('foo')


class FakeBlobManager:
    def get_blob_creator(self):
        return FakeBlob()

    def creator_finished(self, blob_info, should_announce):
        pass

    def get_blob(self, sd_hash):
        return FakeBlob()


class FakeSession:
    blob_manager = FakeBlobManager()
    peer_finder = None
    rate_limiter = None

    @property
    def payment_rate_manager(self):
        obj = SimpleNamespace()
        obj.min_blob_data_payment_rate = 1
        return obj


class CommandTestCase(IntegrationTestCase):

    WALLET_MANAGER = LbryWalletManager

    async def setUp(self):
        await super().setUp()

        if self.VERBOSE:
            log.setLevel(logging.DEBUG)
            logging.getLogger('lbrynet.core').setLevel(logging.DEBUG)

        lbry_conf.settings = None
        lbry_conf.initialize_settings(load_conf_file=False)
        lbry_conf.settings['data_dir'] = self.stack.wallet.data_path
        lbry_conf.settings['lbryum_wallet_dir'] = self.stack.wallet.data_path
        lbry_conf.settings['download_directory'] = self.stack.wallet.data_path
        lbry_conf.settings['use_upnp'] = False
        lbry_conf.settings['blockchain_name'] = 'lbrycrd_regtest'
        lbry_conf.settings['lbryum_servers'] = [('localhost', 50001)]
        lbry_conf.settings['known_dht_nodes'] = []
        lbry_conf.settings.node_id = None

        await d2f(self.account.ensure_address_gap())
        address = (await d2f(self.account.receiving.get_addresses(1, only_usable=True)))[0]
        sendtxid = await self.blockchain.send_to_address(address, 10)
        await self.confirm_tx(sendtxid)

        analytics_manager = FakeAnalytics()
        self.daemon = Daemon(analytics_manager, ComponentManager(analytics_manager, skip_components=[
            'wallet', 'database', 'session', 'file_manager'
        ]))

        wallet_component = WalletComponent(self.daemon.component_manager)
        wallet_component.wallet = self.manager
        wallet_component._running = True
        self.daemon.wallet = self.manager
        self.daemon.component_manager.components.add(wallet_component)

        storage_component = DatabaseComponent(self.daemon.component_manager)
        await d2f(storage_component.start())
        self.daemon.storage = storage_component.storage
        self.daemon.wallet.old_db = self.daemon.storage
        self.daemon.component_manager.components.add(storage_component)

        session_component = SessionComponent(self.daemon.component_manager)
        session_component.session = FakeSession()
        session_component._running = True
        self.daemon.session = session_component.session
        self.daemon.session.storage = self.daemon.storage
        self.daemon.session.wallet = self.daemon.wallet
        self.daemon.session.blob_manager.storage = self.daemon.storage
        self.daemon.component_manager.components.add(session_component)

        file_manager = FileManagerComponent(self.daemon.component_manager)
        file_manager.file_manager = EncryptedFileManager(session_component.session, True)
        file_manager._running = True
        self.daemon.file_manager = file_manager.file_manager
        self.daemon.component_manager.components.add(file_manager)

    async def confirm_tx(self, txid):
        """ Wait for tx to be in mempool, then generate a block, wait for tx to be in a block. """
        log.debug(
            'Waiting on %s to be in mempool. (current height: %s, expected height: %s)',
            txid, self.ledger.headers.height, self.blockchain._block_expected
        )
        await self.on_transaction_id(txid)
        log.debug(
            '%s is in mempool. (current height: %s, expected height: %s)',
            txid, self.ledger.headers.height, self.blockchain._block_expected
        )
        await self.generate(1)
        log.debug(
            'Waiting on %s to be in block. (current height: %s, expected height: %s)',
            txid, self.ledger.headers.height, self.blockchain._block_expected
        )
        await self.on_transaction_id(txid)
        log.debug(
            '%s is in a block. (current height: %s, expected height: %s)',
            txid, self.ledger.headers.height, self.blockchain._block_expected
        )

    async def generate(self, blocks):
        """ Ask lbrycrd to generate some blocks and wait until ledger has them. """
        log.info(
            'Generating %s blocks. (current height: %s)',
            blocks, self.ledger.headers.height
        )
        await self.blockchain.generate(blocks)
        await self.ledger.on_header.where(self.blockchain.is_expected_block)
        log.info(
            "Headers up to date. (current height: %s, expected height: %s)",
            self.ledger.headers.height, self.blockchain._block_expected
        )


class CommonWorkflowTests(CommandTestCase):

    VERBOSE = False

    async def test_user_creating_channel_and_publishing_file(self):

        # User checks their balance.
        result = await d2f(self.daemon.jsonrpc_wallet_balance(include_unconfirmed=True))
        self.assertEqual(result, 10)

        # Decides to get a cool new channel.
        channel = await d2f(self.daemon.jsonrpc_channel_new('@spam', 1))
        self.assertTrue(channel['success'])
        await self.confirm_tx(channel['txid'])

        # Check balance, include utxos with less than 6 confirmations (unconfirmed).
        result = await d2f(self.daemon.jsonrpc_wallet_balance(include_unconfirmed=True))
        self.assertEqual(result, 8.99)

        # Check confirmed balance, only includes utxos with 6+ confirmations.
        result = await d2f(self.daemon.jsonrpc_wallet_balance())
        self.assertEqual(result, 0)

        # Add some confirmations (there is already 1 confirmation, so we add 5 to equal 6 total).
        await self.generate(5)

        # Check balance again after some confirmations, should be correct again.
        result = await d2f(self.daemon.jsonrpc_wallet_balance())
        self.assertEqual(result, 8.99)

        # Now lets publish a hello world file to the channel.
        with tempfile.NamedTemporaryFile() as file:
            file.write(b'hello world!')
            file.flush()
            claim = await d2f(self.daemon.jsonrpc_publish(
                'hovercraft', 1, file_path=file.name, channel_name='@spam', channel_id=channel['claim_id']
            ))
            self.assertTrue(claim['success'])
            await self.confirm_tx(claim['txid'])

        # Check unconfirmed balance.
        result = await d2f(self.daemon.jsonrpc_wallet_balance(include_unconfirmed=True))
        self.assertEqual(round(result, 2), 7.97)

        # Resolve our claim.
        response = await d2f(self.ledger.resolve(0, 10, 'lbry://@spam/hovercraft'))
        self.assertIn('lbry://@spam/hovercraft', response)

        # A few confirmations before trying to spend again.
        await self.generate(5)

        # Verify confirmed balance.
        result = await d2f(self.daemon.jsonrpc_wallet_balance())
        self.assertEqual(round(result, 2), 7.97)

        # Now lets update an existing claim.
        return
        with tempfile.NamedTemporaryFile() as file:
            file.write(b'hello world x2!')
            file.flush()
            claim = await d2f(self.daemon.jsonrpc_publish(
                'hovercraft', 1, file_path=file.name, channel_name='@spam', channel_id=channel['claim_id']
            ))
            self.assertTrue(claim['success'])
            await self.confirm_tx(claim['txid'])
