# pylint: disable=import-error
import os
import json
import shutil
import asyncio
import zipfile
import tarfile
import logging
import tempfile
import subprocess
import platform

from binascii import hexlify
from typing import Type, Optional
import urllib.request
from uuid import uuid4


import lbry
from lbry.wallet import Wallet, Ledger, RegTestLedger, WalletManager, Account, BlockHeightEvent
from lbry.conf import KnownHubsList, Config

log = logging.getLogger(__name__)

try:
    from hub.herald.env import ServerEnv
    from hub.scribe.env import BlockchainEnv
    from hub.elastic_sync.env import ElasticEnv
    from hub.herald.service import HubServerService
    from hub.elastic_sync.service import ElasticSyncService
    from hub.scribe.service import BlockchainProcessorService
except ImportError:
    pass


def get_lbcd_node_from_ledger(ledger_module):
    return LBCDNode(
        ledger_module.__lbcd_url__,
        ledger_module.__lbcd__,
        ledger_module.__lbcctl__
    )


def get_lbcwallet_node_from_ledger(ledger_module):
    return LBCWalletNode(
        ledger_module.__lbcwallet_url__,
        ledger_module.__lbcwallet__,
        ledger_module.__lbcctl__
    )


class Conductor:

    def __init__(self, seed=None):
        self.manager_module = WalletManager
        self.lbcd_node = get_lbcd_node_from_ledger(lbry.wallet)
        self.lbcwallet_node = get_lbcwallet_node_from_ledger(lbry.wallet)
        self.spv_node = SPVNode()
        self.wallet_node = WalletNode(
            self.manager_module, RegTestLedger, default_seed=seed
        )
        self.lbcd_started = False
        self.lbcwallet_started = False
        self.spv_started = False
        self.wallet_started = False

        self.log = log.getChild('conductor')

    async def start_lbcd(self):
        if not self.lbcd_started:
            await self.lbcd_node.start()
            self.lbcd_started = True

    async def stop_lbcd(self, cleanup=True):
        if self.lbcd_started:
            await self.lbcd_node.stop(cleanup)
            self.lbcd_started = False

    async def start_spv(self):
        if not self.spv_started:
            await self.spv_node.start(self.lbcwallet_node)
            self.spv_started = True

    async def stop_spv(self, cleanup=True):
        if self.spv_started:
            await self.spv_node.stop(cleanup)
            self.spv_started = False

    async def start_wallet(self):
        if not self.wallet_started:
            await self.wallet_node.start(self.spv_node)
            self.wallet_started = True

    async def stop_wallet(self, cleanup=True):
        if self.wallet_started:
            await self.wallet_node.stop(cleanup)
            self.wallet_started = False

    async def start_lbcwallet(self, clean=True):
        if not self.lbcwallet_started:
            await self.lbcwallet_node.start()
            if clean:
                mining_addr = await self.lbcwallet_node.get_new_address()
                self.lbcwallet_node.mining_addr = mining_addr
                await self.lbcwallet_node.generate(200)
            # unlock the wallet for the next 1 hour
            await self.lbcwallet_node.wallet_passphrase("password", 3600)
            self.lbcwallet_started = True

    async def stop_lbcwallet(self, cleanup=True):
        if self.lbcwallet_started:
            await self.lbcwallet_node.stop(cleanup)
            self.lbcwallet_started = False

    async def start(self):
        await self.start_lbcd()
        await self.start_lbcwallet()
        await self.start_spv()
        await self.start_wallet()

    async def stop(self):
        all_the_stops = [
            self.stop_wallet,
            self.stop_spv,
            self.stop_lbcwallet,
            self.stop_lbcd
        ]
        for stop in all_the_stops:
            try:
                await stop()
            except Exception as e:
                log.exception('Exception raised while stopping services:', exc_info=e)

    async def clear_mempool(self):
        await self.stop_lbcwallet(cleanup=False)
        await self.stop_lbcd(cleanup=False)
        await self.start_lbcd()
        await self.start_lbcwallet(clean=False)


class WalletNode:

    def __init__(self, manager_class: Type[WalletManager], ledger_class: Type[Ledger],
                 verbose: bool = False, port: int = 5280, default_seed: str = None,
                 data_path: str = None) -> None:
        self.manager_class = manager_class
        self.ledger_class = ledger_class
        self.verbose = verbose
        self.manager: Optional[WalletManager] = None
        self.ledger: Optional[Ledger] = None
        self.wallet: Optional[Wallet] = None
        self.account: Optional[Account] = None
        self.data_path: str = data_path or tempfile.mkdtemp()
        self.port = port
        self.default_seed = default_seed
        self.known_hubs = KnownHubsList()

    async def start(self, spv_node: 'SPVNode', seed=None, connect=True, config=None):
        wallets_dir = os.path.join(self.data_path, 'wallets')
        wallet_file_name = os.path.join(wallets_dir, 'my_wallet.json')
        if not os.path.isdir(wallets_dir):
            os.mkdir(wallets_dir)
            with open(wallet_file_name, 'w') as wallet_file:
                wallet_file.write('{"version": 1, "accounts": []}\n')
        self.manager = self.manager_class.from_config({
            'ledgers': {
                self.ledger_class.get_id(): {
                    'api_port': self.port,
                    'explicit_servers': [(spv_node.hostname, spv_node.port)],
                    'default_servers': Config.lbryum_servers.default,
                    'data_path': self.data_path,
                    'known_hubs': config.known_hubs if config else KnownHubsList(),
                    'hub_timeout': 30,
                    'concurrent_hub_requests': 32,
                    'fee_per_name_char': 200000
                }
            },
            'wallets': [wallet_file_name]
        })
        self.manager.config = config
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
    def __init__(self, node_number=1):
        self.node_number = node_number
        self.controller = None
        self.data_path = None
        self.server: Optional[HubServerService] = None
        self.writer: Optional[BlockchainProcessorService] = None
        self.es_writer: Optional[ElasticSyncService] = None
        self.hostname = 'localhost'
        self.port = 50001 + node_number  # avoid conflict with default daemon
        self.udp_port = self.port
        self.elastic_notifier_port = 19080 + node_number
        self.session_timeout = 600
        self.stopped = True
        self.index_name = uuid4().hex

    async def start(self, lbcwallet_node: 'LBCWalletNode', extraconf=None):
        if not self.stopped:
            log.warning("spv node is already running")
            return
        self.stopped = False
        try:
            self.data_path = tempfile.mkdtemp()
            conf = {
                'description': '',
                'payment_address': '',
                'daily_fee': '0',
                'db_dir': self.data_path,
                'daemon_url': lbcwallet_node.rpc_url,
                'reorg_limit': 100,
                'host': self.hostname,
                'tcp_port': self.port,
                'udp_port': self.udp_port,
                'elastic_notifier_port': self.elastic_notifier_port,
                'session_timeout': self.session_timeout,
                'max_query_workers': 0,
                'es_index_prefix': self.index_name,
                'chain': 'regtest',
                'index_address_status': False
            }
            if extraconf:
                conf.update(extraconf)
            self.writer = BlockchainProcessorService(
                BlockchainEnv(db_dir=self.data_path, daemon_url=lbcwallet_node.rpc_url,
                              reorg_limit=100, max_query_workers=0, chain='regtest', index_address_status=False)
            )
            self.server = HubServerService(ServerEnv(**conf))
            self.es_writer = ElasticSyncService(
                ElasticEnv(
                    db_dir=self.data_path, reorg_limit=100, max_query_workers=0, chain='regtest',
                    elastic_notifier_port=self.elastic_notifier_port,
                    es_index_prefix=self.index_name,
                    filtering_channel_ids=(extraconf or {}).get('filtering_channel_ids'),
                    blocking_channel_ids=(extraconf or {}).get('blocking_channel_ids')
                )
            )
            await self.writer.start()
            await self.es_writer.start()
            await self.server.start()
        except Exception as e:
            self.stopped = True
            if not isinstance(e, asyncio.CancelledError):
                log.exception("failed to start spv node")
            raise e

    async def stop(self, cleanup=True):
        if self.stopped:
            log.warning("spv node is already stopped")
            return
        try:
            await self.server.stop()
            await self.es_writer.delete_index()
            await self.es_writer.stop()
            await self.writer.stop()
            self.stopped = True
        except Exception as e:
            log.exception("failed to stop spv node")
            raise e
        finally:
            cleanup and self.cleanup()

    def cleanup(self):
        shutil.rmtree(self.data_path, ignore_errors=True)


class LBCDProcess(asyncio.SubprocessProtocol):

    IGNORE_OUTPUT = [
        b'keypool keep',
        b'keypool reserve',
        b'keypool return',
        b'Block submitted',
    ]

    def __init__(self):
        self.ready = asyncio.Event()
        self.stopped = asyncio.Event()
        self.log = log.getChild('lbcd')

    def pipe_data_received(self, fd, data):
        if self.log and not any(ignore in data for ignore in self.IGNORE_OUTPUT):
            if b'Error:' in data:
                self.log.error(data.decode())
            else:
                self.log.info(data.decode())
        if b'Error:' in data:
            self.ready.set()
            raise SystemError(data.decode())
        if b'RPCS: RPC server listening on' in data:
            self.ready.set()

    def process_exited(self):
        self.stopped.set()
        self.ready.set()


class WalletProcess(asyncio.SubprocessProtocol):

    IGNORE_OUTPUT = [
    ]

    def __init__(self):
        self.ready = asyncio.Event()
        self.stopped = asyncio.Event()
        self.log = log.getChild('lbcwallet')
        self.transport: Optional[asyncio.transports.SubprocessTransport] = None

    def pipe_data_received(self, fd, data):
        if self.log and not any(ignore in data for ignore in self.IGNORE_OUTPUT):
            if b'Error:' in data:
                self.log.error(data.decode())
            else:
                self.log.info(data.decode())
        if b'Error:' in data:
            self.ready.set()
            raise SystemError(data.decode())
        if b'WLLT: Finished rescan' in data:
            self.ready.set()

    def process_exited(self):
        self.stopped.set()
        self.ready.set()


class LBCDNode:
    def __init__(self, url, daemon, cli):
        self.latest_release_url = url
        self.project_dir = os.path.dirname(os.path.dirname(__file__))
        self.bin_dir = os.path.join(self.project_dir, 'bin')
        self.daemon_bin = os.path.join(self.bin_dir, daemon)
        self.cli_bin = os.path.join(self.bin_dir, cli)
        self.log = log.getChild('lbcd')
        self.data_path = tempfile.mkdtemp()
        self.protocol = None
        self.transport = None
        self.hostname = 'localhost'
        self.peerport = 29246
        self.rpcport = 29245
        self.rpcuser = 'rpcuser'
        self.rpcpassword = 'rpcpassword'
        self.stopped = True
        self.running = asyncio.Event()

    @property
    def rpc_url(self):
        return f'http://{self.rpcuser}:{self.rpcpassword}@{self.hostname}:{self.rpcport}/'

    @property
    def exists(self):
        return (
            os.path.exists(self.cli_bin) and
            os.path.exists(self.daemon_bin)
        )

    def download(self):
        uname = platform.uname()
        target_os = str.lower(uname.system)
        target_arch = str.replace(uname.machine, 'x86_64', 'amd64')
        target_platform = target_os + '_' + target_arch
        self.latest_release_url = str.replace(self.latest_release_url, 'TARGET_PLATFORM', target_platform)

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
        if not self.stopped:
            return
        self.stopped = False
        try:
            assert self.ensure()
            loop = asyncio.get_event_loop()
            asyncio.get_child_watcher().attach_loop(loop)
            command = [
                self.daemon_bin,
                '--notls',
                f'--datadir={self.data_path}',
                '--regtest', f'--listen=127.0.0.1:{self.peerport}', f'--rpclisten=127.0.0.1:{self.rpcport}',
                '--txindex', f'--rpcuser={self.rpcuser}', f'--rpcpass={self.rpcpassword}'
            ]
            self.log.info(' '.join(command))
            self.transport, self.protocol = await loop.subprocess_exec(
                LBCDProcess, *command
            )
            await self.protocol.ready.wait()
            assert not self.protocol.stopped.is_set()
            self.running.set()
        except asyncio.CancelledError:
            self.running.clear()
            self.stopped = True
            raise
        except Exception as e:
            self.running.clear()
            self.stopped = True
            log.exception('failed to start lbcd', exc_info=e)
            raise

    async def stop(self, cleanup=True):
        if self.stopped:
            return
        try:
            if self.transport:
                self.transport.terminate()
                await self.protocol.stopped.wait()
                self.transport.close()
        except Exception as e:
            log.exception('failed to stop lbcd', exc_info=e)
            raise
        finally:
            self.log.info("Done shutting down " + self.daemon_bin)
            self.stopped = True
            if cleanup:
                self.cleanup()
            self.running.clear()

    def cleanup(self):
        assert self.stopped
        shutil.rmtree(self.data_path, ignore_errors=True)


class LBCWalletNode:
    P2SH_SEGWIT_ADDRESS = "p2sh-segwit"
    BECH32_ADDRESS = "bech32"

    def __init__(self, url, lbcwallet, cli):
        self.latest_release_url = url
        self.project_dir = os.path.dirname(os.path.dirname(__file__))
        self.bin_dir = os.path.join(self.project_dir, 'bin')
        self.lbcwallet_bin = os.path.join(self.bin_dir, lbcwallet)
        self.cli_bin = os.path.join(self.bin_dir, cli)
        self.log = log.getChild('lbcwallet')
        self.protocol = None
        self.transport = None
        self.hostname = 'localhost'
        self.lbcd_rpcport = 29245
        self.lbcwallet_rpcport = 29244
        self.rpcuser = 'rpcuser'
        self.rpcpassword = 'rpcpassword'
        self.data_path = tempfile.mkdtemp()
        self.stopped = True
        self.running = asyncio.Event()
        self.block_expected = 0
        self.mining_addr = ''

    @property
    def rpc_url(self):
        # FIXME: somehow the hub/sdk doesn't learn the blocks through the Walet RPC port, why?
        # return f'http://{self.rpcuser}:{self.rpcpassword}@{self.hostname}:{self.lbcwallet_rpcport}/'
        return f'http://{self.rpcuser}:{self.rpcpassword}@{self.hostname}:{self.lbcd_rpcport}/'

    def is_expected_block(self, e: BlockHeightEvent):
        return self.block_expected == e.height

    @property
    def exists(self):
        return (
            os.path.exists(self.lbcwallet_bin)
        )

    def download(self):
        uname = platform.uname()
        target_os = str.lower(uname.system)
        target_arch = str.replace(uname.machine, 'x86_64', 'amd64')
        target_platform = target_os + '_' + target_arch
        self.latest_release_url = str.replace(self.latest_release_url, 'TARGET_PLATFORM', target_platform)

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
                os.chmod(self.lbcwallet_bin, 0o755)

        elif downloaded_file.endswith('.tar.gz'):
            with tarfile.open(downloaded_file) as tar:
                tar.extractall(self.bin_dir)

        return self.exists

    def ensure(self):
        return self.exists or self.download()

    async def start(self):
        assert self.ensure()
        loop = asyncio.get_event_loop()
        asyncio.get_child_watcher().attach_loop(loop)

        command = [
            self.lbcwallet_bin,
            '--noservertls', '--noclienttls',
            '--regtest',
            f'--rpcconnect=127.0.0.1:{self.lbcd_rpcport}', f'--rpclisten=127.0.0.1:{self.lbcwallet_rpcport}',
            '--createtemp', f'--appdata={self.data_path}',
            f'--username={self.rpcuser}', f'--password={self.rpcpassword}'
        ]
        self.log.info(' '.join(command))
        try:
            self.transport, self.protocol = await loop.subprocess_exec(
                WalletProcess, *command
            )
            self.protocol.transport = self.transport
            await self.protocol.ready.wait()
            assert not self.protocol.stopped.is_set()
            self.running.set()
            self.stopped = False
        except asyncio.CancelledError:
            self.running.clear()
            raise
        except Exception as e:
            self.running.clear()
            log.exception('failed to start lbcwallet', exc_info=e)

    def cleanup(self):
        assert self.stopped
        shutil.rmtree(self.data_path, ignore_errors=True)

    async def stop(self, cleanup=True):
        if self.stopped:
            return
        try:
            self.transport.terminate()
            await self.protocol.stopped.wait()
            self.transport.close()
        except Exception as e:
            log.exception('failed to stop lbcwallet', exc_info=e)
            raise
        finally:
            self.log.info("Done shutting down " + self.lbcwallet_bin)
            self.stopped = True
            if cleanup:
                self.cleanup()
            self.running.clear()

    async def _cli_cmnd(self, *args):
        cmnd_args = [
            self.cli_bin,
            f'--rpcuser={self.rpcuser}', f'--rpcpass={self.rpcpassword}', '--notls', '--regtest', '--wallet'
        ] + list(args)
        self.log.info(' '.join(cmnd_args))
        loop = asyncio.get_event_loop()
        asyncio.get_child_watcher().attach_loop(loop)
        process = await asyncio.create_subprocess_exec(
            *cmnd_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        out, err = await process.communicate()
        result = out.decode().strip()
        err = err.decode().strip()
        if len(result) <= 0 and err.startswith('-'):
            raise Exception(err)
        if err and 'creating a default config file' not in err:
            log.warning(err)
        self.log.info(result)
        if result.startswith('error code'):
            raise Exception(result)
        return result

    def generate(self, blocks):
        self.block_expected += blocks
        return self._cli_cmnd('generatetoaddress', str(blocks), self.mining_addr)

    def generate_to_address(self, blocks, addr):
        self.block_expected += blocks
        return self._cli_cmnd('generatetoaddress', str(blocks), addr)

    def wallet_passphrase(self, passphrase, timeout):
        return self._cli_cmnd('walletpassphrase', passphrase, str(timeout))

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

    def get_new_address(self, address_type='legacy'):
        return self._cli_cmnd('getnewaddress', "", address_type)

    async def get_balance(self):
        return await self._cli_cmnd('getbalance')

    def send_to_address(self, address, amount):
        return self._cli_cmnd('sendtoaddress', address, str(amount))

    def send_raw_transaction(self, tx):
        return self._cli_cmnd('sendrawtransaction', tx.decode())

    def create_raw_transaction(self, inputs, outputs):
        return self._cli_cmnd('createrawtransaction', json.dumps(inputs), json.dumps(outputs))

    async def sign_raw_transaction_with_wallet(self, tx):
        # the "withwallet" portion should only come into play if we are doing segwit.
        # and "withwallet" doesn't exist on lbcd yet.
        result = await self._cli_cmnd('signrawtransaction', tx)
        return json.loads(result)['hex'].encode()

    def decode_raw_transaction(self, tx):
        return self._cli_cmnd('decoderawtransaction', hexlify(tx.raw).decode())

    def get_raw_transaction(self, txid):
        return self._cli_cmnd('getrawtransaction', txid, '1')
