import asyncio
import os
import tempfile
from urllib.request import Request, urlopen

from torba.testcase import AsyncioTestCase

from torba.coin.bitcoinsegwit import MainHeaders


def block_bytes(blocks):
    return blocks * MainHeaders.header_size


class BitcoinHeadersTestCase(AsyncioTestCase):
    HEADER_FILE = 'bitcoin_headers'
    RETARGET_BLOCK = 32256  # difficulty: 1 -> 1.18

    def setUp(self):
        self.maxDiff = None
        self.header_file_name = os.path.join(os.path.dirname(__file__), self.HEADER_FILE)

    def get_bytes(self, upto: int = -1, after: int = 0) -> bytes:
        with open(self.header_file_name, 'rb') as headers:
            headers.seek(after, os.SEEK_SET)
            return headers.read(upto)

    async def get_headers(self, upto: int = -1):
        h = MainHeaders(':memory:')
        h.io.write(self.get_bytes(upto))
        return h


class BasicHeadersTests(BitcoinHeadersTestCase):

    async def test_serialization(self):
        h = await self.get_headers()
        self.assertEqual(h[0], {
            'bits': 486604799,
            'block_height': 0,
            'merkle_root': b'4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b',
            'nonce': 2083236893,
            'prev_block_hash': b'0000000000000000000000000000000000000000000000000000000000000000',
            'timestamp': 1231006505,
            'version': 1
        })
        self.assertEqual(h[self.RETARGET_BLOCK-1], {
            'bits': 486604799,
            'block_height': 32255,
            'merkle_root': b'89b4f223789e40b5b475af6483bb05bceda54059e17d2053334b358f6bb310ac',
            'nonce': 312762301,
            'prev_block_hash': b'000000006baebaa74cecde6c6787c26ee0a616a3c333261bff36653babdac149',
            'timestamp': 1262152739,
            'version': 1
        })
        self.assertEqual(h[self.RETARGET_BLOCK], {
            'bits': 486594666,
            'block_height': 32256,
            'merkle_root': b'64b5e5f5a262f47af443a0120609206a3305877693edfe03e994f20a024ab627',
            'nonce': 121087187,
            'prev_block_hash': b'00000000984f962134a7291e3693075ae03e521f0ee33378ec30a334d860034b',
            'timestamp': 1262153464,
            'version': 1
        })
        self.assertEqual(h[self.RETARGET_BLOCK+1], {
            'bits': 486594666,
            'block_height': 32257,
            'merkle_root': b'4d1488981f08b3037878193297dbac701a2054e0f803d4424fe6a4d763d62334',
            'nonce': 274675219,
            'prev_block_hash': b'000000004f2886a170adb7204cb0c7a824217dd24d11a74423d564c4e0904967',
            'timestamp': 1262154352,
            'version': 1
        })
        self.assertEqual(
            h.serialize(h[0]),
            h.get_raw_header(0)
        )
        self.assertEqual(
            h.serialize(h[self.RETARGET_BLOCK]),
            h.get_raw_header(self.RETARGET_BLOCK)
        )

    async def test_connect_from_genesis_to_3000_past_first_chunk_at_2016(self):
        headers = MainHeaders(':memory:')
        self.assertEqual(headers.height, -1)
        await headers.connect(0, self.get_bytes(block_bytes(3001)))
        self.assertEqual(headers.height, 3000)

    async def test_connect_9_blocks_passing_a_retarget_at_32256(self):
        retarget = block_bytes(self.RETARGET_BLOCK-5)
        headers = await self.get_headers(upto=retarget)
        remainder = self.get_bytes(after=retarget)
        self.assertEqual(headers.height, 32250)
        await headers.connect(len(headers), remainder)
        self.assertEqual(headers.height, 32259)

    async def test_repair(self):
        headers = MainHeaders(':memory:')
        await headers.connect(0, self.get_bytes(block_bytes(3001)))
        self.assertEqual(headers.height, 3000)
        await headers.repair()
        self.assertEqual(headers.height, 3000)
        # corrupt the middle of it
        headers.io.seek(block_bytes(1500))
        headers.io.write(b"wtf")
        await headers.repair()
        self.assertEqual(headers.height, 1499)
        self.assertEqual(len(headers), 1500)
        # corrupt by appending
        headers.io.seek(block_bytes(len(headers)))
        headers.io.write(b"appending")
        await headers.repair()
        self.assertEqual(headers.height, 1499)
        await headers.connect(len(headers), self.get_bytes(block_bytes(3001 - 1500), after=block_bytes(1500)))
        self.assertEqual(headers.height, 3000)

    async def test_concurrency(self):
        BLOCKS = 30
        headers_temporary_file = tempfile.mktemp()
        headers = MainHeaders(headers_temporary_file)
        await headers.open()
        self.addCleanup(os.remove, headers_temporary_file)
        async def writer():
            for block_index in range(BLOCKS):
                await headers.connect(block_index, self.get_bytes(block_bytes(block_index + 1), block_bytes(block_index)))
        async def reader():
            for block_index in range(BLOCKS):
                while len(headers) < block_index:
                    await asyncio.sleep(0.000001)
                assert headers[block_index]['block_height'] == block_index
        reader_task = asyncio.create_task(reader())
        await writer()
        await reader_task