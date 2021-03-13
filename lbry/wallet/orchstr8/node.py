import os
import json
import shutil
import asyncio
import zipfile
import tarfile
import logging
import tempfile
import subprocess
import importlib
from binascii import hexlify
from typing import Type, Optional
import urllib.request
from uuid import uuid4

import lbry
from lbry.wallet.server.server import Server
from lbry.wallet.server.env import Env
from lbry.wallet import Wallet, Ledger, RegTestLedger, WalletManager, Account, BlockHeightEvent


log = logging.getLogger(__name__)


def get_spvserver_from_ledger(ledger_module):
    spvserver_path, regtest_class_name = ledger_module.__spvserver__.rsplit('.', 1)
    spvserver_module = importlib.import_module(spvserver_path)
    return getattr(spvserver_module, regtest_class_name)


def get_blockchain_node_from_ledger(ledger_module):
    return BlockchainNode(
        ledger_module.__node_url__,
        os.path.join(ledger_module.__node_bin__, ledger_module.__node_daemon__),
        os.path.join(ledger_module.__node_bin__, ledger_module.__node_cli__)
    )


class Conductor:

    def __init__(self, seed=None):
        self.manager_module = WalletManager
        self.spv_module = get_spvserver_from_ledger(lbry.wallet)

        self.blockchain_node = get_blockchain_node_from_ledger(lbry.wallet)
        self.spv_node = SPVNode(self.spv_module)
        self.wallet_node = WalletNode(
            self.manager_module, RegTestLedger, default_seed=seed
        )

        self.blockchain_started = False
        self.spv_started = False
        self.wallet_started = False

        self.log = log.getChild('conductor')

    async def start_blockchain(self):
        if not self.blockchain_started:
            asyncio.create_task(self.blockchain_node.start())
            await self.blockchain_node.running.wait()
            await self.blockchain_node.generate(200)
            self.blockchain_started = True

    async def stop_blockchain(self):
        if self.blockchain_started:
            await self.blockchain_node.stop(cleanup=True)
            self.blockchain_started = False

    async def start_spv(self):
        if not self.spv_started:
            await self.spv_node.start(self.blockchain_node)
            self.spv_started = True

    async def stop_spv(self):
        if self.spv_started:
            await self.spv_node.stop(cleanup=True)
            self.spv_started = False

    async def start_wallet(self):
        if not self.wallet_started:
            await self.wallet_node.start(self.spv_node)
            self.wallet_started = True

    async def stop_wallet(self):
        if self.wallet_started:
            await self.wallet_node.stop(cleanup=True)
            self.wallet_started = False

    async def start(self):
        await self.start_blockchain()
        await self.start_spv()
        await self.start_wallet()

    async def stop(self):
        all_the_stops = [
            self.stop_wallet,
            self.stop_spv,
            self.stop_blockchain
        ]
        for stop in all_the_stops:
            try:
                await stop()
            except Exception as e:
                log.exception('Exception raised while stopping services:', exc_info=e)


class WalletNode:

    def __init__(self, manager_class: Type[WalletManager], ledger_class: Type[Ledger],
                 verbose: bool = False, port: int = 5280, default_seed: str = None) -> None:
        self.manager_class = manager_class
        self.ledger_class = ledger_class
        self.verbose = verbose
        self.manager: Optional[WalletManager] = None
        self.ledger: Optional[Ledger] = None
        self.wallet: Optional[Wallet] = None
        self.account: Optional[Account] = None
        self.data_path: Optional[str] = None
        self.port = port
        self.default_seed = default_seed

    async def start(self, spv_node: 'SPVNode', seed=None, connect=True):
        self.data_path = tempfile.mkdtemp()
        wallets_dir = os.path.join(self.data_path, 'wallets')
        os.mkdir(wallets_dir)
        wallet_file_name = os.path.join(wallets_dir, 'my_wallet.json')
        with open(wallet_file_name, 'w') as wallet_file:
            wallet_file.write('{"version": 1, "accounts": []}\n')
        self.manager = self.manager_class.from_config({
            'ledgers': {
                self.ledger_class.get_id(): {
                    'api_port': self.port,
                    'default_servers': [(spv_node.hostname, spv_node.port)],
                    'data_path': self.data_path,
                    'hub_timeout': 30,
                    'concurrent_hub_requests': 32,
                }
            },
            'wallets': [wallet_file_name]
        })
        self.ledger = self.manager.ledgers[self.ledger_class]
        self.wallet = self.manager.default_wallet
        if not self.wallet:
            raise ValueError('Wallet is required.')
        if seed or self.default_seed:
            Account.from_dict(
                self.ledger, self.wallet, {'seed': seed or self.default_seed}
            )
        else:
            self.wallet.generate_account(self.ledger)
        self.account = self.wallet.default_account
        if connect:
            await self.manager.start()

    async def stop(self, cleanup=True):
        try:
            await self.manager.stop()
        finally:
            cleanup and self.cleanup()

    def cleanup(self):
        shutil.rmtree(self.data_path, ignore_errors=True)


class SPVNode:

    def __init__(self, coin_class, node_number=1):
        self.coin_class = coin_class
        self.controller = None
        self.data_path = None
        self.server = None
        self.hostname = 'localhost'
        self.port = 50001 + node_number  # avoid conflict with default daemon
        self.udp_port = self.port
        self.session_timeout = 600
        self.rpc_port = '0'  # disabled by default

    async def start(self, blockchain_node: 'BlockchainNode', extraconf=None):
        self.data_path = tempfile.mkdtemp()
        conf = {
            'DESCRIPTION': '',
            'PAYMENT_ADDRESS': '',
            'DAILY_FEE': '0',
            'DB_DIRECTORY': self.data_path,
            'DAEMON_URL': blockchain_node.rpc_url,
            'REORG_LIMIT': '100',
            'HOST': self.hostname,
            'TCP_PORT': str(self.port),
            'UDP_PORT': str(self.udp_port),
            'SESSION_TIMEOUT': str(self.session_timeout),
            'MAX_QUERY_WORKERS': '0',
            'INDIVIDUAL_TAG_INDEXES': '',
            'RPC_PORT': self.rpc_port,
            'ES_INDEX_PREFIX': uuid4().hex,
            'ES_MODE': 'writer',
        }
        if extraconf:
            conf.update(extraconf)
        # TODO: don't use os.environ
        os.environ.update(conf)
        self.server = Server(Env(self.coin_class))
        self.server.mempool.refresh_secs = self.server.bp.prefetcher.polling_delay = 0.5
        await self.server.start()

    async def stop(self, cleanup=True):
        try:
            await self.server.db.search_index.delete_index()
            await self.server.db.search_index.stop()
            await self.server.stop()
        finally:
            cleanup and self.cleanup()

    def cleanup(self):
        shutil.rmtree(self.data_path, ignore_errors=True)


class BlockchainProcess(asyncio.SubprocessProtocol):

    IGNORE_OUTPUT = [
        b'keypool keep',
        b'keypool reserve',
        b'keypool return',
    ]

    def __init__(self):
        self.ready = asyncio.Event()
        self.stopped = asyncio.Event()
        self.log = log.getChild('blockchain')

    def pipe_data_received(self, fd, data):
        if self.log and not any(ignore in data for ignore in self.IGNORE_OUTPUT):
            if b'Error:' in data:
                self.log.error(data.decode())
            else:
                self.log.info(data.decode())
        if b'Error:' in data:
            self.ready.set()
            raise SystemError(data.decode())
        if b'Done loading' in data:
            self.ready.set()

    def process_exited(self):
        self.stopped.set()
        self.ready.set()


class BlockchainNode:

    P2SH_SEGWIT_ADDRESS = "p2sh-segwit"
    BECH32_ADDRESS = "bech32"

    def __init__(self, url, daemon, cli):
        self.latest_release_url = url
        self.project_dir = os.path.dirname(os.path.dirname(__file__))
        self.bin_dir = os.path.join(self.project_dir, 'bin')
        self.daemon_bin = os.path.join(self.bin_dir, daemon)
        self.cli_bin = os.path.join(self.bin_dir, cli)
        self.log = log.getChild('blockchain')
        self.data_path = None
        self.protocol = None
        self.transport = None
        self.block_expected = 0
        self.hostname = 'localhost'
        self.peerport = 9246 + 2  # avoid conflict with default peer port
        self.rpcport = 9245 + 2  # avoid conflict with default rpc port
        self.rpcuser = 'rpcuser'
        self.rpcpassword = 'rpcpassword'
        self.stopped = False
        self.restart_ready = asyncio.Event()
        self.restart_ready.set()
        self.running = asyncio.Event()

    @property
    def rpc_url(self):
        return f'http://{self.rpcuser}:{self.rpcpassword}@{self.hostname}:{self.rpcport}/'

    def is_expected_block(self, e: BlockHeightEvent):
        return self.block_expected == e.height

    @property
    def exists(self):
        return (
            os.path.exists(self.cli_bin) and
            os.path.exists(self.daemon_bin)
        )

    def download(self):
        downloaded_file = os.path.join(
            self.bin_dir,
            self.latest_release_url[self.latest_release_url.rfind('/')+1:]
        )

        if not os.path.exists(self.bin_dir):
            os.mkdir(self.bin_dir)

        if not os.path.exists(downloaded_file):
            self.log.info('Downloading: %s', self.latest_release_url)
            with urllib.request.urlopen(self.latest_release_url) as response:
                with open(downloaded_file, 'wb') as out_file:
                    shutil.copyfileobj(response, out_file)

        self.log.info('Extracting: %s', downloaded_file)

        if downloaded_file.endswith('.zip'):
            with zipfile.ZipFile(downloaded_file) as dotzip:
                dotzip.extractall(self.bin_dir)
                # zipfile bug https://bugs.python.org/issue15795
                os.chmod(self.cli_bin, 0o755)
                os.chmod(self.daemon_bin, 0o755)

        elif downloaded_file.endswith('.tar.gz'):
            with tarfile.open(downloaded_file) as tar:
                tar.extractall(self.bin_dir)

        return self.exists

    def ensure(self):
        return self.exists or self.download()

    async def start(self):
        assert self.ensure()
        self.data_path = tempfile.mkdtemp()
        loop = asyncio.get_event_loop()
        asyncio.get_child_watcher().attach_loop(loop)
        command = [
            self.daemon_bin,
            f'-datadir={self.data_path}', '-printtoconsole', '-regtest', '-server', '-txindex',
            f'-rpcuser={self.rpcuser}', f'-rpcpassword={self.rpcpassword}', f'-rpcport={self.rpcport}',
            f'-port={self.peerport}'
        ]
        self.log.info(' '.join(command))
        while not self.stopped:
            if self.running.is_set():
                await asyncio.sleep(1)
                continue
            await self.restart_ready.wait()
            try:
                self.transport, self.protocol = await loop.subprocess_exec(
                    BlockchainProcess, *command
                )
                await self.protocol.ready.wait()
                assert not self.protocol.stopped.is_set()
                self.running.set()
            except asyncio.CancelledError:
                self.running.clear()
                raise
            except Exception as e:
                self.running.clear()
                log.exception('failed to start lbrycrdd', exc_info=e)

    async def stop(self, cleanup=True):
        self.stopped = True
        try:
            self.transport.terminate()
            await self.protocol.stopped.wait()
            self.transport.close()
        finally:
            if cleanup:
                self.cleanup()

    async def clear_mempool(self):
        self.restart_ready.clear()
        self.transport.terminate()
        await self.protocol.stopped.wait()
        self.transport.close()
        self.running.clear()
        os.remove(os.path.join(self.data_path, 'regtest', 'mempool.dat'))
        self.restart_ready.set()
        await self.running.wait()

    def cleanup(self):
        shutil.rmtree(self.data_path, ignore_errors=True)

    async def _cli_cmnd(self, *args):
        cmnd_args = [
            self.cli_bin, f'-datadir={self.data_path}', '-regtest',
            f'-rpcuser={self.rpcuser}', f'-rpcpassword={self.rpcpassword}', f'-rpcport={self.rpcport}'
        ] + list(args)
        self.log.info(' '.join(cmnd_args))
        loop = asyncio.get_event_loop()
        asyncio.get_child_watcher().attach_loop(loop)
        process = await asyncio.create_subprocess_exec(
            *cmnd_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        out, _ = await process.communicate()
        result = out.decode().strip()
        self.log.info(result)
        if result.startswith('error code'):
            raise Exception(result)
        return result

    def generate(self, blocks):
        self.block_expected += blocks
        return self._cli_cmnd('generate', str(blocks))

    def invalidate_block(self, blockhash):
        return self._cli_cmnd('invalidateblock', blockhash)

    def get_block_hash(self, block):
        return self._cli_cmnd('getblockhash', str(block))

    def sendrawtransaction(self, tx):
        return self._cli_cmnd('sendrawtransaction', tx)

    async def get_block(self, block_hash):
        return json.loads(await self._cli_cmnd('getblock', block_hash, '1'))

    def get_raw_change_address(self):
        return self._cli_cmnd('getrawchangeaddress')

    def get_new_address(self, address_type):
        return self._cli_cmnd('getnewaddress', "", address_type)

    async def get_balance(self):
        return float(await self._cli_cmnd('getbalance'))

    def send_to_address(self, address, amount):
        return self._cli_cmnd('sendtoaddress', address, str(amount))

    def send_raw_transaction(self, tx):
        return self._cli_cmnd('sendrawtransaction', tx.decode())

    def create_raw_transaction(self, inputs, outputs):
        return self._cli_cmnd('createrawtransaction', json.dumps(inputs), json.dumps(outputs))

    async def sign_raw_transaction_with_wallet(self, tx):
        return json.loads(await self._cli_cmnd('signrawtransactionwithwallet', tx))['hex'].encode()

    def decode_raw_transaction(self, tx):
        return self._cli_cmnd('decoderawtransaction', hexlify(tx.raw).decode())

    def get_raw_transaction(self, txid):
        return self._cli_cmnd('getrawtransaction', txid, '1')
