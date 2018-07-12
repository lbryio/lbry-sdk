import six
import tempfile
from types import SimpleNamespace
from binascii import hexlify

from twisted.internet import defer
from orchstr8.testcase import IntegrationTestCase, d2f
from torba.constants import COIN

import lbryschema
lbryschema.BLOCKCHAIN_NAME = 'lbrycrd_regtest'

from lbrynet import conf as lbry_conf
from lbrynet.daemon.Daemon import Daemon
from lbrynet.wallet.manager import LbryWalletManager
from lbrynet.daemon.Components import WalletComponent, FileManager, SessionComponent, DatabaseComponent
from lbrynet.file_manager.EncryptedFileManager import EncryptedFileManager


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
            return defer.succeed(hexlify(b'a'*48))
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
        address = (await d2f(self.account.receiving.get_usable_addresses(1)))[0]
        sendtxid = await self.blockchain.send_to_address(address.decode(), 10)
        await self.on_transaction_id(sendtxid)
        await self.blockchain.generate(1)
        await self.on_transaction_id(sendtxid)

        self.daemon = Daemon(FakeAnalytics())

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

        file_manager = FileManager(self.daemon.component_manager)
        file_manager.file_manager = EncryptedFileManager(session_component.session, True)
        file_manager._running = True
        self.daemon.file_manager = file_manager.file_manager
        self.daemon.component_manager.components.add(file_manager)


class ChannelNewCommandTests(CommandTestCase):

    VERBOSE = True

    @defer.inlineCallbacks
    def test_new_channel(self):
        result = yield self.daemon.jsonrpc_channel_new('@bar', 1*COIN)
        self.assertIn('txid', result)
        yield self.ledger.on_transaction.deferred_where(
            lambda e: e.tx.hex_id.decode() == result['txid']
        )


class WalletBalanceCommandTests(CommandTestCase):

    VERBOSE = True

    @defer.inlineCallbacks
    def test_wallet_balance(self):
        result = yield self.daemon.jsonrpc_wallet_balance()
        self.assertEqual(result, 10*COIN)


class PublishCommandTests(CommandTestCase):

    VERBOSE = True

    @defer.inlineCallbacks
    def test_publish(self):
        with tempfile.NamedTemporaryFile() as file:
            file.write(b'hello world!')
            file.flush()
            result = yield self.daemon.jsonrpc_publish('foo', 1, file_path=file.name)
            print(result)
