from binascii import hexlify
from sqlalchemy.future import select

from lbry.crypto.hash import hash160
from lbry.crypto.bip32 import from_extended_key_string
from lbry.blockchain.block import create_address_filter
from lbry.db import queries as q
from lbry.db.tables import AccountAddress, TX
from lbry.db.query_context import context
from lbry.testcase import UnitDBTestCase


class TestMissingRequiredFiltersCalculation(UnitDBTestCase):

    def test_get_missing_required_filters(self):
        self.assertEqual(q.get_missing_required_filters(99), {(1, 0, 99)})
        self.assertEqual(q.get_missing_required_filters(100), {(2, 0, 0)})
        self.assertEqual(q.get_missing_required_filters(199), {(2, 0, 0), (1, 100, 199)})
        self.assertEqual(q.get_missing_required_filters(201), {(2, 0, 100), (1, 200, 201)})

        # all filters missing
        self.assertEqual(q.get_missing_required_filters(234_567), {
            (5, 0, 100_000),
            (4, 200_000, 220_000),
            (3, 230_000, 233_000),
            (2, 234_000, 234_400),
            (1, 234_500, 234_567)
        })

        q.insert_block_filters([(0, 5, b'beef')])
        q.insert_block_filters([(190_000, 4, b'beef')])
        q.insert_block_filters([(229_000, 3, b'beef')])
        q.insert_block_filters([(233_900, 2, b'beef')])
        q.insert_block_filters([(234_499, 1, b'beef')])
        # we have some old filters but none useable as initial required (except one 100k filter)
        self.assertEqual(q.get_missing_required_filters(234_567), {
            (5, 100_000, 100_000),
            (4, 200_000, 220_000),
            (3, 230_000, 233_000),
            (2, 234_000, 234_400),
            (1, 234_500, 234_567)
        })

        q.insert_block_filters([(100_000, 5, b'beef')])
        q.insert_block_filters([(210_000, 4, b'beef')])
        q.insert_block_filters([(232_000, 3, b'beef')])
        q.insert_block_filters([(234_300, 2, b'beef')])
        q.insert_block_filters([(234_550, 1, b'beef')])
        # we have some useable initial filters, but not all
        self.assertEqual(q.get_missing_required_filters(234_567), {
            (4, 220_000, 220_000),
            (3, 233_000, 233_000),
            (2, 234_400, 234_400),
            (1, 234_551, 234_567)
        })

        q.insert_block_filters([(220_000, 4, b'beef')])
        q.insert_block_filters([(233_000, 3, b'beef')])
        q.insert_block_filters([(234_400, 2, b'beef')])
        q.insert_block_filters([(234_566, 1, b'beef')])
        # we have latest filters for all except latest single block
        self.assertEqual(q.get_missing_required_filters(234_567), {
            (1, 234_567, 234_567)
        })

        q.insert_block_filters([(234_567, 1, b'beef')])
        # we have all latest filters
        self.assertEqual(q.get_missing_required_filters(234_567), set())


class TestAddressGenerationAndTXSync(UnitDBTestCase):

    RECEIVING_KEY_N = 0

    def setUp(self):
        super().setUp()
        self.root_pubkey = from_extended_key_string(
            self.ledger,
            'xpub661MyMwAqRbcGWtPvbWh9sc2BCfw2cTeVDYF23o3N1t6UZ5wv3EMmDgp66FxH'
            'uDtWdft3B5eL5xQtyzAtkdmhhC95gjRjLzSTdkho95asu9'
        )
        self.receiving_pubkey = self.root_pubkey.child(self.RECEIVING_KEY_N)

    def generate(self, loops, is_new_starts=0):
        with q.PersistingAddressIterator(
            self.root_pubkey.address, self.RECEIVING_KEY_N,
            self.receiving_pubkey.pubkey_bytes,
            self.receiving_pubkey.chain_code,
            self.receiving_pubkey.depth
        ) as generator:
            for address, n, is_new in generator:
                if n >= is_new_starts:
                    self.assertTrue(is_new)
                else:
                    self.assertFalse(is_new)
                if n == loops:
                    break

    @staticmethod
    def get_ordered_addresses():
        return [r["address"] for r in context().fetchall(
            select(AccountAddress.c.address).order_by(AccountAddress.c.n)
        )]

    def test_generator_persisting(self):
        expected = [self.receiving_pubkey.child(n).address for n in range(30)]
        self.assertEqual([], self.get_ordered_addresses())
        self.generate(5, 0)
        self.assertEqual(expected[:6], self.get_ordered_addresses())
        self.generate(7, 6)
        self.assertEqual(expected[:8], self.get_ordered_addresses())
        self.generate(12, 8)
        self.assertEqual(expected[:13], self.get_ordered_addresses())

    @staticmethod
    def insert_sub_filters(granularity, addresses, height):
        if granularity >= 2:
            end = height + 10 ** granularity
            step = 1 if granularity == 2 else 10 ** (granularity - 1)
            for i, height in enumerate(range(height, end, step)):
                if i == 3:
                    q.insert_block_filters([(height, granularity - 1, create_address_filter(addresses))])
                else:
                    q.insert_block_filters([(height, granularity - 1, create_address_filter([b'beef']))])
        elif granularity == 1:
            q.insert_tx_filters([(hexlify(f'tx{height}'.encode()), height, create_address_filter(addresses))])

    def test_generate_from_filters_and_download_txs(self):
        # 15 addresses will get generated, 9 due to filters and 6 due to gap
        pubkeys = [self.receiving_pubkey.child(n) for n in range(15)]
        hashes = [hash160(key.pubkey_bytes) for key in pubkeys]

        # create all required filters (include 9 of the addresses in the filters)

        q.insert_block_filters([(0,       5, create_address_filter(hashes[0:1]))])
        q.insert_block_filters([(100_000, 5, create_address_filter([b'beef']))])

        q.insert_block_filters([(200_000, 4, create_address_filter(hashes[1:2]))])
        q.insert_block_filters([(210_000, 4, create_address_filter([b'beef']))])
        q.insert_block_filters([(220_000, 4, create_address_filter(hashes[2:3]))])

        q.insert_block_filters([(230_000, 3, create_address_filter(hashes[3:4]))])
        q.insert_block_filters([(231_000, 3, create_address_filter([b'beef']))])
        q.insert_block_filters([(233_000, 3, create_address_filter(hashes[4:5]))])

        q.insert_block_filters([(234_000, 2, create_address_filter(hashes[5:6]))])
        q.insert_block_filters([(234_200, 2, create_address_filter([b'beef']))])
        q.insert_block_filters([(234_400, 2, create_address_filter(hashes[6:7]))])

        q.insert_block_filters([(234_500, 1, create_address_filter(hashes[7:8]))])
        q.insert_block_filters([(234_566, 1, create_address_filter([b'beef']))])
        q.insert_block_filters([(234_567, 1, create_address_filter(hashes[8:9]))])

        # check that all required filters did get created
        self.assertEqual(q.get_missing_required_filters(234_567), set())

        # no addresses
        self.assertEqual([], self.get_ordered_addresses())

        # generate addresses with 6 address gap, returns new sub filters needed
        self.assertEqual(
            q.generate_addresses_using_filters(234_567, 6, (
                    self.root_pubkey.address, self.RECEIVING_KEY_N,
                    self.receiving_pubkey.pubkey_bytes,
                    self.receiving_pubkey.chain_code,
                    self.receiving_pubkey.depth
            )), {
                (0, 234500, 234500),
                (0, 234567, 234567),
                (1, 234000, 234099),
                (1, 234400, 234499),
                (2, 230000, 230900),
                (2, 233000, 233900),
                (3, 200000, 209000),
                (3, 220000, 229000),
                (4, 0, 90000),
            }
        )

        # all addresses generated
        self.assertEqual([key.address for key in pubkeys], self.get_ordered_addresses())

        # "download" missing sub filters
        self.insert_sub_filters(5, hashes[0:1], 0)
        self.insert_sub_filters(4, hashes[1:2], 200_000)
        self.insert_sub_filters(4, hashes[2:3], 220_000)
        self.insert_sub_filters(3, hashes[3:4], 230_000)
        self.insert_sub_filters(3, hashes[4:5], 233_000)
        self.insert_sub_filters(2, hashes[5:6], 234_000)
        self.insert_sub_filters(2, hashes[6:7], 234_400)
        self.insert_sub_filters(1, hashes[7:8], 234_500)
        self.insert_sub_filters(1, hashes[8:9], 234_567)

        # no sub filters needed to be downloaded now when re-checking all addresses
        self.assertEqual(
            q.generate_addresses_using_filters(234_567, 6, (
                self.root_pubkey.address, self.RECEIVING_KEY_N,
                self.receiving_pubkey.pubkey_bytes,
                self.receiving_pubkey.chain_code,
                self.receiving_pubkey.depth
            )), set()
        )
        # no new addresses should have been generated either
        self.assertEqual([key.address for key in pubkeys], self.get_ordered_addresses())

        # check sub filters at 1,000
        self.assertEqual(
            q.get_missing_sub_filters_for_addresses(3, (
                self.root_pubkey.address, self.RECEIVING_KEY_N,
            )), {
                (2, 223000, 223900),
            }
        )
        # "download" missing 1,000 sub filters
        self.insert_sub_filters(3, hashes[1:2], 203_000)
        self.insert_sub_filters(3, hashes[2:3], 223_000)
        # no more missing sub filters at 1,000
        self.assertEqual(
            q.get_missing_sub_filters_for_addresses(3, (
                self.root_pubkey.address, self.RECEIVING_KEY_N,
            )), set()
        )

        # check sub filters at 100
        self.assertEqual(
            q.get_missing_sub_filters_for_addresses(2, (
                self.root_pubkey.address, self.RECEIVING_KEY_N,
            )), {
                (1, 233300, 233399),
            }
        )
        # "download" missing 100 sub filters
        self.insert_sub_filters(2, hashes[0:1], 3300)
        self.insert_sub_filters(2, hashes[1:2], 203_300)
        self.insert_sub_filters(2, hashes[2:3], 223_300)
        self.insert_sub_filters(2, hashes[3:4], 230_300)
        self.insert_sub_filters(2, hashes[4:5], 233_300)
        # no more missing sub filters at 100
        self.assertEqual(
            q.get_missing_sub_filters_for_addresses(2, (
                self.root_pubkey.address, self.RECEIVING_KEY_N,
            )), set()
        )

        # check tx filters
        self.assertEqual(
            q.get_missing_sub_filters_for_addresses(1, (
                self.root_pubkey.address, self.RECEIVING_KEY_N,
            )), {
                (0, 234403, 234403),
            }
        )
        # "download" missing tx filters
        self.insert_sub_filters(1, hashes[0:1], 3303)
        self.insert_sub_filters(1, hashes[1:2], 203_303)
        self.insert_sub_filters(1, hashes[2:3], 223_303)
        self.insert_sub_filters(1, hashes[3:4], 230_303)
        self.insert_sub_filters(1, hashes[4:5], 233_303)
        self.insert_sub_filters(1, hashes[5:6], 234_003)
        self.insert_sub_filters(1, hashes[6:7], 234_403)
        # no more missing tx filters
        self.assertEqual(
            q.get_missing_sub_filters_for_addresses(1, (
                self.root_pubkey.address, self.RECEIVING_KEY_N,
            )), set()
        )

        # find TXs we need to download
        missing_txs = {
            b'7478323033333033',
            b'7478323233333033',
            b'7478323330333033',
            b'7478323333333033',
            b'7478323334303033',
            b'7478323334343033',
            b'7478323334353030',
            b'7478323334353637',
            b'747833333033'
        }
        self.assertEqual(
            q.get_missing_tx_for_addresses((
                self.root_pubkey.address, self.RECEIVING_KEY_N,
            )), missing_txs
        )
        # "download" missing TXs
        ctx = context()
        for tx_hash in missing_txs:
            ctx.execute(TX.insert().values(tx_hash=tx_hash))
        # check we have everything
        self.assertEqual(
            q.get_missing_tx_for_addresses((
                self.root_pubkey.address, self.RECEIVING_KEY_N,
            )), set()
        )
