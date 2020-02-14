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

    def __init__(self, path=None):
        self.data_path = path
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
        self._on_block_controller = StreamController()
        self.on_block = self._on_block_controller.stream
        self.on_block.listen(lambda e: log.info('%s %s', hexlify(e['hash']), e['msg']))

    @classmethod
    def regtest(cls):
        return cls(tempfile.mkdtemp())

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

    async def start(self, *args):
        loop = asyncio.get_event_loop()
        command = [
            self.daemon_bin,
            f'-datadir={self.data_path}', '-printtoconsole', '-regtest', '-server',
            f'-rpcuser={self.rpcuser}', f'-rpcpassword={self.rpcpassword}', f'-rpcport={self.rpcport}',
            f'-port={self.peerport}', '-zmqpubhashblock=tcp://127.0.0.1:29000', *args
        ]
        log.info(' '.join(command))
        self.transport, self.protocol = await loop.subprocess_exec(
            Process, *command
        )
        await self.protocol.ready.wait()
        assert not self.protocol.stopped.is_set()
        self.session = aiohttp.ClientSession()

    async def stop(self, cleanup=True):
        try:
            await self.session.close()
            self.transport.terminate()
            await self.protocol.stopped.wait()
            self.transport.close()
        finally:
            if cleanup:
                await self.cleanup()

    async def cleanup(self):
        await asyncio.get_running_loop().run_in_executor(
            None, shutil.rmtree, self.data_path, True
        )

    def subscribe(self):
        if not self.subscribed:
            self.subscribed = True
            ctx = zmq.asyncio.Context.instance()
            sock = ctx.socket(zmq.SUB)
            sock.connect("tcp://127.0.0.1:29000")
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
        return await self.rpc("generate", [blocks])

    async def claim_name(self, name, data, amount):
        return await self.rpc("claimname", [name, data, amount])
