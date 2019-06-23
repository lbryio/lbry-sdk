import json
import shutil
import tempfile
import logging
from binascii import unhexlify

from torba.testcase import IntegrationTestCase, WalletNode

import lbry.wallet

from lbry.conf import Config
from lbry.extras.daemon.Daemon import Daemon, jsonrpc_dumps_pretty
from lbry.wallet import LbryWalletManager
from lbry.wallet.account import Account
from lbry.extras.daemon.Components import Component, WalletComponent
from lbry.extras.daemon.Components import (
    DHT_COMPONENT, HASH_ANNOUNCER_COMPONENT, PEER_PROTOCOL_SERVER_COMPONENT,
    UPNP_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT
)
from lbry.extras.daemon.ComponentManager import ComponentManager
from lbry.extras.daemon.storage import SQLiteStorage
from lbry.blob.blob_manager import BlobManager
from lbry.stream.reflector.server import ReflectorServer
from lbry.blob_exchange.server import BlobServer


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

    LEDGER = lbry.wallet
    MANAGER = LbryWalletManager
    VERBOSITY = logging.WARN
    blob_lru_cache_size = 0

    account: Account

    async def asyncSetUp(self):
        await super().asyncSetUp()

        logging.getLogger('lbry.blob_exchange').setLevel(self.VERBOSITY)
        logging.getLogger('lbry.daemon').setLevel(self.VERBOSITY)
        logging.getLogger('lbry.stream').setLevel(self.VERBOSITY)

        self.daemons = []
        self.extra_wallet_nodes = []
        self.extra_wallet_node_port = 5280
        self.daemon = await self.add_daemon(self.wallet_node)

        await self.account.ensure_address_gap()
        address = (await self.account.receiving.get_addresses(limit=1, only_usable=True))[0]
        sendtxid = await self.blockchain.send_to_address(address, 10)
        await self.confirm_tx(sendtxid)
        await self.generate(5)

        server_tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, server_tmp_dir)
        self.server_config = Config()
        self.server_storage = SQLiteStorage(self.server_config, ':memory:')
        await self.server_storage.open()

        self.server_blob_manager = BlobManager(self.loop, server_tmp_dir, self.server_storage, self.server_config)
        self.server = BlobServer(self.loop, self.server_blob_manager, 'bQEaw42GXsgCAGio1nxFncJSyRmnztSCjP')
        self.server.start_server(5567, '127.0.0.1')
        await self.server.started_listening.wait()

        self.reflector = ReflectorServer(self.server_blob_manager)
        self.reflector.start_server(5566, '127.0.0.1')
        await self.reflector.started_listening.wait()
        self.addCleanup(self.reflector.stop_server)

    async def asyncTearDown(self):
        await super().asyncTearDown()
        for wallet_node in self.extra_wallet_nodes:
            await wallet_node.stop(cleanup=True)
        for daemon in self.daemons:
            daemon.component_manager.get_component('wallet')._running = False
            await daemon.stop(shutdown_runner=False)

    async def add_daemon(self, wallet_node=None, seed=None):
        if wallet_node is None:
            wallet_node = WalletNode(
                self.wallet_node.manager_class,
                self.wallet_node.ledger_class,
                port=self.extra_wallet_node_port
            )
            self.extra_wallet_node_port += 1
            await wallet_node.start(self.conductor.spv_node, seed=seed)
            self.extra_wallet_nodes.append(wallet_node)

        conf = Config()
        conf.data_dir = wallet_node.data_path
        conf.wallet_dir = wallet_node.data_path
        conf.download_dir = wallet_node.data_path
        conf.share_usage_data = False
        conf.use_upnp = False
        conf.reflect_streams = True
        conf.blockchain_name = 'lbrycrd_regtest'
        conf.lbryum_servers = [('127.0.0.1', 50001)]
        conf.reflector_servers = [('127.0.0.1', 5566)]
        conf.known_dht_nodes = []
        conf.blob_lru_cache_size = self.blob_lru_cache_size
        conf.components_to_skip = [
            DHT_COMPONENT, UPNP_COMPONENT, HASH_ANNOUNCER_COMPONENT,
            PEER_PROTOCOL_SERVER_COMPONENT
        ]

        def wallet_maker(component_manager):
            wallet_component = WalletComponent(component_manager)
            wallet_component.wallet_manager = wallet_node.manager
            wallet_component._running = True
            return wallet_component

        daemon = Daemon(conf, ComponentManager(
            conf, skip_components=conf.components_to_skip, wallet=wallet_maker,
            exchange_rate_manager=ExchangeRateManagerComponent
        ))
        await daemon.initialize()
        self.daemons.append(daemon)
        wallet_node.manager.old_db = daemon.storage
        return daemon

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

    async def blockchain_claim_name(self, name: str, value: str, amount: str, confirm=True):
        txid = await self.blockchain._cli_cmnd('claimname', name, value, amount)
        if confirm:
            await self.generate(1)
        return txid

    async def blockchain_update_name(self, txid: str, value: str, amount: str, confirm=True):
        txid = await self.blockchain._cli_cmnd('updateclaim', txid, value, amount)
        if confirm:
            await self.generate(1)
        return txid

    async def out(self, awaitable):
        """ Serializes lbrynet API results to JSON then loads and returns it as dictionary. """
        return json.loads(jsonrpc_dumps_pretty(await awaitable, ledger=self.ledger))['result']

    def sout(self, value):
        """ Synchronous version of `out` method. """
        return json.loads(jsonrpc_dumps_pretty(value, ledger=self.ledger))['result']

    async def stream_create(self, name='hovercraft', bid='1.0', data=b'hi!', confirm=True, **kwargs):
        file = tempfile.NamedTemporaryFile()

        def cleanup():
            try:
                file.close()
            except FileNotFoundError:
                pass

        self.addCleanup(cleanup)
        file.write(data)
        file.flush()
        claim = await self.out(
            self.daemon.jsonrpc_stream_create(name, bid, file_path=file.name, **kwargs)
        )
        self.assertEqual(claim['outputs'][0]['name'], name)
        if confirm:
            await self.on_transaction_dict(claim)
            await self.generate(1)
            await self.on_transaction_dict(claim)
        return claim

    async def stream_update(self, claim_id, data=None, confirm=True, **kwargs):
        if data:
            file = tempfile.NamedTemporaryFile()
            file.write(data)
            file.flush()

            def cleanup():
                try:
                    file.close()
                except FileNotFoundError:
                    pass

            self.addCleanup(cleanup)
            claim = await self.out(
                self.daemon.jsonrpc_stream_update(claim_id, file_path=file.name, **kwargs)
            )
        else:
            claim = await self.out(self.daemon.jsonrpc_stream_update(claim_id, **kwargs))
        self.assertIsNotNone(claim['outputs'][0]['name'])
        if confirm:
            await self.on_transaction_dict(claim)
            await self.generate(1)
            await self.on_transaction_dict(claim)
        return claim

    async def stream_abandon(self, *args, confirm=True, **kwargs):
        if 'blocking' not in kwargs:
            kwargs['blocking'] = False
        tx = await self.out(self.daemon.jsonrpc_stream_abandon(*args, **kwargs))
        if confirm:
            await self.on_transaction_dict(tx)
            await self.generate(1)
            await self.on_transaction_dict(tx)
        return tx

    async def publish(self, name, *args, confirm=True, **kwargs):
        claim = await self.out(self.daemon.jsonrpc_publish(name, *args, **kwargs))
        self.assertEqual(claim['outputs'][0]['name'], name)
        if confirm:
            await self.on_transaction_dict(claim)
            await self.generate(1)
            await self.on_transaction_dict(claim)
        return claim

    async def channel_create(self, name='@arena', bid='1.0', confirm=True, **kwargs):
        channel = await self.out(self.daemon.jsonrpc_channel_create(name, bid, **kwargs))
        self.assertEqual(channel['outputs'][0]['name'], name)
        if confirm:
            await self.on_transaction_dict(channel)
            await self.generate(1)
            await self.on_transaction_dict(channel)
        return channel

    async def channel_update(self, claim_id, confirm=True, **kwargs):
        channel = await self.out(self.daemon.jsonrpc_channel_update(claim_id, **kwargs))
        self.assertTrue(channel['outputs'][0]['name'].startswith('@'))
        if confirm:
            await self.on_transaction_dict(channel)
            await self.generate(1)
            await self.on_transaction_dict(channel)
        return channel

    async def channel_abandon(self, *args, confirm=True, **kwargs):
        if 'blocking' not in kwargs:
            kwargs['blocking'] = False
        tx = await self.out(self.daemon.jsonrpc_channel_abandon(*args, **kwargs))
        if confirm:
            await self.on_transaction_dict(tx)
            await self.generate(1)
            await self.on_transaction_dict(tx)
        return tx

    async def support_create(self, claim_id, bid='1.0', confirm=True, **kwargs):
        tx = await self.out(self.daemon.jsonrpc_support_create(claim_id, bid, **kwargs))
        if confirm:
            await self.on_transaction_dict(tx)
            await self.generate(1)
            await self.on_transaction_dict(tx)
        return tx

    async def resolve(self, uri):
        return await self.out(self.daemon.jsonrpc_resolve(uri))

    async def claim_search(self, **kwargs):
        return (await self.out(self.daemon.jsonrpc_claim_search(**kwargs)))['items']
