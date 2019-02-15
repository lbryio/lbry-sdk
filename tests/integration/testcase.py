import json
import shutil
import tempfile
import logging
from binascii import unhexlify

import lbrynet.extras.wallet
from lbrynet.schema.claim import ClaimDict

from torba.testcase import IntegrationTestCase

import lbrynet.schema
lbrynet.schema.BLOCKCHAIN_NAME = 'lbrycrd_regtest'

from lbrynet.conf import Config
from lbrynet.extras.daemon.Daemon import Daemon, jsonrpc_dumps_pretty
from lbrynet.extras.wallet import LbryWalletManager
from lbrynet.extras.daemon.Components import Component, WalletComponent
from lbrynet.extras.daemon.Components import (
    DHT_COMPONENT, HASH_ANNOUNCER_COMPONENT, PEER_PROTOCOL_SERVER_COMPONENT,
    UPNP_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT
)
from lbrynet.extras.daemon.ComponentManager import ComponentManager
from lbrynet.extras.daemon.storage import SQLiteStorage
from lbrynet.blob.blob_manager import BlobFileManager
from lbrynet.stream.reflector.server import ReflectorServer
from lbrynet.blob_exchange.server import BlobServer


class ExchangeRateManager:

    def start(self):
        pass

    def stop(self):
        pass

    def convert_currency(self, from_currency, to_currency, amount):
        return amount

    def fee_dict(self):
        return {}


class ExchangeRateManagerComponent(Component):
    component_name = EXCHANGE_RATE_MANAGER_COMPONENT

    def __init__(self, component_manager):
        super().__init__(component_manager)
        self.exchange_rate_manager = ExchangeRateManager()

    @property
    def component(self) -> ExchangeRateManager:
        return self.exchange_rate_manager

    async def start(self):
        self.exchange_rate_manager.start()

    async def stop(self):
        self.exchange_rate_manager.stop()


class CommandTestCase(IntegrationTestCase):

    timeout = 180
    LEDGER = lbrynet.extras.wallet
    MANAGER = LbryWalletManager
    VERBOSITY = logging.WARN

    async def asyncSetUp(self):
        await super().asyncSetUp()

        logging.getLogger('lbrynet.blob_exchange').setLevel(self.VERBOSITY)
        logging.getLogger('lbrynet.daemon').setLevel(self.VERBOSITY)
        logging.getLogger('lbrynet.stream').setLevel(self.VERBOSITY)

        conf = Config()
        conf.data_dir = self.wallet_node.data_path
        conf.wallet_dir = self.wallet_node.data_path
        conf.download_dir = self.wallet_node.data_path
        conf.share_usage_data = False
        conf.use_upnp = False
        conf.reflect_streams = True
        conf.blockchain_name = 'lbrycrd_regtest'
        conf.lbryum_servers = [('127.0.0.1', 50001)]
        conf.reflector_servers = [('127.0.0.1', 5566)]
        conf.known_dht_nodes = []

        await self.account.ensure_address_gap()
        address = (await self.account.receiving.get_addresses(limit=1, only_usable=True))[0]
        sendtxid = await self.blockchain.send_to_address(address, 10)
        await self.confirm_tx(sendtxid)
        await self.generate(5)

        def wallet_maker(component_manager):
            self.wallet_component = WalletComponent(component_manager)
            self.wallet_component.wallet_manager = self.manager
            self.wallet_component._running = True
            return self.wallet_component

        conf.components_to_skip = [
            DHT_COMPONENT, UPNP_COMPONENT, HASH_ANNOUNCER_COMPONENT,
            PEER_PROTOCOL_SERVER_COMPONENT
        ]
        self.daemon = Daemon(conf, ComponentManager(
            conf, skip_components=conf.components_to_skip, wallet=wallet_maker,
            exchange_rate_manager=ExchangeRateManagerComponent
        ))
        await self.daemon.initialize()
        self.manager.old_db = self.daemon.storage

        server_tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, server_tmp_dir)
        self.server_storage = SQLiteStorage(Config(), ':memory:')
        await self.server_storage.open()
        self.server_blob_manager = BlobFileManager(self.loop, server_tmp_dir, self.server_storage)
        self.server = BlobServer(self.loop, self.server_blob_manager, 'bQEaw42GXsgCAGio1nxFncJSyRmnztSCjP')
        self.server.start_server(5567, '127.0.0.1')
        await self.server.started_listening.wait()

        self.reflector = ReflectorServer(self.server_blob_manager)
        self.reflector.start_server(5566, '127.0.0.1')
        await self.reflector.started_listening.wait()
        self.addCleanup(self.reflector.stop_server)

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.wallet_component._running = False
        await self.daemon.stop()

    async def confirm_tx(self, txid):
        """ Wait for tx to be in mempool, then generate a block, wait for tx to be in a block. """
        await self.on_transaction_id(txid)
        await self.generate(1)
        await self.on_transaction_id(txid)

    async def on_transaction_dict(self, tx):
        await self.ledger.wait(
            self.ledger.transaction_class(unhexlify(tx['hex']))
        )

    @staticmethod
    def get_all_addresses(tx):
        addresses = set()
        for txi in tx['inputs']:
            addresses.add(txi['address'])
        for txo in tx['outputs']:
            addresses.add(txo['address'])
        return list(addresses)

    async def generate(self, blocks):
        """ Ask lbrycrd to generate some blocks and wait until ledger has them. """
        await self.blockchain.generate(blocks)
        await self.ledger.on_header.where(self.blockchain.is_expected_block)

    async def out(self, awaitable):
        """ Converts Daemon API call results (dictionary)
            to JSON and then back to a dictionary. """
        return json.loads(jsonrpc_dumps_pretty(await awaitable, ledger=self.ledger))['result']

    async def make_claim(self, name='hovercraft', amount='1.0', data=b'hi!',
                         channel_name=None, confirm=True, account_id=None, fee=None):
        with tempfile.NamedTemporaryFile() as file:
            file.write(data)
            file.flush()
            claim = await self.out(self.daemon.jsonrpc_publish(
                name, amount, file_path=file.name, channel_name=channel_name, account_id=account_id,
                fee=fee
            ))
            self.assertTrue(claim['success'])
            if confirm:
                await self.on_transaction_dict(claim['tx'])
                await self.generate(1)
                await self.on_transaction_dict(claim['tx'])
            return claim

    async def make_channel(self, name='@arena', amount='1.0', confirm=True, account_id=None):
        channel = await self.out(self.daemon.jsonrpc_channel_new(name, amount, account_id))
        self.assertTrue(channel['success'])
        if confirm:
            await self.on_transaction_dict(channel['tx'])
            await self.generate(1)
            await self.on_transaction_dict(channel['tx'])
        return channel

    async def resolve(self, uri):
        return await self.out(self.daemon.jsonrpc_resolve(uri))
