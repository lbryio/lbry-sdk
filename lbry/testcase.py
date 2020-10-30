# pylint: disable=attribute-defined-outside-init
import os
import sys
import json
import shutil
import hashlib
import logging
import tempfile
import functools
import asyncio
import time
from asyncio.runners import _cancel_all_tasks  # type: ignore
import unittest
from unittest.case import _Outcome
from typing import Optional, List, Union
from binascii import unhexlify, hexlify
from distutils.dir_util import remove_tree

import ecdsa

from lbry.db import Database
from lbry.blockchain import (
    RegTestLedger, Transaction, Input, Output, dewies_to_lbc
)
from lbry.blockchain.block import Block
from lbry.blockchain.bcd_data_stream import BCDataStream
from lbry.blockchain.lbrycrd import Lbrycrd
from lbry.blockchain.dewies import lbc_to_dewies
from lbry.constants import COIN, CENT, NULL_HASH32
from lbry.service import Daemon, FullNode, LightClient, jsonrpc_dumps_pretty
from lbry.conf import Config
from lbry.console import Console
from lbry.wallet import Wallet, Account
from lbry.schema.claim import Claim

from lbry.service.exchange_rate_manager import (
    ExchangeRateManager, ExchangeRate, LBRYFeed, LBRYBTCFeed
)


def get_output(amount=CENT, pubkey_hash=NULL_HASH32, height=-2):
    return Transaction(height=height) \
        .add_outputs([Output.pay_pubkey_hash(amount, pubkey_hash)]) \
        .outputs[0]


def get_input(amount=CENT, pubkey_hash=NULL_HASH32):
    return Input.spend(get_output(amount, pubkey_hash))


def get_transaction(txo=None):
    return Transaction() \
        .add_inputs([get_input()]) \
        .add_outputs([txo or Output.pay_pubkey_hash(CENT, NULL_HASH32)])


def get_claim_transaction(claim_name, claim=b''):
    return get_transaction(
        Output.pay_claim_name_pubkey_hash(CENT, claim_name, claim, NULL_HASH32)
    )


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

    LOOP_SLOW_CALLBACK_DURATION = 0.1

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


class UnitDBTestCase(AsyncioTestCase):

    async def asyncSetUp(self):
        await super().asyncSetUp()

        self.db = Database.temp_sqlite()
        self.addCleanup(self.db.close)
        await self.db.open()

        self.ledger = self.db.ledger
        self.conf = self.ledger.conf
        self.outputs: List[Output] = []
        self.current_height = 0

    async def add(self, block_or_tx: Union[Block, Transaction], block_hash: Optional[bytes] = None):
        if isinstance(block_or_tx, Block):
            await self.db.insert_block(block_or_tx)
            for tx in block_or_tx.txs:
                self.outputs.extend(tx.outputs)
            return block_or_tx
        elif isinstance(block_or_tx, Transaction):
            await self.db.insert_transaction(block_hash, block_or_tx)
            self.outputs.extend(block_or_tx.outputs)
            return block_or_tx.outputs[0]
        else:
            raise NotImplementedError(f"Can't add {type(block_or_tx)}.")

    def block(self, height: int, txs: List[Transaction]):
        self.current_height = height
        for tx in txs:
            tx.height = height
        return Block(
            height=height, version=1, file_number=0,
            block_hash=f'beef{height}'.encode(), prev_block_hash=f'beef{height-1}'.encode(),
            merkle_root=b'beef', claim_trie_root=b'beef',
            timestamp=99, bits=1, nonce=1, txs=txs
        )

    @staticmethod
    def coinbase():
        return (
            Transaction(height=0)
            .add_inputs([Input.create_coinbase()])
            .add_outputs([Output.pay_pubkey_hash(1000*COIN, (0).to_bytes(32, 'little'))])
        )

    def tx(self, amount='1.0', height=None, txi=None, txo=None):
        counter = len(self.outputs)
        self.current_height = height or (self.current_height+1)
        txis = [Input.spend(self.outputs[-1])]
        if txi is not None:
            txis.insert(0, txi)
        txo = txo or Output.pay_pubkey_hash(lbc_to_dewies(amount), counter.to_bytes(32, 'little'))
        change = (sum(txi.txo_ref.txo.amount for txi in txis) - txo.amount) - CENT
        assert change > 0
        return (
            Transaction(height=self.current_height)
            .add_inputs(txis)
            .add_outputs([
                txo,
                Output.pay_pubkey_hash(change, (counter + 1).to_bytes(32, 'little'))
            ])
        )

    def create_claim(self, claim_name='foo', claim=b'', amount='1.0', height=None):
        return self.tx(
            height=height,
            txo=Output.pay_claim_name_pubkey_hash(
                lbc_to_dewies(amount), claim_name, claim,
                len(self.outputs).to_bytes(32, 'little')
            )
        )

    def update_claim(self, txo, amount='1.0', height=None):
        return self.tx(
            height=height,
            txo=Output.pay_update_claim_pubkey_hash(
                lbc_to_dewies(amount), txo.claim_name, txo.claim_id, txo.claim,
                len(self.outputs).to_bytes(32, 'little')
            )
        )

    def support_claim(self, txo, amount='1.0', height=None):
        return self.tx(
            height=height,
            txo=Output.pay_support_pubkey_hash(
                lbc_to_dewies(amount), txo.claim_name, txo.claim_id,
                len(self.outputs).to_bytes(32, 'little')
            )
        )

    def repost_claim(self, claim_id, amount, channel):
        claim = Claim()
        claim.repost.reference.claim_id = claim_id
        result = self.create_claim('repost', claim, amount)
        if channel:
            result.outputs[0].sign(channel)
            result._reset()
        return result

    def abandon_claim(self, txo):
        return self.tx(amount='0.01', txi=Input.spend(txo))

    @staticmethod
    def _set_channel_key(channel, key):
        private_key = ecdsa.SigningKey.from_string(key*32, curve=ecdsa.SECP256k1, hashfunc=hashlib.sha256)
        channel.private_key = private_key
        channel.claim.channel.public_key_bytes = private_key.get_verifying_key().to_der()
        channel.script.generate()

    def create_channel(self, title, amount, name='@foo', key=b'a', **kwargs):
        claim = Claim()
        claim.stream.update(title=title, **kwargs)
        tx = self.create_claim(name, claim, amount)
        self._set_channel_key(tx.outputs[0], key)
        return tx

    def update_channel(self, channel, amount, key=b'a'):
        self._set_channel_key(channel, key)
        return self.update_claim(channel, amount)

    def create_stream(self, title, amount, name='foo', channel=None, **kwargs):
        claim = Claim()
        claim.stream.update(title=title, **kwargs)
        result = self.create_claim(name, claim, amount)
        if channel:
            result.outputs[0].sign(channel)
            result._reset()
        return result

    def update_stream(self, stream, amount, channel=None):
        result = self.update_claim(stream, amount)
        if channel:
            result.outputs[0].sign(channel)
            result._reset()
        return result

    async def get_txis(self):
        txis = []
        for txi in await self.db.execute_fetchall("select txo_hash, address from txi"):
            txoid = hexlify(txi["txo_hash"][:32][::-1]).decode()
            position, = BCDataStream.uint32.unpack(txi['txo_hash'][32:])
            txis.append((f'{txoid}:{position}', txi['address']))
        return txis

    async def get_txos(self):
        txos = []
        sql = (
            "select txo_hash, txo.position, spent_height from txo join tx using (tx_hash) "
            "order by tx.height, tx.position, txo.position"
        )
        for txo in await self.db.execute_fetchall(sql):
            txoid = hexlify(txo["txo_hash"][:32][::-1]).decode()
            txos.append((
                f"{txoid}:{txo['position']}",
                bool(txo['spent_height'])
            ))
        return txos

    async def get_claims(self):
        claims = []
        sql = (
            "select claim_id from claim order by height"
        )
        for claim in await self.db.execute_fetchall(sql):
            claims.append(claim['claim_id'])
        return claims


class IntegrationTestCase(AsyncioTestCase):

    SEED = None
    LBRYCRD_ARGS = '-rpcworkqueue=128',

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ledger: Optional[RegTestLedger] = None
        self.chain: Optional[Lbrycrd] = None
        self.block_expected = 0
        self.service = None
        self.api = None
        self.wallet: Optional[Wallet] = None
        self.account: Optional[Account] = None

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.chain = self.make_chain()
        await self.chain.ensure()
        self.addCleanup(self.chain.stop)
        await self.chain.start(*self.LBRYCRD_ARGS)

    @staticmethod
    def make_chain():
        return Lbrycrd.temp_regtest()

    async def make_db(self, chain):
        db_driver = os.environ.get('TEST_DB', 'sqlite')
        if db_driver == 'sqlite':
            db = Database.temp_sqlite_regtest(chain.ledger.conf)
        elif db_driver.startswith('postgres') or db_driver.startswith('psycopg'):
            db_driver = 'postgresql'
            db_name = 'lbry_test_chain'
            db_connection = 'postgres:postgres@localhost:5432'
            meta_db = Database.from_url(f'postgresql://{db_connection}/postgres')
            await meta_db.drop(db_name)
            await meta_db.create(db_name)
            db = Database.temp_from_url_regtest(
                f'postgresql://{db_connection}/{db_name}',
                chain.ledger.conf
            )
        else:
            raise RuntimeError(f"Unsupported database driver: {db_driver}")
        self.addCleanup(remove_tree, db.ledger.conf.data_dir)
        await db.open()
        self.addCleanup(db.close)
        self.db_driver = db_driver
        return db

    async def add_full_node(self, port):
        path = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, path, True)
        ledger = RegTestLedger(Config.with_same_dir(path).set(
            api=f'localhost:{port}',
            lbrycrd_dir=self.chain.ledger.conf.lbrycrd_dir,
            lbrycrd_rpc_port=self.chain.ledger.conf.lbrycrd_rpc_port,
            lbrycrd_peer_port=self.chain.ledger.conf.lbrycrd_peer_port,
            lbrycrd_zmq=self.chain.ledger.conf.lbrycrd_zmq
        ))
        service = FullNode(ledger)
        console = Console(service)
        daemon = Daemon(service, console)
        self.addCleanup(daemon.stop)
        await daemon.start()
        return daemon

    async def add_light_client(self, full_node, port, start=True):
        path = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, path, True)
        ledger = RegTestLedger(Config.with_same_dir(path).set(
            api=f'localhost:{port}',
            full_nodes=[(full_node.conf.api_host, full_node.conf.api_port)]
        ))
        service = LightClient(ledger)
        console = Console(service)
        daemon = Daemon(service, console)
        self.addCleanup(daemon.stop)
        if start:
            await daemon.start()
        return daemon

    @staticmethod
    def find_claim_txo(tx) -> Optional[Output]:
        for txo in tx.outputs:
            if txo.is_claim:
                return txo

    @staticmethod
    def find_support_txo(tx) -> Optional[Output]:
        for txo in tx.outputs:
            if txo.is_support:
                return txo

    async def assertBalance(self, account, expected_balance: str):  # pylint: disable=C0103
        balance = await account.get_balance()
        self.assertEqual(dewies_to_lbc(balance), expected_balance)

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

    def on_transaction_hash(self, tx_hash, ledger=None):
        return (ledger or self.ledger).on_transaction.where(
            lambda e: e.tx.hash == tx_hash
        )

    def on_address_update(self, address):
        return self.ledger.on_transaction.where(
            lambda e: e.address == address
        )

    def on_transaction_address(self, tx, address):
        return self.ledger.on_transaction.where(
            lambda e: e.tx.id == tx.id and e.address == address
        )


class FakeExchangeRateManager(ExchangeRateManager):

    def __init__(self, market_feeds, rates):  # pylint: disable=super-init-not-called
        self.market_feeds = market_feeds
        for feed in self.market_feeds:
            feed.last_check = time.time()
            feed.rate = ExchangeRate(feed.market, rates[feed.market], time.time())

    def start(self):
        pass

    def stop(self):
        pass


def get_fake_exchange_rate_manager(rates=None):
    return FakeExchangeRateManager(
        [LBRYFeed(), LBRYBTCFeed()],
        rates or {'BTCLBC': 3.0, 'USDBTC': 2.0}
    )


class CommandTestCase(IntegrationTestCase):

    VERBOSITY = logging.WARN
    blob_lru_cache_size = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.daemon_port = 5252
        self.daemon = None
        self.daemons = []
        self.server_config = None
        self.server_storage = None
        self.extra_wallet_nodes = []
        self.extra_wallet_node_port = 5281
        self.server_blob_manager = None
        self.server = None
        self.reflector = None

    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.generate(200, wait=False)

        self.daemon_port += 1
        self.full_node = self.daemon = await self.add_full_node(self.daemon_port)
        if os.environ.get('TEST_MODE', 'node') == 'client':
            self.daemon_port += 1
            self.daemon = await self.add_light_client(self.full_node, self.daemon_port)

        self.service = self.daemon.service
        self.ledger = self.service.ledger
        self.api = self.daemon.api

        self.wallet = self.service.wallets.default
        self.account = self.wallet.accounts.default
        address = await self.account.receiving.get_or_create_usable_address()

        self.ledger.conf.upload_dir = os.path.join(self.ledger.conf.data_dir, 'uploads')
        os.mkdir(self.ledger.conf.upload_dir)

        await self.chain.send_to_address(address, '10.0')
        await self.generate(5)

    async def asyncTearDown(self):
        await super().asyncTearDown()
        for wallet_node in self.extra_wallet_nodes:
            await wallet_node.stop(cleanup=True)
        for daemon in self.daemons:
            daemon.component_manager.get_component('wallet')._running = False
            await daemon.stop()

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

    def is_expected_block(self, event):
        return self.block_expected == event.height

    async def generate(self, blocks, wait=True):
        """ Ask lbrycrd to generate some blocks and wait until ledger has them. """
        await self.chain.generate(blocks)
        self.block_expected += blocks
        if wait:
            await self.service.sync.on_block.where(self.is_expected_block)

    async def out(self, awaitable):
        """ Serializes lbrynet API results to JSON then loads and returns it as dictionary. """
        return json.loads(jsonrpc_dumps_pretty(await awaitable, service=self.service))['result']

    def sout(self, value):
        """ Synchronous version of `out` method. """
        return json.loads(jsonrpc_dumps_pretty(value, service=self.service))['result']

    async def confirm_and_render(self, awaitable, confirm) -> Transaction:
        tx = await awaitable
        if confirm:
            await self.generate(1)
            await self.service.wait(tx)
        return self.sout(tx)

    async def wallet_list(self, *args, **kwargs):
        return (await self.out(self.api.wallet_list(*args, **kwargs)))['items']

    async def wallet_create(self, *args, **kwargs):
        return await self.out(self.api.wallet_create(*args, **kwargs))

    async def wallet_add(self, *args, **kwargs):
        return await self.out(self.api.wallet_add(*args, **kwargs))

    async def wallet_remove(self, *args, **kwargs):
        return await self.out(self.api.wallet_remove(*args, **kwargs))

    async def wallet_balance(self, *args, **kwargs):
        return await self.out(self.api.wallet_balance(*args, **kwargs))

    async def account_list(self, *args, **kwargs):
        return (await self.out(self.api.account_list(*args, **kwargs)))['items']

    async def account_create(self, *args, **kwargs):
        return await self.out(self.api.account_create(*args, **kwargs))

    async def account_add(self, *args, **kwargs):
        return await self.out(self.api.account_add(*args, **kwargs))

    async def account_set(self, *args, **kwargs):
        return await self.out(self.api.account_set(*args, **kwargs))

    async def account_remove(self, *args, **kwargs):
        return await self.out(self.api.account_remove(*args, **kwargs))

    async def account_send(self, *args, **kwargs):
        return await self.out(self.api.account_send(*args, **kwargs))

    async def account_balance(self, *args, **kwargs):
        return await self.out(self.api.account_balance(*args, **kwargs))

    async def address_unused(self, *args, **kwargs):
        return await self.out(self.api.address_unused(*args, **kwargs))

    def create_upload_file(self, data, prefix=None, suffix=None):
        file_path = tempfile.mktemp(
            prefix=prefix or "tmp", suffix=suffix or "", dir=self.ledger.conf.upload_dir
        )
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
            self.api.stream_create(name, bid, file_path=file_path, **kwargs), confirm
        )

    async def stream_update(
            self, claim_id, data=None, prefix=None, suffix=None, confirm=True, **kwargs):
        if data is not None:
            file_path = self.create_upload_file(data=data, prefix=prefix, suffix=suffix)
            return await self.confirm_and_render(
                self.api.stream_update(claim_id, file_path=file_path, **kwargs), confirm
            )
        return await self.confirm_and_render(
            self.api.stream_update(claim_id, **kwargs), confirm
        )

    async def stream_repost(self, claim_id, name='repost', bid='1.0', confirm=True, **kwargs):
        return await self.confirm_and_render(
            self.api.stream_repost(claim_id=claim_id, name=name, bid=bid, **kwargs), confirm
        )

    async def stream_abandon(self, *args, confirm=True, **kwargs):
        if 'blocking' not in kwargs:
            kwargs['blocking'] = False
        return await self.confirm_and_render(
            self.api.stream_abandon(*args, **kwargs), confirm
        )

    async def purchase_create(self, *args, confirm=True, **kwargs):
        return await self.confirm_and_render(
            self.api.purchase_create(*args, **kwargs), confirm
        )

    async def publish(self, name, *args, confirm=True, **kwargs):
        return await self.confirm_and_render(
            self.api.publish(name, *args, **kwargs), confirm
        )

    async def channel_create(self, name='@arena', bid='1.0', confirm=True, **kwargs):
        return await self.confirm_and_render(
            self.api.channel_create(name, bid, **kwargs), confirm
        )

    async def channel_update(self, claim_id, confirm=True, **kwargs):
        return await self.confirm_and_render(
            self.api.channel_update(claim_id, **kwargs), confirm
        )

    async def channel_abandon(self, *args, confirm=True, **kwargs):
        if 'blocking' not in kwargs:
            kwargs['blocking'] = False
        return await self.confirm_and_render(
            self.api.channel_abandon(*args, **kwargs), confirm
        )

    async def collection_create(
            self, name='firstcollection', bid='1.0', confirm=True, **kwargs):
        return await self.confirm_and_render(
            self.api.collection_create(name, bid, **kwargs), confirm
        )

    async def collection_update(
            self, claim_id, confirm=True, **kwargs):
        return await self.confirm_and_render(
            self.api.collection_update(claim_id, **kwargs), confirm
        )

    async def collection_abandon(self, *args, confirm=True, **kwargs):
        if 'blocking' not in kwargs:
            kwargs['blocking'] = False
        return await self.confirm_and_render(
            self.api.stream_abandon(*args, **kwargs), confirm
        )

    async def support_create(self, claim_id, bid='1.0', confirm=True, **kwargs):
        return await self.confirm_and_render(
            self.api.support_create(claim_id, bid, **kwargs), confirm
        )

    async def support_abandon(self, *args, confirm=True, **kwargs):
        return await self.confirm_and_render(
            self.api.support_abandon(*args, **kwargs), confirm
        )

    async def account_fund(self, *args, confirm=True, **kwargs):
        return await self.confirm_and_render(
            self.api.account_fund(*args, **kwargs), confirm
        )

    async def account_send(self, *args, confirm=True, **kwargs):
        return await self.confirm_and_render(
            self.api.account_send(*args, **kwargs), confirm
        )

    async def wallet_send(self, *args, confirm=True, **kwargs):
        return await self.confirm_and_render(
            self.api.wallet_send(*args, **kwargs), confirm
        )

    async def txo_spend(self, *args, confirm=True, **kwargs):
        txs = await self.api.txo_spend(*args, **kwargs)
        if confirm:
            await asyncio.wait([self.ledger.wait(tx) for tx in txs])
            await self.generate(1)
            await asyncio.wait([self.ledger.wait(tx, self.block_expected) for tx in txs])
        return self.sout(txs)

    async def resolve(self, uri, **kwargs):
        return (await self.out(self.api.resolve(uri, **kwargs)))[uri]

    async def claim_search(self, **kwargs):
        return (await self.out(self.api.claim_search(**kwargs)))['items']

    async def file_list(self, *args, **kwargs):
        return (await self.out(self.api.file_list(*args, **kwargs)))['items']

    async def txo_list(self, *args, **kwargs):
        return (await self.out(self.api.txo_list(*args, **kwargs)))['items']

    async def txo_sum(self, *args, **kwargs):
        return await self.out(self.api.txo_sum(*args, **kwargs))

    async def txo_plot(self, *args, **kwargs):
        return await self.out(self.api.txo_plot(*args, **kwargs))

    async def claim_list(self, *args, **kwargs):
        return (await self.out(self.api.claim_list(*args, **kwargs)))['items']

    async def stream_list(self, *args, **kwargs):
        return (await self.out(self.api.stream_list(*args, **kwargs)))['items']

    async def channel_list(self, *args, **kwargs):
        return (await self.out(self.api.channel_list(*args, **kwargs)))['items']

    async def collection_list(self, *args, **kwargs):
        return (await self.out(self.api.collection_list(*args, **kwargs)))['items']

    async def collection_resolve(self, *args, **kwargs):
        return (await self.out(self.api.collection_resolve(*args, **kwargs)))['items']

    async def transaction_list(self, *args, **kwargs):
        return (await self.out(self.api.transaction_list(*args, **kwargs)))['items']

    @staticmethod
    def get_claim_id(tx):
        return tx['outputs'][0]['claim_id']

    @staticmethod
    def get_address(tx):
        return tx['outputs'][0]['address']


class EventGenerator:

    def __init__(
        self, initial_sync=False, start=None, end=None, block_files=None, claims=None,
        takeovers=None, stakes=0, supports=None
    ):
        self.initial_sync = initial_sync
        self.block_files = block_files or []
        self.claims = claims or []
        self.takeovers = takeovers or []
        self.stakes = stakes
        self.supports = supports or []
        self.start_height = start
        self.end_height = end

    @property
    def events(self):
        yield from self.blocks_init()
        if self.block_files:
            yield from self.blocks_main_start()
            for block_file in self.block_files:
                yield from self.blocks_file(*block_file)
            if self.initial_sync:
                yield from self.blocks_indexes()
            else:
                yield from self.blocks_vacuum()
            yield from self.blocks_main_finish()
            yield from self.spends_steps()

        yield from self.filters_init()
        if self.block_files:
            yield from self.filters_main_start()
            yield from self.filters_generate()
            if self.initial_sync:
                yield from self.filters_indexes()
            else:
                yield from self.filters_vacuum()
            yield from self.filters_main_finish()

        if self.claims:
            if not self.initial_sync:
                yield from self.claims_init()
            yield from self.claims_main_start()
            yield from self.claims_insert(self.claims)
            if self.initial_sync:
                yield from self.generate("blockchain.sync.claims.indexes", ("steps",), 0, None, (10,), (1,))
            else:
                yield from self.claims_takeovers(self.takeovers)
                yield from self.claims_stakes()
                yield from self.claims_vacuum()
            yield from self.claims_main_finish()

        if self.supports:
            if not self.initial_sync:
                yield from self.supports_init()
            yield from self.supports_main_start()
            yield from self.supports_insert(self.supports)
            if self.initial_sync:
                yield from self.generate("blockchain.sync.supports.indexes", ("steps",), 0, None, (3,), (1,))
            else:
                yield from self.supports_vacuum()
            yield from self.supports_main_finish()

    def blocks_init(self):
        yield from self.generate("blockchain.sync.blocks.init", ("steps",), 0, None, (3,), (1,))

    def blocks_main_start(self):
        files = len(self.block_files)
        blocks = sum([bf[1] for bf in self.block_files])
        txs = sum([bf[2] for bf in self.block_files])
        claims = sum([c[2] for c in self.claims])
        supports = sum([c[2] for c in self.supports])
        yield {
            "event": "blockchain.sync.blocks.main",
            "data": {
                "id": 0, "done": (0, 0), "total": (blocks, txs), "units": ("blocks", "txs"),
                "starting_height": self.start_height, "ending_height": self.end_height,
                "files": files, "claims": claims, "supports": supports
            }
        }

    @staticmethod
    def blocks_main_finish():
        yield {
            "event": "blockchain.sync.blocks.main",
            "data": {"id": 0, "done": (-1, -1)}
        }

    def blocks_files(self, files):
        for file in files:
            yield from self.blocks_file(*file)

    @staticmethod
    def blocks_file(file, blocks, txs, steps):
        for i, step in enumerate(steps):
            if i == 0:
                yield {
                    "event": "blockchain.sync.blocks.file",
                    "data": {
                        "id": file,
                        "done": (0, 0),
                        "total": (blocks, txs),
                        "units": ("blocks", "txs"),
                        "label": f"blk0000{file}.dat",
                    }
                }
            yield {
                "event": "blockchain.sync.blocks.file",
                "data": {"id": file, "done": step}
            }

    def blocks_indexes(self):
        yield from self.generate(
            "blockchain.sync.blocks.indexes", ("steps",), 0, None, (2,), (1,)
        )

    def blocks_vacuum(self):
        yield from self.generate(
            "blockchain.sync.blocks.vacuum", ("steps",), 0, None, (1,), (1,)
        )

    def filters_init(self):
        yield from self.generate("blockchain.sync.filters.init", ("steps",), 0, None, (2,), (1,))

    def filters_main_start(self):
        yield {
            "event": "blockchain.sync.filters.main",
            "data": {
                "id": 0, "done": (0,),
                "total": ((self.end_height-self.start_height)+1,),
                "units": ("blocks",)}
        }

    @staticmethod
    def filters_main_finish():
        yield {
            "event": "blockchain.sync.filters.main",
            "data": {"id": 0, "done": (-1,)}
        }

    def filters_generate(self):
        #yield from self.generate(
        #    "blockchain.sync.filters.generate", ("blocks",), 0,
        #    f"generate filters 0-{blocks-1}", (blocks,), (100,)
        #)
        blocks = (self.end_height-self.start_height)+1
        yield {
            "event": "blockchain.sync.filters.generate",
            "data": {
                "id": self.start_height, "done": (0,),
                "total": (blocks,),
                "units": ("blocks",),
                "label": f"generate filters {self.start_height}-{self.end_height}",
            }
        }
        yield {
            "event": "blockchain.sync.filters.generate",
            "data": {"id": self.start_height, "done": (blocks,)}
        }

    def filters_indexes(self):
        yield from self.generate(
            "blockchain.sync.filters.indexes", ("steps",), 0, None, (6,), (1,)
        )

    def filters_vacuum(self):
        yield from self.generate(
            "blockchain.sync.filters.vacuum", ("steps",), 0, None, (2,), (1,)
        )

    def spends_steps(self):
        yield from self.generate(
            "blockchain.sync.spends.main", ("steps",), 0, None,
            (20 if self.initial_sync else 5,),
            (1,)
        )

    def claims_init(self):
        yield from self.generate("blockchain.sync.claims.init", ("steps",), 0, None, (5,), (1,))

    def claims_main_start(self):
        total = (
            sum([c[2] for c in self.claims]) +
            sum([c[2] for c in self.takeovers]) +
            self.stakes
        )
        yield {
            "event": "blockchain.sync.claims.main",
            "data": {
                "id": 0, "done": (0,),
                "total": (total,),
                "units": ("claims",)}
        }

    @staticmethod
    def claims_main_finish():
        yield {
            "event": "blockchain.sync.claims.main",
            "data": {"id": 0, "done": (-1,)}
        }

    def claims_insert(self, heights):
        for start, end, total, count in heights:
            yield from self.generate(
                "blockchain.sync.claims.insert", ("claims",), start,
                f"add claims    {start}-   {end}", (total,), (count,)
            )

    def claims_takeovers(self, heights):
        for start, end, total, count in heights:
            yield from self.generate(
                "blockchain.sync.claims.takeovers", ("claims",), 0,
                f"mod winner    {start}-   {end}", (total,), (count,)
            )

    def claims_stakes(self):
        yield from self.generate(
            "blockchain.sync.claims.stakes", ("claims",), 0, None, (self.stakes,), (self.stakes,)
        )

    def claims_vacuum(self):
        yield from self.generate(
            "blockchain.sync.claims.vacuum", ("steps",), 0, None, (2,), (1,)
        )

    def supports_init(self):
        yield from self.generate("blockchain.sync.supports.init", ("steps",), 0, None, (2,), (1,))

    def supports_main_start(self):
        yield {
            "event": "blockchain.sync.supports.main",
            "data": {
                "id": 0, "done": (0,),
                "total": (sum([c[2] for c in self.supports]),),
                "units": ("supports",)
            }
        }

    @staticmethod
    def supports_main_finish():
        yield {
            "event": "blockchain.sync.supports.main",
            "data": {"id": 0, "done": (-1,)}
        }

    def supports_insert(self, heights):
        for start, end, total, count in heights:
            yield from self.generate(
                "blockchain.sync.supports.insert", ("supports",), start,
                f"add supprt    {start}" if start == end else f"add supprt    {start}-   {end}",
                (total,), (count,)
            )

    def supports_vacuum(self):
        yield from self.generate(
            "blockchain.sync.supports.vacuum", ("steps",), 0, None, (1,), (1,)
        )

    @staticmethod
    def generate(name, units, eid, label, total, steps):
        done = (0,)*len(total)
        while not all(d >= t for d, t in zip(done, total)):
            if done[0] == 0:
                first_event = {
                    "event": name,
                    "data": {
                        "id": eid,
                        "done": done,
                        "total": total,
                        "units": units,
                    }
                }
                if label is not None:
                    first_event["data"]["label"] = label
                yield first_event
            done = tuple(min(d+s, t) for d, s, t in zip(done, steps, total))
            yield {
                "event": name,
                "data": {
                    "id": eid,
                    "done": done,
                }
            }
