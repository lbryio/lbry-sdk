import asyncio
import aiohttp
import aiohttp.web
import os
import hashlib
import logging
from lbrynet.utils import aiohttp_request
from lbrynet.testcase import CommandTestCase

log = logging.getLogger(__name__)


class RangeRequests(CommandTestCase):

    VERBOSITY = logging.WARN

    async def _test_range_requests(self, data: bytes, save_blobs: bool = True, streaming_only: bool = True):
        self.daemon.conf.save_blobs = save_blobs
        self.daemon.conf.streaming_only = streaming_only
        self.data = data
        await self.stream_create('foo', '0.01', data=self.data)
        await self.daemon.jsonrpc_file_delete(delete_from_download_dir=True, claim_name='foo')

        self.daemon.stream_manager.stop()
        await self.daemon.stream_manager.start()

        await self.daemon.runner.setup()
        site = aiohttp.web.TCPSite(self.daemon.runner, self.daemon.conf.api_host, self.daemon.conf.api_port)
        await site.start()
        self.assertListEqual(self.daemon.jsonrpc_file_list(), [])
        name = 'foo'
        url = f'http://{self.daemon.conf.api_host}:{self.daemon.conf.api_port}/get/{name}'

        streamed_bytes = b''
        async with aiohttp_request('get', url) as req:
            self.assertEqual(req.headers.get('Content-Type'), 'application/octet-stream')
            content_range = req.headers.get('Content-Range')
            while True:
                try:
                    data, eof = await asyncio.wait_for(req.content.readchunk(), 3, loop=self.loop)
                except asyncio.TimeoutError:
                    data = b''
                    eof = True
                if data:
                    streamed_bytes += data
                if not data or eof:
                    break
        self.assertTrue((len(streamed_bytes) + 16 >= len(self.data))
                        and (len(streamed_bytes) <= len(self.data)))
        return streamed_bytes, content_range

    async def test_range_requests_0_padded_bytes(self):
        self.data = b''.join(hashlib.sha256(os.urandom(16)).digest() for _ in range(250000)) + b'0000000000000'
        streamed, content_range = await self._test_range_requests(self.data)
        self.assertEqual(streamed, self.data)
        self.assertEqual(content_range, 'bytes 0-8000013/8000014')

    async def test_range_requests_1_padded_bytes(self):
        self.data = b''.join(hashlib.sha256(os.urandom(16)).digest() for _ in range(250000)) + b'00000000000001x'
        streamed, content_range = await self._test_range_requests(self.data)
        self.assertEqual(streamed, self.data[:-1])
        self.assertEqual(content_range, 'bytes 0-8000013/8000014')

    async def test_range_requests_2_padded_bytes(self):
        self.data = b''.join(hashlib.sha256(os.urandom(16)).digest() for _ in range(250000))
        streamed, content_range = await self._test_range_requests(self.data)
        self.assertEqual(streamed, self.data[:-2])
        self.assertEqual(content_range, 'bytes 0-7999997/7999998')
