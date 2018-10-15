import os
from binascii import hexlify

from torba.coin.bitcoinsegwit import MainNetLedger
from torba.wallet import Wallet

from .test_transaction import get_transaction, get_output
from .test_headers import BitcoinHeadersTestCase, block_bytes


class MockNetwork:

    def __init__(self, history, transaction):
        self.history = history
        self.transaction = transaction
        self.address = None
        self.get_history_called = []
        self.get_transaction_called = []

    async def get_history(self, address):
        self.get_history_called.append(address)
        self.address = address
        return self.history

    async def get_merkle(self, txid, height):
        return {'merkle': ['abcd01'], 'pos': 1}

    async def get_transaction(self, tx_hash):
        self.get_transaction_called.append(tx_hash)
        return self.transaction[tx_hash]


class LedgerTestCase(BitcoinHeadersTestCase):

    async def asyncSetUp(self):
        self.ledger = MainNetLedger({
            'db': MainNetLedger.database_class(':memory:'),
            'headers': MainNetLedger.headers_class(':memory:')
        })
        await self.ledger.db.open()

    async def asyncTearDown(self):
        await self.ledger.db.close()

    def make_header(self, **kwargs):
        header = {
            'bits': 486604799,
            'block_height': 0,
            'merkle_root': b'4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b',
            'nonce': 2083236893,
            'prev_block_hash': b'0000000000000000000000000000000000000000000000000000000000000000',
            'timestamp': 1231006505,
            'version': 1
        }
        header.update(kwargs)
        header['merkle_root'] = header['merkle_root'].ljust(64, b'a')
        header['prev_block_hash'] = header['prev_block_hash'].ljust(64, b'0')
        return self.ledger.headers.serialize(header)

    def add_header(self, **kwargs):
        serialized = self.make_header(**kwargs)
        self.ledger.headers.io.seek(0, os.SEEK_END)
        self.ledger.headers.io.write(serialized)
        self.ledger.headers._size = None


class TestSynchronization(LedgerTestCase):

    async def test_update_history(self):
        account = self.ledger.account_class.generate(self.ledger, Wallet(), "torba")
        address = await account.receiving.get_or_create_usable_address()
        address_details = await self.ledger.db.get_address(address=address)
        self.assertEqual(address_details['history'], None)

        self.add_header(block_height=0, merkle_root=b'abcd04')
        self.add_header(block_height=1, merkle_root=b'abcd04')
        self.add_header(block_height=2, merkle_root=b'abcd04')
        self.add_header(block_height=3, merkle_root=b'abcd04')
        self.ledger.network = MockNetwork([
            {'tx_hash': 'abcd01', 'height': 0},
            {'tx_hash': 'abcd02', 'height': 1},
            {'tx_hash': 'abcd03', 'height': 2},
        ], {
            'abcd01': hexlify(get_transaction(get_output(1)).raw),
            'abcd02': hexlify(get_transaction(get_output(2)).raw),
            'abcd03': hexlify(get_transaction(get_output(3)).raw),
        })
        await self.ledger.update_history(address)
        self.assertEqual(self.ledger.network.get_history_called, [address])
        self.assertEqual(self.ledger.network.get_transaction_called, ['abcd01', 'abcd02', 'abcd03'])

        address_details = await self.ledger.db.get_address(address=address)
        self.assertEqual(address_details['history'], 'abcd01:0:abcd02:1:abcd03:2:')

        self.ledger.network.get_history_called = []
        self.ledger.network.get_transaction_called = []
        await self.ledger.update_history(address)
        self.assertEqual(self.ledger.network.get_history_called, [address])
        self.assertEqual(self.ledger.network.get_transaction_called, [])

        self.ledger.network.history.append({'tx_hash': 'abcd04', 'height': 3})
        self.ledger.network.transaction['abcd04'] = hexlify(get_transaction(get_output(4)).raw)
        self.ledger.network.get_history_called = []
        self.ledger.network.get_transaction_called = []
        await self.ledger.update_history(address)
        self.assertEqual(self.ledger.network.get_history_called, [address])
        self.assertEqual(self.ledger.network.get_transaction_called, ['abcd04'])
        address_details = await self.ledger.db.get_address(address=address)
        self.assertEqual(address_details['history'], 'abcd01:0:abcd02:1:abcd03:2:abcd04:3:')


class MocHeaderNetwork:
    def __init__(self, responses):
        self.responses = responses

    async def get_headers(self, height, blocks):
        return self.responses[height]


class BlockchainReorganizationTests(LedgerTestCase):

    async def test_1_block_reorganization(self):
        self.ledger.network = MocHeaderNetwork({
            20: {'height': 20, 'count': 5, 'hex': hexlify(
                self.get_bytes(after=block_bytes(20), upto=block_bytes(5))
            )},
            25: {'height': 25, 'count': 0, 'hex': b''}
        })
        headers = self.ledger.headers
        await headers.connect(0, self.get_bytes(upto=block_bytes(20)))
        self.add_header(block_height=len(headers))
        self.assertEqual(headers.height, 20)
        await self.ledger.receive_header([{
            'height': 21, 'hex': hexlify(self.make_header(block_height=21))
        }])

    async def test_3_block_reorganization(self):
        self.ledger.network = MocHeaderNetwork({
            20: {'height': 20, 'count': 5, 'hex': hexlify(
                self.get_bytes(after=block_bytes(20), upto=block_bytes(5))
            )},
            21: {'height': 21, 'count': 1, 'hex': hexlify(self.make_header(block_height=21))},
            22: {'height': 22, 'count': 1, 'hex': hexlify(self.make_header(block_height=22))},
            25: {'height': 25, 'count': 0, 'hex': b''}
        })
        headers = self.ledger.headers
        await headers.connect(0, self.get_bytes(upto=block_bytes(20)))
        self.add_header(block_height=len(headers))
        self.add_header(block_height=len(headers))
        self.add_header(block_height=len(headers))
        self.assertEqual(headers.height, 22)
        await self.ledger.receive_header(({
            'height': 23, 'hex': hexlify(self.make_header(block_height=23))
        },))
