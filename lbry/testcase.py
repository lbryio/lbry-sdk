import os
import sys
import json
import shutil
import logging
import tempfile
import functools
import asyncio
from asyncio.runners import _cancel_all_tasks  # type: ignore
import unittest
from unittest.case import _Outcome
from typing import Optional
from time import time
from binascii import unhexlify
from functools import partial

from lbry.wallet import WalletManager, Wallet, Ledger, Account, Transaction
from lbry.conf import Config
from lbry.wallet.util import satoshis_to_coins
from lbry.wallet.orchstr8 import Conductor
from lbry.wallet.orchstr8.node import BlockchainNode, WalletNode

from lbry.extras.daemon.Daemon import Daemon, jsonrpc_dumps_pretty
from lbry.extras.daemon.Components import Component, WalletComponent
from lbry.extras.daemon.Components import (
    DHT_COMPONENT, HASH_ANNOUNCER_COMPONENT, PEER_PROTOCOL_SERVER_COMPONENT,
    UPNP_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT
)
from lbry.extras.daemon.ComponentManager import ComponentManager
from lbry.extras.daemon.exchange_rate_manager import (
    ExchangeRateManager, ExchangeRate, LBRYFeed, LBRYBTCFeed
)
from lbry.extras.daemon.storage import SQLiteStorage
from lbry.blob.blob_manager import BlobManager
from lbry.stream.reflector.server import ReflectorServer
from lbry.blob_exchange.server import BlobServer


class ColorHandler(logging.StreamHandler):

    level_color = {
        logging.DEBUG: "black",
        logging.INFO: "light_gray",
        logging.WARNING: "yellow",
        logging.ERROR: "red"
    }

    color_code = dict(
        black=30,
        red=31,
        green=32,
        yellow=33,
        blue=34,
        magenta=35,
        cyan=36,
        white=37,
        light_gray='0;37',
        dark_gray='1;30'
    )

    def emit(self, record):
        try:
            msg = self.format(record)
            color_name = self.level_color.get(record.levelno, "black")
            color_code = self.color_code[color_name]
            stream = self.stream
            stream.write(f'\x1b[{color_code}m{msg}\x1b[0m')
            stream.write(self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)


HANDLER = ColorHandler(sys.stdout)
HANDLER.setFormatter(
    logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
)
logging.getLogger().addHandler(HANDLER)


class AsyncioTestCase(unittest.TestCase):
    # Implementation inspired by discussion:
    #  https://bugs.python.org/issue32972

    LOOP_SLOW_CALLBACK_DURATION = 0.2

    maxDiff = None

    async def asyncSetUp(self):  # pylint: disable=C0103
        pass

    async def asyncTearDown(self):  # pylint: disable=C0103
        pass

    def run(self, result=None):  # pylint: disable=R0915
        orig_result = result
        if result is None:
            result = self.defaultTestResult()
            startTestRun = getattr(result, 'startTestRun', None)  # pylint: disable=C0103
            if startTestRun is not None:
                startTestRun()

        result.startTest(self)

        testMethod = getattr(self, self._testMethodName)  # pylint: disable=C0103
        if (getattr(self.__class__, "__unittest_skip__", False) or
                getattr(testMethod, "__unittest_skip__", False)):
            # If the class or method was skipped.
            try:
                skip_why = (getattr(self.__class__, '__unittest_skip_why__', '')
                            or getattr(testMethod, '__unittest_skip_why__', ''))
                self._addSkip(result, self, skip_why)
            finally:
                result.stopTest(self)
            return
        expecting_failure_method = getattr(testMethod,
                                           "__unittest_expecting_failure__", False)
        expecting_failure_class = getattr(self,
                                          "__unittest_expecting_failure__", False)
        expecting_failure = expecting_failure_class or expecting_failure_method
        outcome = _Outcome(result)

        self.loop = asyncio.new_event_loop()  # pylint: disable=W0201
        asyncio.set_event_loop(self.loop)
        self.loop.set_debug(True)
        self.loop.slow_callback_duration = self.LOOP_SLOW_CALLBACK_DURATION

        try:
            self._outcome = outcome

            with outcome.testPartExecutor(self):
                self.setUp()
                self.loop.run_until_complete(self.asyncSetUp())
            if outcome.success:
                outcome.expecting_failure = expecting_failure
                with outcome.testPartExecutor(self, isTest=True):
                    maybe_coroutine = testMethod()
                    if asyncio.iscoroutine(maybe_coroutine):
                        self.loop.run_until_complete(maybe_coroutine)
                outcome.expecting_failure = False
                with outcome.testPartExecutor(self):
                    self.loop.run_until_complete(self.asyncTearDown())
                    self.tearDown()

            self.doAsyncCleanups()

            try:
                _cancel_all_tasks(self.loop)
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            finally:
                asyncio.set_event_loop(None)
                self.loop.close()

            for test, reason in outcome.skipped:
                self._addSkip(result, test, reason)
            self._feedErrorsToResult(result, outcome.errors)
            if outcome.success:
                if expecting_failure:
                    if outcome.expectedFailure:
                        self._addExpectedFailure(result, outcome.expectedFailure)
                    else:
                        self._addUnexpectedSuccess(result)
                else:
                    result.addSuccess(self)
            return result
        finally:
            result.stopTest(self)
            if orig_result is None:
                stopTestRun = getattr(result, 'stopTestRun', None)  # pylint: disable=C0103
                if stopTestRun is not None:
                    stopTestRun()  # pylint: disable=E1102

            # explicitly break reference cycles:
            # outcome.errors -> frame -> outcome -> outcome.errors
            # outcome.expectedFailure -> frame -> outcome -> outcome.expectedFailure
            outcome.errors.clear()
            outcome.expectedFailure = None

            # clear the outcome, no more needed
            self._outcome = None

    def doAsyncCleanups(self):  # pylint: disable=C0103
        outcome = self._outcome or _Outcome()
        while self._cleanups:
            function, args, kwargs = self._cleanups.pop()
            with outcome.testPartExecutor(self):
                maybe_coroutine = function(*args, **kwargs)
                if asyncio.iscoroutine(maybe_coroutine):
                    self.loop.run_until_complete(maybe_coroutine)


class AdvanceTimeTestCase(AsyncioTestCase):

    async def asyncSetUp(self):
        self._time = 0  # pylint: disable=W0201
        self.loop.time = functools.wraps(self.loop.time)(lambda: self._time)
        await super().asyncSetUp()

    async def advance(self, seconds):
        while self.loop._ready:
            await asyncio.sleep(0)
        self._time += seconds
        await asyncio.sleep(0)
        while self.loop._ready:
            await asyncio.sleep(0)


class IntegrationTestCase(AsyncioTestCase):

    SEED = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.conductor: Optional[Conductor] = None
        self.blockchain: Optional[BlockchainNode] = None
        self.wallet_node: Optional[WalletNode] = None
        self.manager: Optional[WalletManager] = None
        self.ledger: Optional[Ledger] = None
        self.wallet: Optional[Wallet] = None
        self.account: Optional[Account] = None

    async def asyncSetUp(self):
        self.conductor = Conductor(seed=self.SEED)
        await self.conductor.start_blockchain()
        self.addCleanup(self.conductor.stop_blockchain)
        await self.conductor.start_spv()
        self.addCleanup(self.conductor.stop_spv)
        await self.conductor.start_wallet()
        self.addCleanup(self.conductor.stop_wallet)
        self.blockchain = self.conductor.blockchain_node
        self.wallet_node = self.conductor.wallet_node
        self.manager = self.wallet_node.manager
        self.ledger = self.wallet_node.ledger
        self.wallet = self.wallet_node.wallet
        self.account = self.wallet_node.wallet.default_account

    async def assertBalance(self, account, expected_balance: str):  # pylint: disable=C0103
        balance = await account.get_balance()
        self.assertEqual(satoshis_to_coins(balance), expected_balance)

    def broadcast(self, tx):
        return self.ledger.broadcast(tx)

    async def on_header(self, height):
        if self.ledger.headers.height < height:
            await self.ledger.on_header.where(
                lambda e: e.height == height
            )
        return True

    def on_transaction_id(self, txid, ledger=None):
        return (ledger or self.ledger).on_transaction.where(
            lambda e: e.tx.id == txid
        )

    def on_transaction_address(self, tx, address):
        return self.ledger.on_transaction.where(
            lambda e: e.tx.id == tx.id and e.address == address
        )


class FakeExchangeRateManager(ExchangeRateManager):

    def __init__(self, market_feeds, rates):
        self.market_feeds = market_feeds
        for feed in self.market_feeds:
            feed.last_check = time()
            feed.rate = ExchangeRate(feed.market, rates[feed.market], time())

    def start(self):
        pass

    def stop(self):
        pass


def get_fake_exchange_rate_manager(rates=None):
    return FakeExchangeRateManager(
        [LBRYFeed(), LBRYBTCFeed()],
        rates or {'BTCLBC': 3.0, 'USDBTC': 2.0}
    )


class ExchangeRateManagerComponent(Component):
    component_name = EXCHANGE_RATE_MANAGER_COMPONENT

    def __init__(self, component_manager, rates=None):
        super().__init__(component_manager)
        self.exchange_rate_manager = get_fake_exchange_rate_manager(rates)

    @property
    def component(self) -> ExchangeRateManager:
        return self.exchange_rate_manager

    async def start(self):
        self.exchange_rate_manager.start()

    async def stop(self):
        self.exchange_rate_manager.stop()


class CommandTestCase(IntegrationTestCase):

    VERBOSITY = logging.WARN
    blob_lru_cache_size = 0

    async def asyncSetUp(self):
        await super().asyncSetUp()

        logging.getLogger('lbry.blob_exchange').setLevel(self.VERBOSITY)
        logging.getLogger('lbry.daemon').setLevel(self.VERBOSITY)
        logging.getLogger('lbry.stream').setLevel(self.VERBOSITY)
        logging.getLogger('lbry.wallet').setLevel(self.VERBOSITY)

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
            await daemon.stop()

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

        upload_dir = os.path.join(wallet_node.data_path, 'uploads')
        os.mkdir(upload_dir)

        conf = Config()
        conf.data_dir = wallet_node.data_path
        conf.wallet_dir = wallet_node.data_path
        conf.download_dir = wallet_node.data_path
        conf.upload_dir = upload_dir  # not a real conf setting
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
        wallet_node.manager.config = conf

        def wallet_maker(component_manager):
            wallet_component = WalletComponent(component_manager)
            wallet_component.wallet_manager = wallet_node.manager
            wallet_component._running = True
            return wallet_component

        daemon = Daemon(conf, ComponentManager(
            conf, skip_components=conf.components_to_skip, wallet=wallet_maker,
            exchange_rate_manager=partial(ExchangeRateManagerComponent, rates={
                'BTCLBC': 1.0, 'USDBTC': 2.0
            })
        ))
        await daemon.initialize()
        self.daemons.append(daemon)
        wallet_node.manager.old_db = daemon.storage
        return daemon

    async def confirm_tx(self, txid, ledger=None):
        """ Wait for tx to be in mempool, then generate a block, wait for tx to be in a block. """
        await self.on_transaction_id(txid, ledger)
        await self.generate(1)
        await self.on_transaction_id(txid, ledger)
        return txid

    async def on_transaction_dict(self, tx):
        await self.ledger.wait(Transaction(unhexlify(tx['hex'])))

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

    async def confirm_and_render(self, awaitable, confirm) -> Transaction:
        tx = await awaitable
        if confirm:
            await self.ledger.wait(tx)
            await self.generate(1)
            await self.ledger.wait(tx, self.blockchain.block_expected)
        return self.sout(tx)

    def create_upload_file(self, data, prefix=None, suffix=None):
        file_path = tempfile.mktemp(prefix=prefix or "tmp", suffix=suffix or "", dir=self.daemon.conf.upload_dir)
        with open(file_path, 'w+b') as file:
            file.write(data)
            file.flush()
            return file.name

    async def stream_create(
            self, name='hovercraft', bid='1.0', file_path=None,
            data=b'hi!', confirm=True, prefix=None, suffix=None, **kwargs):
        if file_path is None:
            file_path = self.create_upload_file(data=data, prefix=prefix, suffix=suffix)
        return await self.confirm_and_render(
            self.daemon.jsonrpc_stream_create(name, bid, file_path=file_path, **kwargs), confirm
        )

    async def stream_update(
            self, claim_id, data=None, prefix=None, suffix=None, confirm=True, **kwargs):
        if data is not None:
            file_path = self.create_upload_file(data=data, prefix=prefix, suffix=suffix)
            return await self.confirm_and_render(
                self.daemon.jsonrpc_stream_update(claim_id, file_path=file_path, **kwargs), confirm
            )
        return await self.confirm_and_render(
            self.daemon.jsonrpc_stream_update(claim_id, **kwargs), confirm
        )

    def stream_repost(self, claim_id, name='repost', bid='1.0', confirm=True, **kwargs):
        return self.confirm_and_render(
            self.daemon.jsonrpc_stream_repost(claim_id=claim_id, name=name, bid=bid, **kwargs), confirm
        )

    async def stream_abandon(self, *args, confirm=True, **kwargs):
        if 'blocking' not in kwargs:
            kwargs['blocking'] = False
        return await self.confirm_and_render(
            self.daemon.jsonrpc_stream_abandon(*args, **kwargs), confirm
        )

    async def publish(self, name, *args, confirm=True, **kwargs):
        return await self.confirm_and_render(
            self.daemon.jsonrpc_publish(name, *args, **kwargs), confirm
        )

    async def channel_create(self, name='@arena', bid='1.0', confirm=True, **kwargs):
        return await self.confirm_and_render(
            self.daemon.jsonrpc_channel_create(name, bid, **kwargs), confirm
        )

    async def channel_update(self, claim_id, confirm=True, **kwargs):
        return await self.confirm_and_render(
            self.daemon.jsonrpc_channel_update(claim_id, **kwargs), confirm
        )

    async def channel_abandon(self, *args, confirm=True, **kwargs):
        if 'blocking' not in kwargs:
            kwargs['blocking'] = False
        return await self.confirm_and_render(
            self.daemon.jsonrpc_channel_abandon(*args, **kwargs), confirm
        )

    async def collection_create(
            self, name='firstcollection', bid='1.0', confirm=True, **kwargs):
        return await self.confirm_and_render(
            self.daemon.jsonrpc_collection_create(name, bid, **kwargs), confirm
        )

    async def collection_update(
            self, claim_id, confirm=True, **kwargs):
        return await self.confirm_and_render(
            self.daemon.jsonrpc_collection_update(claim_id, **kwargs), confirm
        )

    async def collection_abandon(self, *args, confirm=True, **kwargs):
        if 'blocking' not in kwargs:
            kwargs['blocking'] = False
        return await self.confirm_and_render(
            self.daemon.jsonrpc_stream_abandon(*args, **kwargs), confirm
        )

    async def support_create(self, claim_id, bid='1.0', confirm=True, **kwargs):
        return await self.confirm_and_render(
            self.daemon.jsonrpc_support_create(claim_id, bid, **kwargs), confirm
        )

    async def resolve(self, uri):
        return await self.out(self.daemon.jsonrpc_resolve(uri))

    async def claim_search(self, **kwargs):
        return (await self.out(self.daemon.jsonrpc_claim_search(**kwargs)))['items']

    async def file_list(self, *args, **kwargs):
        return (await self.out(self.daemon.jsonrpc_file_list(*args, **kwargs)))['items']

    async def claim_list(self, *args, **kwargs):
        return (await self.out(self.daemon.jsonrpc_claim_list(*args, **kwargs)))['items']

    @staticmethod
    def get_claim_id(tx):
        return tx['outputs'][0]['claim_id']

    def assertItemCount(self, result, count):
        self.assertEqual(result['total_items'], count)
