import os
from unittest import TestCase
from binascii import hexlify

from lbry.testcase import AsyncioTestCase
from lbry.wallet import Wallet, Account, Transaction, Output, Input, Ledger, Database, Headers

from tests.unit.wallet.test_transaction import get_transaction, get_output
from tests.unit.wallet.test_headers import HEADERS, block_bytes


class MockNetwork:

    def __init__(self, history, transaction):
        self.history = history
        self.transaction = transaction
        self.address = None
        self.get_history_called = []
        self.get_transaction_called = []
        self.is_connected = False

    def retriable_call(self, function, *args, **kwargs):
        return function(*args, **kwargs)

    async def get_history(self, address):
        self.get_history_called.append(address)
        self.address = address
        return self.history

    async def get_merkle(self, txid, height):
        return {'merkle': ['abcd01'], 'pos': 1}

    async def get_transaction(self, tx_hash, _=None):
        self.get_transaction_called.append(tx_hash)
        return self.transaction[tx_hash]

    async def get_transaction_and_merkle(self, tx_hash, known_height=None):
        tx = await self.get_transaction(tx_hash)
        merkle = {'block_height': -1}
        if known_height:
            merkle = await self.get_merkle(tx_hash, known_height)
        return tx, merkle

    async def get_transaction_batch(self, txids, restricted):
        return {
            txid: await self.get_transaction_and_merkle(txid)
            for txid in txids
        }


class LedgerTestCase(AsyncioTestCase):

    async def asyncSetUp(self):
        self.ledger = Ledger({
            'db': Database(':memory:'),
            'headers': Headers(':memory:')
        })
        self.ledger.headers.checkpoints = {}
        await self.ledger.headers.open()
        self.account = Account.generate(self.ledger, Wallet(), "lbryum")
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
            'claim_trie_root': b'4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b',
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
        self.ledger.headers._size = self.ledger.headers.io.seek(0, os.SEEK_END) // self.ledger.headers.header_size


class TestUtils(TestCase):

    def test_valid_address(self):
        self.assertTrue(Ledger.is_script_address("rCz6yb1p33oYHToGZDzTjX7nFKaU3kNgBd"))


class TestSynchronization(LedgerTestCase):

    async def test_update_history(self):
        txid1 = '252bda9b22cc902ca2aa2de3548ee8baf06b8501ff7bfb3b0b7d980dbd1bf792'
        txid2 = 'ab9c0654dd484ac20437030f2034e25dcb29fc507e84b91138f80adc3af738f9'
        txid3 = 'a2ae3d1db3c727e7d696122cab39ee20a7f81856dab7019056dd539f38c548a0'
        txid4 = '047cf1d53ef68f0fd586d46f90c09ff8e57a4180f67e7f4b8dd0135c3741e828'

        account = Account.generate(self.ledger, Wallet(), "torba")
        address = await account.receiving.get_or_create_usable_address()
        address_details = await self.ledger.db.get_address(address=address)
        self.assertIsNone(address_details['history'])

        self.add_header(block_height=0, merkle_root=b'abcd04')
        self.add_header(block_height=1, merkle_root=b'abcd04')
        self.add_header(block_height=2, merkle_root=b'abcd04')
        self.add_header(block_height=3, merkle_root=b'abcd04')
        self.ledger.network = MockNetwork([
            {'tx_hash': txid1, 'height': 0},
            {'tx_hash': txid2, 'height': 1},
            {'tx_hash': txid3, 'height': 2},
        ], {
            txid1: hexlify(get_transaction(get_output(1)).raw),
            txid2: hexlify(get_transaction(get_output(2)).raw),
            txid3: hexlify(get_transaction(get_output(3)).raw),
        })
        await self.ledger.update_history(address, '')
        self.assertListEqual(self.ledger.network.get_history_called, [address])
        self.assertListEqual(self.ledger.network.get_transaction_called, [txid1, txid2, txid3])

        address_details = await self.ledger.db.get_address(address=address)

        self.assertEqual(
            address_details['history'],
            f'{txid1}:0:'
            f'{txid2}:1:'
            f'{txid3}:2:'
        )

        self.ledger.network.get_history_called = []
        self.ledger.network.get_transaction_called = []
        self.assertEqual(0, len(self.ledger._tx_cache))
        await self.ledger.update_history(address, '')
        self.assertListEqual(self.ledger.network.get_history_called, [address])
        self.assertListEqual(self.ledger.network.get_transaction_called, [])

        self.ledger.network.history.append({'tx_hash': txid4, 'height': 3})
        self.ledger.network.transaction[txid4] = hexlify(get_transaction(get_output(4)).raw)
        self.ledger.network.get_history_called = []
        self.ledger.network.get_transaction_called = []
        await self.ledger.update_history(address, '')
        self.assertListEqual(self.ledger.network.get_history_called, [address])
        self.assertListEqual(self.ledger.network.get_transaction_called, [txid4])
        address_details = await self.ledger.db.get_address(address=address)
        self.assertEqual(
            address_details['history'],
            f'{txid1}:0:'
            f'{txid2}:1:'
            f'{txid3}:2:'
            f'{txid4}:3:'
        )


class MocHeaderNetwork(MockNetwork):
    def __init__(self, responses):
        super().__init__(None, None)
        self.responses = responses

    async def get_headers(self, height, blocks):
        return self.responses[height]


class BlockchainReorganizationTests(LedgerTestCase):

    async def test_1_block_reorganization(self):
        self.ledger.network = MocHeaderNetwork({
            10: {'height': 10, 'count': 5, 'hex': hexlify(
                HEADERS[block_bytes(10):block_bytes(15)]
            )},
            15: {'height': 15, 'count': 0, 'hex': b''}
        })
        headers = self.ledger.headers
        await headers.connect(0, HEADERS[:block_bytes(10)])
        self.add_header(block_height=len(headers))
        self.assertEqual(10, headers.height)
        await self.ledger.receive_header([{
            'height': 11, 'hex': hexlify(self.make_header(block_height=11))
        }])

    async def test_3_block_reorganization(self):
        self.ledger.network = MocHeaderNetwork({
            10: {'height': 10, 'count': 5, 'hex': hexlify(
                HEADERS[block_bytes(10):block_bytes(15)]
            )},
            11: {'height': 11, 'count': 1, 'hex': hexlify(self.make_header(block_height=11))},
            12: {'height': 12, 'count': 1, 'hex': hexlify(self.make_header(block_height=12))},
            15: {'height': 15, 'count': 0, 'hex': b''}
        })
        headers = self.ledger.headers
        await headers.connect(0, HEADERS[:block_bytes(10)])
        self.add_header(block_height=len(headers))
        self.add_header(block_height=len(headers))
        self.add_header(block_height=len(headers))
        self.assertEqual(headers.height, 12)
        await self.ledger.receive_header([{
            'height': 13, 'hex': hexlify(self.make_header(block_height=13))
        }])


class BasicAccountingTests(LedgerTestCase):

    async def test_empty_state(self):
        self.assertEqual(await self.account.get_balance(), 0)

    async def test_balance(self):
        address = await self.account.receiving.get_or_create_usable_address()
        hash160 = self.ledger.address_to_hash160(address)

        tx = Transaction(is_verified=True)\
            .add_outputs([Output.pay_pubkey_hash(100, hash160)])
        await self.ledger.db.insert_transaction(tx)
        await self.ledger.db.save_transaction_io(
            tx, address, hash160, f'{tx.id}:1:'
        )
        self.assertEqual(await self.account.get_balance(), 100)

        tx = Transaction(is_verified=True)\
            .add_outputs([Output.pay_claim_name_pubkey_hash(100, 'foo', b'', hash160)])
        await self.ledger.db.insert_transaction(tx)
        await self.ledger.db.save_transaction_io(
            tx, address, hash160, f'{tx.id}:1:'
        )
        self.assertEqual(await self.account.get_balance(), 100)  # claim names don't count towards balance
        self.assertEqual(await self.account.get_balance(include_claims=True), 200)

    async def test_get_utxo(self):
        address = yield self.account.receiving.get_or_create_usable_address()
        hash160 = self.ledger.address_to_hash160(address)

        tx = Transaction(is_verified=True)\
            .add_outputs([Output.pay_pubkey_hash(100, hash160)])
        await self.ledger.db.save_transaction_io(
            'insert', tx, address, hash160, f'{tx.id}:1:'
        )

        utxos = await self.account.get_utxos()
        self.assertEqual(len(utxos), 1)

        tx = Transaction(is_verified=True)\
            .add_inputs([Input.spend(utxos[0])])
        await self.ledger.db.save_transaction_io(
            'insert', tx, address, hash160, f'{tx.id}:1:'
        )
        self.assertEqual(await self.account.get_balance(include_claims=True), 0)

        utxos = await self.account.get_utxos()
        self.assertEqual(len(utxos), 0)
