import asyncio
import os
import tempfile
from binascii import hexlify

from torba.client.hash import sha256
from torba.testcase import AsyncioTestCase

from torba.coin.bitcoinsegwit import MainHeaders
from binascii import unhexlify

from torba.testcase import AsyncioTestCase
from torba.client.util import ArithUint256

from lbry.wallet.ledger import Headers


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
        self.assertDictEqual(h[0], {
            'bits': 486604799,
            'block_height': 0,
            'merkle_root': b'4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b',
            'nonce': 2083236893,
            'prev_block_hash': b'0000000000000000000000000000000000000000000000000000000000000000',
            'timestamp': 1231006505,
            'version': 1
        })
        self.assertDictEqual(h[self.RETARGET_BLOCK-1], {
            'bits': 486604799,
            'block_height': 32255,
            'merkle_root': b'89b4f223789e40b5b475af6483bb05bceda54059e17d2053334b358f6bb310ac',
            'nonce': 312762301,
            'prev_block_hash': b'000000006baebaa74cecde6c6787c26ee0a616a3c333261bff36653babdac149',
            'timestamp': 1262152739,
            'version': 1
        })
        self.assertDictEqual(h[self.RETARGET_BLOCK], {
            'bits': 486594666,
            'block_height': 32256,
            'merkle_root': b'64b5e5f5a262f47af443a0120609206a3305877693edfe03e994f20a024ab627',
            'nonce': 121087187,
            'prev_block_hash': b'00000000984f962134a7291e3693075ae03e521f0ee33378ec30a334d860034b',
            'timestamp': 1262153464,
            'version': 1
        })
        self.assertDictEqual(h[self.RETARGET_BLOCK+1], {
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

    async def test_bounds(self):
        headers = MainHeaders(':memory:')
        await headers.connect(0, self.get_bytes(block_bytes(3001)))
        self.assertEqual(headers.height, 3000)
        with self.assertRaises(IndexError):
            _ = headers[3001]
        with self.assertRaises(IndexError):
            _ = headers[-1]
        self.assertIsNotNone(headers[3000])
        self.assertIsNotNone(headers[0])

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

    async def test_checkpointed_writer(self):
        headers = MainHeaders(':memory:')
        headers.checkpoint = 100, hexlify(sha256(self.get_bytes(block_bytes(100))))
        genblocks = lambda start, end: self.get_bytes(block_bytes(end - start), block_bytes(start))
        async with headers.checkpointed_connector() as buff:
            buff.write(genblocks(0, 10))
        self.assertEqual(len(headers), 10)
        async with headers.checkpointed_connector() as buff:
            buff.write(genblocks(10, 100))
        self.assertEqual(len(headers), 100)
        headers = MainHeaders(':memory:')
        async with headers.checkpointed_connector() as buff:
            buff.write(genblocks(0, 300))
        self.assertEqual(len(headers), 300)

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


class TestHeaders(AsyncioTestCase):

    def test_deserialize(self):
        self.maxDiff = None
        h = Headers(':memory:')
        h.io.write(HEADERS)
        self.assertEqual(h[0], {
            'bits': 520159231,
            'block_height': 0,
            'claim_trie_root': b'0000000000000000000000000000000000000000000000000000000000000001',
            'merkle_root': b'b8211c82c3d15bcd78bba57005b86fed515149a53a425eb592c07af99fe559cc',
            'nonce': 1287,
            'prev_block_hash': b'0000000000000000000000000000000000000000000000000000000000000000',
            'timestamp': 1446058291,
            'version': 1
        })
        self.assertEqual(h[10], {
            'bits': 509349720,
            'block_height': 10,
            'merkle_root': b'f4d8fded6a181d4a8a2817a0eb423cc0f414af29490004a620e66c35c498a554',
            'claim_trie_root': b'0000000000000000000000000000000000000000000000000000000000000001',
            'nonce': 75838,
            'prev_block_hash': b'fdab1b38bcf236bc85b6bcd52fe8ec19bcb0b6c7352e913de05fa5a4e5ae8d55',
            'timestamp': 1466646593,
            'version': 536870912
        })

    async def test_connect_from_genesis(self):
        headers = Headers(':memory:')
        self.assertEqual(headers.height, -1)
        await headers.connect(0, HEADERS)
        self.assertEqual(headers.height, 19)

    async def test_connect_from_middle(self):
        h = Headers(':memory:')
        h.io.write(HEADERS[:10*Headers.header_size])
        self.assertEqual(h.height, 9)
        await h.connect(len(h), HEADERS[10*Headers.header_size:20*Headers.header_size])
        self.assertEqual(h.height, 19)

    def test_target_calculation(self):
        # see: https://github.com/lbryio/lbrycrd/blob/master/src/test/lbry_tests.cpp
        # 1 test block 1 difficulty, should be a max retarget
        self.assertEqual(
            0x1f00e146,
            Headers(':memory').get_next_block_target(
                max_target=ArithUint256(Headers.max_target),
                previous={'timestamp': 1386475638},
                current={'timestamp': 1386475638, 'bits': 0x1f00ffff}
            ).compact
        )
        # test max retarget (difficulty increase)
        self.assertEqual(
            0x1f008ccc,
            Headers(':memory').get_next_block_target(
                max_target=ArithUint256(Headers.max_target),
                previous={'timestamp': 1386475638},
                current={'timestamp': 1386475638, 'bits': 0x1f00a000}
            ).compact
        )
        # test min retarget (difficulty decrease)
        self.assertEqual(
            0x1f00f000,
            Headers(':memory').get_next_block_target(
                max_target=ArithUint256(Headers.max_target),
                previous={'timestamp': 1386475638},
                current={'timestamp': 1386475638 + 60*20, 'bits': 0x1f00a000}
            ).compact
        )
        # test to see if pow limit is not exceeded
        self.assertEqual(
            0x1f00ffff,
            Headers(':memory').get_next_block_target(
                max_target=ArithUint256(Headers.max_target),
                previous={'timestamp': 1386475638},
                current={'timestamp': 1386475638 + 600, 'bits': 0x1f00ffff}
            ).compact
        )

    def test_get_proof_of_work_hash(self):
        # see: https://github.com/lbryio/lbrycrd/blob/master/src/test/lbry_tests.cpp
        self.assertEqual(
            Headers.header_hash_to_pow_hash(Headers.hash_header(b"test string")),
            b"485f3920d48a0448034b0852d1489cfa475341176838c7d36896765221be35ce"
        )
        self.assertEqual(
            Headers.header_hash_to_pow_hash(Headers.hash_header(b"a"*70)),
            b"eb44af2f41e7c6522fb8be4773661be5baa430b8b2c3a670247e9ab060608b75"
        )
        self.assertEqual(
            Headers.header_hash_to_pow_hash(Headers.hash_header(b"d"*140)),
            b"74044747b7c1ff867eb09a84d026b02d8dc539fb6adcec3536f3dfa9266495d9"
        )


HEADERS = unhexlify(
    b'010000000000000000000000000000000000000000000000000000000000000000000000cc59e59ff97ac092b55e4'
    b'23aa5495151ed6fb80570a5bb78cd5bd1c3821c21b801000000000000000000000000000000000000000000000000'
    b'0000000000000033193156ffff001f070500000000002063f4346a4db34fdfce29a70f5e8d11f065f6b91602b7036'
    b'c7f22f3a03b28899cba888e2f9c037f831046f8ad09f6d378f79c728d003b177a64d29621f481da5d010000000000'
    b'00000000000000000000000000000000000000000000000000003c406b5746e1001f5b4f000000000020246cb8584'
    b'3ac936d55388f2ff288b011add5b1b20cca9cfd19a403ca2c9ecbde09d8734d81b5f2eb1b653caf17491544ddfbc7'
    b'2f2f4c0c3f22a3362db5ba9d4701000000000000000000000000000000000000000000000000000000000000003d4'
    b'06b57ffff001f4ff20000000000200044e1258b865d262587c28ff98853bc52bb31266230c1c648cc9004047a5428'
    b'e285dbf24334585b9a924536a717160ee185a86d1eeb7b19684538685eca761a01000000000000000000000000000'
    b'000000000000000000000000000000000003d406b5746e1001fce9c010000000020bbf8980e3f7604896821203bf6'
    b'2f97f311124da1fbb95bf523fcfdb356ad19c9d83cf1408debbd631950b7a95b0c940772119cd8a615a3d44601568'
    b'713fec80c01000000000000000000000000000000000000000000000000000000000000003e406b573dc6001fec7b'
    b'0000000000201a650b9b7b9d132e257ff6b336ba7cd96b1796357c4fc8dd7d0bd1ff1de057d547638e54178dbdddf'
    b'2e81a3b7566860e5264df6066755f9760a893f5caecc5790100000000000000000000000000000000000000000000'
    b'0000000000000000003e406b5773ae001fcf770000000000206d694b93a2bb5ac23a13ed6749a789ca751cf73d598'
    b'2c459e0cd9d5d303da74cec91627e0dba856b933983425d7f72958e8f974682632a0fa2acee9cfd81940101000000'
    b'000000000000000000000000000000000000000000000000000000003e406b578399001f225c010000000020b5780'
    b'8c188b7315583cf120fe89de923583bc7a8ebff03189145b86bf859b21ba3c4a19948a1263722c45c5601fd10a7ae'
    b'a7cf73bfa45e060508f109155e80ab010000000000000000000000000000000000000000000000000000000000000'
    b'03f406b571787001f0816070000000020a6a5b330e816242d54c8586ba9b6d63c19d921171ef3d4525b8ffc635742'
    b'e83a0fc2da46cf0de0057c1b9fc93d997105ff6cf2c8c43269b446c1dbf5ac18be8c0100000000000000000000000'
    b'00000000000000000000000000000000000000040406b570ae1761edd8f030000000020b8447f415279dffe8a09af'
    b'e6f6d5e335a2f6911fce8e1d1866723d5e5e8a53067356a733f87e592ea133328792dd9d676ed83771c8ff0f51992'
    b'8ce752f159ba6010000000000000000000000000000000000000000000000000000000000000040406b57139d681e'
    b'd40d000000000020558daee5a4a55fe03d912e35c7b6b0bc19ece82fd5bcb685bc36f2bc381babfd54a598c4356ce'
    b'620a604004929af14f4c03c42eba017288a4a1d186aedfdd8f4010000000000000000000000000000000000000000'
    b'000000000000000000000041406b57580f5c1e3e280100000000200381bfc0b2f10c9a3c0fc2dc8ad06388aff8ea5'
    b'a9f7dba6a945073b021796197364b79f33ff3f3a7ccb676fc0a37b7d831bd5942a05eac314658c6a7e4c4b1a40100'
    b'00000000000000000000000000000000000000000000000000000000000041406b574303511ec0ae0100000000202'
    b'aae02063ae0f1025e6acecd5e8e2305956ecaefd185bb47a64ea2ae953233891df3d4c1fc547ab3bbca027c8bbba7'
    b'44c051add8615d289b567f97c64929dcf201000000000000000000000000000000000000000000000000000000000'
    b'0000042406b578c4a471e04ee00000000002016603ef45d5a7c02bfbb30f422016746872ff37f8b0b5824a0f70caa'
    b'668eea5415aad300e70f7d8755d93645d1fd21eda9c40c5d0ed797acd0e07ace34585aaf010000000000000000000'
    b'000000000000000000000000000000000000000000042406b577bbc3e1ea163000000000020cad8863b312914f2fd'
    b'2aad6e9420b64859039effd67ac4681a7cf60e42b09b7e7bafa1e8d5131f477785d8338294da0f998844a85b39d24'
    b'26e839b370e014e3b010000000000000000000000000000000000000000000000000000000000000042406b573935'
    b'371e20e900000000002053d5e608ce5a12eda5931f86ee81198fdd231fea64cf096e9aeae321cf2efbe241e888d5a'
    b'af495e4c2a9f11b932db979d7483aeb446f479179b0c0b8d24bfa0e01000000000000000000000000000000000000'
    b'0000000000000000000000000045406b573c95301e34af0a0000000020df0e494c02ff79e3929bc1f2491077ec4f6'
    b'a607d7a1a5e1be96536642c98f86e533febd715f8a234028fd52046708551c6b6ac415480a6568aaa35cb94dc7203'
    b'01000000000000000000000000000000000000000000000000000000000000004f406b57c4c02a1ec54d230000000'
    b'020341f7d8e7d242e5e46343c40840c44f07e7e7306eb2355521b51502e8070e569485ba7eec4efdff0fc755af6e7'
    b'3e38b381a88b0925a68193a25da19d0f616e9f0100000000000000000000000000000000000000000000000000000'
    b'00000000050406b575be8251e1f61010000000020cd399f8078166ca5f0bdd1080ab1bb22d3c271b9729b6000b44f'
    b'4592cc9fab08c00ebab1e7cd88677e3b77c1598c7ac58660567f49f3a30ec46a48a1ae7652fe01000000000000000'
    b'0000000000000000000000000000000000000000000000052406b57d55b211e6f53090000000020c6c14ed4a53bbb'
    b'4f181acf2bbfd8b74d13826732f2114140ca99ca371f7dd87c51d18a05a1a6ffa37c041877fa33c2229a45a0ab66b'
    b'5530f914200a8d6639a6f010000000000000000000000000000000000000000000000000000000000000055406b57'
    b'0d5b1d1eff1c0900'
)
