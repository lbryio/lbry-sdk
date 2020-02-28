import os
import struct
import shutil
import asyncio
import logging
import zipfile
import tempfile
import urllib.request
from typing import Optional
from binascii import hexlify

import aiohttp
import zmq
import zmq.asyncio

from lbry.wallet.stream import StreamController


log = logging.getLogger(__name__)

download_url = (
#    'https://github.com/lbryio/lbrycrd/releases/download/v0.17.4.2/lbrycrd-linux-1742.zip'
    'https://build.lbry.io/lbrycrd/fix_flush_to_not_corrupt/lbrycrd-linux.zip'
)


class Process(asyncio.SubprocessProtocol):

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


class Lbrycrd:

    def __init__(self, path, regtest=False):
        self.data_dir = self.actual_data_dir = path
        self.regtest = regtest
        if regtest:
            self.actual_data_dir = os.path.join(self.data_dir, 'regtest')
        self.blocks_dir = os.path.join(self.actual_data_dir, 'blocks')
        self.bin_dir = os.path.join(os.path.dirname(__file__), 'bin')
        self.daemon_bin = os.path.join(self.bin_dir, 'lbrycrdd')
        self.cli_bin = os.path.join(self.bin_dir, 'lbrycrd-cli')
        self.protocol = None
        self.transport = None
        self.hostname = 'localhost'
        self.peerport = 9246 + 2  # avoid conflict with default peer port
        self.rpcport = 9245 + 2  # avoid conflict with default rpc port
        self.rpcuser = 'rpcuser'
        self.rpcpassword = 'rpcpassword'
        self.session: Optional[aiohttp.ClientSession] = None
        self.subscribed = False
        self.subscription: Optional[asyncio.Task] = None
        self.subscription_url = 'tcp://127.0.0.1:29000'
        self.default_generate_address = None
        self._on_block_controller = StreamController()
        self.on_block = self._on_block_controller.stream
        self.on_block.listen(lambda e: log.info('%s %s', hexlify(e['hash']), e['msg']))

    @classmethod
    def temp_regtest(cls):
        return cls(tempfile.mkdtemp(), True)

    @property
    def rpc_url(self):
        return f'http://{self.rpcuser}:{self.rpcpassword}@{self.hostname}:{self.rpcport}/'

    @property
    def exists(self):
        return (
            os.path.exists(self.cli_bin) and
            os.path.exists(self.daemon_bin)
        )

    async def download(self):
        downloaded_file = os.path.join(
            self.bin_dir, download_url[download_url.rfind('/')+1:]
        )

        if not os.path.exists(self.bin_dir):
            os.mkdir(self.bin_dir)

        if not os.path.exists(downloaded_file):
            log.info('Downloading: %s', download_url)
            async with aiohttp.ClientSession() as session:
                async with session.get(download_url) as response:
                    with open(downloaded_file, 'wb') as out_file:
                        while True:
                            chunk = await response.content.read(4096)
                            if not chunk:
                                break
                            out_file.write(chunk)
            with urllib.request.urlopen(download_url) as response:
                with open(downloaded_file, 'wb') as out_file:
                    shutil.copyfileobj(response, out_file)

        log.info('Extracting: %s', downloaded_file)

        with zipfile.ZipFile(downloaded_file) as dotzip:
            dotzip.extractall(self.bin_dir)
            # zipfile bug https://bugs.python.org/issue15795
            os.chmod(self.cli_bin, 0o755)
            os.chmod(self.daemon_bin, 0o755)

        return self.exists

    async def ensure(self):
        return self.exists or await self.download()

    def get_start_command(self, *args):
        if self.regtest:
            args += '-regtest',
        return (
            self.daemon_bin,
            f'-datadir={self.data_dir}',
            f'-port={self.peerport}',
            f'-rpcport={self.rpcport}',
            f'-rpcuser={self.rpcuser}',
            f'-rpcpassword={self.rpcpassword}',
            f'-zmqpubhashblock={self.subscription_url}',
            '-server', '-printtoconsole',
            *args
        )

    async def start(self, *args):
        loop = asyncio.get_event_loop()
        command = self.get_start_command(*args)
        log.info(' '.join(command))
        self.transport, self.protocol = await loop.subprocess_exec(Process, *command)
        await self.protocol.ready.wait()
        assert not self.protocol.stopped.is_set()
        self.session = aiohttp.ClientSession()

    async def stop(self, cleanup=True):
        try:
            await self.session.close()
            self.transport.terminate()
            await self.protocol.stopped.wait()
            assert self.transport.get_returncode() == 0, "lbrycrd daemon exit with error"
        finally:
            if cleanup:
                await self.cleanup()

    async def cleanup(self):
        await asyncio.get_running_loop().run_in_executor(
            None, shutil.rmtree, self.data_dir, True
        )

    def subscribe(self):
        if not self.subscribed:
            self.subscribed = True
            ctx = zmq.asyncio.Context.instance()
            sock = ctx.socket(zmq.SUB)
            sock.connect(self.subscription_url)
            sock.subscribe("hashblock")
            self.subscription = asyncio.create_task(self.subscription_handler(sock))

    async def subscription_handler(self, sock):
        try:
            while self.subscribed:
                msg = await sock.recv_multipart()
                self._on_block_controller.add({
                    'hash': msg[1],
                    'msg': struct.unpack('<I', msg[2])[0]
                })
        except asyncio.CancelledError:
            sock.close()
            raise

    def unsubscribe(self):
        if self.subscribed:
            self.subscribed = False
            self.subscription.cancel()
            self.subscription = None

    async def rpc(self, method, params=None):
        message = {
            "jsonrpc": "1.0",
            "id": "1",
            "method": method,
            "params": params or []
        }
        async with self.session.post(self.rpc_url, json=message) as resp:
            try:
                result = await resp.json()
            except aiohttp.ContentTypeError as e:
                raise Exception(await resp.text()) from e
            if not result['error']:
                return result['result']
            else:
                result['error'].update(method=method, params=params)
                raise Exception(result['error'])

    async def generate(self, blocks):
        if self.default_generate_address is None:
            self.default_generate_address = await self.get_new_address()
        return await self.generate_to_address(blocks, self.default_generate_address)

    async def get_new_address(self):
        return await self.rpc("getnewaddress")

    async def generate_to_address(self, blocks, address):
        return await self.rpc("generatetoaddress", [blocks, address])

    async def fund_raw_transaction(self, tx):
        return await self.rpc("fundrawtransaction", [tx])

    async def sign_raw_transaction_with_wallet(self, tx):
        return await self.rpc("signrawtransactionwithwallet", [tx])

    async def send_raw_transaction(self, tx):
        return await self.rpc("sendrawtransaction", [tx])

    async def claim_name(self, name, data, amount):
        return await self.rpc("claimname", [name, data, amount])
