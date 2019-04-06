import os
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

from torba.server.server import Server
from torba.server.env import Env
from torba.client.wallet import Wallet
from torba.client.baseledger import BaseLedger, BlockHeightEvent
from torba.client.basemanager import BaseWalletManager
from torba.client.baseaccount import BaseAccount


log = logging.getLogger(__name__)


def get_manager_from_environment(default_manager=BaseWalletManager):
    if 'TORBA_MANAGER' not in os.environ:
        return default_manager
    module_name = os.environ['TORBA_MANAGER'].split('-')[-1]  # tox support
    return importlib.import_module(module_name)


def get_ledger_from_environment():
    if 'TORBA_LEDGER' not in os.environ:
        raise ValueError('Environment variable TORBA_LEDGER must point to a torba based ledger module.')
    module_name = os.environ['TORBA_LEDGER'].split('-')[-1]  # tox support
    return importlib.import_module(module_name)


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


def set_logging(ledger_module, level, handler=None):
    modules = [
        'torba',
        'torba.client',
        'torba.server',
        'blockchain',
        ledger_module.__name__
    ]
    for module_name in modules:
        module = logging.getLogger(module_name)
        module.setLevel(level)
        if handler is not None:
            module.addHandler(handler)


class Conductor:

    def __init__(self, ledger_module=None, manager_module=None, verbosity=logging.WARNING):
        self.ledger_module = ledger_module or get_ledger_from_environment()
        self.manager_module = manager_module or get_manager_from_environment()
        self.spv_module = get_spvserver_from_ledger(self.ledger_module)

        self.blockchain_node = get_blockchain_node_from_ledger(self.ledger_module)
        self.spv_node = SPVNode(self.spv_module)
        self.wallet_node = WalletNode(self.manager_module, self.ledger_module.RegTestLedger)

        set_logging(self.ledger_module, verbosity)

        self.blockchain_started = False
        self.spv_started = False
        self.wallet_started = False

        self.log = log.getChild('conductor')

    async def start_blockchain(self):
        if not self.blockchain_started:
            await self.blockchain_node.start()
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

    def __init__(self, manager_class: Type[BaseWalletManager], ledger_class: Type[BaseLedger],
                 verbose: bool = False, port: int = 5280) -> None:
        self.manager_class = manager_class
        self.ledger_class = ledger_class
        self.verbose = verbose
        self.manager: Optional[BaseWalletManager] = None
        self.ledger: Optional[BaseLedger] = None
        self.wallet: Optional[Wallet] = None
        self.account: Optional[BaseAccount] = None
        self.data_path: Optional[str] = None
        self.port = port

    async def start(self, spv_node: 'SPVNode', seed=None, connect=True):
        self.data_path = tempfile.mkdtemp()
        wallet_file_name = os.path.join(self.data_path, 'my_wallet.json')
        with open(wallet_file_name, 'w') as wallet_file:
            wallet_file.write('{"version": 1, "accounts": []}\n')
        self.manager = self.manager_class.from_config({
            'ledgers': {
                self.ledger_class.get_id(): {
                    'api_port': self.port,
                    'default_servers': [(spv_node.hostname, spv_node.port)],
                    'data_path': self.data_path
                }
            },
            'wallets': [wallet_file_name]
        })
        self.ledger = self.manager.ledgers[self.ledger_class]
        self.wallet = self.manager.default_wallet
        if seed is None and self.wallet is not None:
            self.wallet.generate_account(self.ledger)
        elif self.wallet is not None:
            self.ledger.account_class.from_dict(
                self.ledger, self.wallet, {'seed': seed}
            )
        else:
            raise ValueError('Wallet is required.')
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

    def __init__(self, coin_class):
        self.coin_class = coin_class
        self.controller = None
        self.data_path = None
        self.server = None
        self.hostname = 'localhost'
        self.port = 50001 + 1  # avoid conflict with default daemon

    async def start(self, blockchain_node: 'BlockchainNode'):
        self.data_path = tempfile.mkdtemp()
        conf = {
            'DB_DIRECTORY': self.data_path,
            'DAEMON_URL': blockchain_node.rpc_url,
            'REORG_LIMIT': '100',
            'HOST': self.hostname,
            'TCP_PORT': str(self.port)
        }
        # TODO: don't use os.environ
        os.environ.update(conf)
        self.server = Server(Env(self.coin_class))
        self.server.mempool.refresh_secs = self.server.bp.prefetcher.polling_delay = 0.5
        await self.server.start()

    async def stop(self, cleanup=True):
        try:
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


class BlockchainNode:

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
        self._block_expected = 0
        self.hostname = 'localhost'
        self.peerport = 9246 + 2  # avoid conflict with default peer port
        self.rpcport = 9245 + 2  # avoid conflict with default rpc port
        self.rpcuser = 'rpcuser'
        self.rpcpassword = 'rpcpassword'

    @property
    def rpc_url(self):
        return f'http://{self.rpcuser}:{self.rpcpassword}@{self.hostname}:{self.rpcport}/'

    def is_expected_block(self, e: BlockHeightEvent):
        return self._block_expected == e.height

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
        command = (
            self.daemon_bin,
            f'-datadir={self.data_path}', '-printtoconsole', '-regtest', '-server', '-txindex',
            f'-rpcuser={self.rpcuser}', f'-rpcpassword={self.rpcpassword}', f'-rpcport={self.rpcport}',
            f'-port={self.peerport}'
        )
        self.log.info(' '.join(command))
        self.transport, self.protocol = await loop.subprocess_exec(
            BlockchainProcess, *command
        )
        await self.protocol.ready.wait()

    async def stop(self, cleanup=True):
        try:
            self.transport.terminate()
            await self.protocol.stopped.wait()
            self.transport.close()
        finally:
            if cleanup:
                self.cleanup()

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
        self.log.info(out.decode().strip())
        return out.decode().strip()

    def generate(self, blocks):
        self._block_expected += blocks
        return self._cli_cmnd('generate', str(blocks))

    def invalidateblock(self, blockhash):
        return self._cli_cmnd('invalidateblock', blockhash)

    def get_raw_change_address(self):
        return self._cli_cmnd('getrawchangeaddress')

    async def get_balance(self):
        return float(await self._cli_cmnd('getbalance'))

    def send_to_address(self, address, amount):
        return self._cli_cmnd('sendtoaddress', address, str(amount))

    def send_raw_transaction(self, tx):
        return self._cli_cmnd('sendrawtransaction', tx.decode())

    def decode_raw_transaction(self, tx):
        return self._cli_cmnd('decoderawtransaction', hexlify(tx.raw).decode())

    def get_raw_transaction(self, txid):
        return self._cli_cmnd('getrawtransaction', txid, '1')
