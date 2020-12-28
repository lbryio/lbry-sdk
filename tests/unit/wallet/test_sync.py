from binascii import hexlify
from sqlalchemy.future import select

from lbry.crypto.hash import hash160
from lbry.crypto.bip32 import from_extended_key_string
from lbry.blockchain.block import create_address_filter
from lbry.db import queries as q
from lbry.db.tables import AccountAddress
from lbry.db.query_context import context
from lbry.testcase import UnitDBTestCase


class TestMissingRequiredFiltersCalculation(UnitDBTestCase):

    def test_get_missing_required_filters(self):
        self.assertEqual(q.get_missing_required_filters(99), {1: (0, 99)})
        self.assertEqual(q.get_missing_required_filters(100), {100: (0, 0)})
        self.assertEqual(q.get_missing_required_filters(199), {100: (0, 0), 1: (100, 199)})
        self.assertEqual(q.get_missing_required_filters(201), {100: (0, 100), 1: (200, 201)})
        # all filters missing
        self.assertEqual(q.get_missing_required_filters(134_567), {
            10_000: (0, 120_000),
            1_000: (130_000, 133_000),
            100: (134_000, 134_400),
            1: (134_500, 134_567)
        })

        q.insert_block_filter(110_000, 4, b'beef')
        q.insert_block_filter(129_000, 3, b'beef')
        q.insert_block_filter(133_900, 2, b'beef')
        q.insert_block_filter(134_499, 1, b'beef')
        # we we have some filters, but not recent enough (all except 10k are adjusted)
        self.assertEqual(q.get_missing_required_filters(134_567), {
            10_000: (120_000, 120_000),  # 0 -> 120_000
            1_000: (130_000, 133_000),
            100: (134_000, 134_400),
            1: (134_500, 134_567)
        })

        q.insert_block_filter(132_000, 3, b'beef')
        q.insert_block_filter(134_300, 2, b'beef')
        q.insert_block_filter(134_550, 1, b'beef')
        # all filters get adjusted because we have recent of each
        self.assertEqual(q.get_missing_required_filters(134_567), {
            10_000: (120_000, 120_000),  # 0       -> 120_000
            1_000: (133_000, 133_000),   # 130_000 -> 133_000
            100: (134_400, 134_400),     # 134_000 -> 134_400
            1: (134_551, 134_567)        # 134_500 -> 134_551
        })

        q.insert_block_filter(120_000, 4, b'beef')
        q.insert_block_filter(133_000, 3, b'beef')
        q.insert_block_filter(134_400, 2, b'beef')
        q.insert_block_filter(134_566, 1, b'beef')
        # we have latest filters for all except latest single block
        self.assertEqual(q.get_missing_required_filters(134_567), {
            1: (134_567, 134_567)   # 134_551 -> 134_567
        })

        q.insert_block_filter(134_567, 1, b'beef')
        # we have all latest filters
        self.assertEqual(q.get_missing_required_filters(134_567), {})


class TestAddressGeneration(UnitDBTestCase):

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
        expected = [self.receiving_pubkey.child(n).addresses for n in range(30)]
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
                    q.insert_block_filter(height, granularity - 1, create_address_filter(addresses))
                else:
                    q.insert_block_filter(height, granularity - 1, create_address_filter([b'beef']))
        elif granularity == 1:
            q.insert_tx_filter(hexlify(f'tx{height}'.encode()), height, create_address_filter(addresses))

    def test_generate_from_filters(self):
        # 15 addresses will get generated, 9 due to filters and 6 due to gap
        pubkeys = [self.receiving_pubkey.child(n) for n in range(15)]
        hashes = [hash160(key.pubkey_bytes) for key in pubkeys]

        # create all required filters (include 9 of the addresses in the filters)

        q.insert_block_filter(0,       4, create_address_filter(hashes[0:1]))
        q.insert_block_filter(100_000, 4, create_address_filter(hashes[1:2]))
        q.insert_block_filter(110_000, 4, create_address_filter([b'beef']))
        q.insert_block_filter(120_000, 4, create_address_filter(hashes[2:3]))

        q.insert_block_filter(130_000, 3, create_address_filter(hashes[3:4]))
        q.insert_block_filter(131_000, 3, create_address_filter([b'beef']))
        q.insert_block_filter(133_000, 3, create_address_filter(hashes[4:5]))

        q.insert_block_filter(134_000, 2, create_address_filter(hashes[5:6]))
        q.insert_block_filter(134_200, 2, create_address_filter([b'beef']))
        q.insert_block_filter(134_400, 2, create_address_filter(hashes[6:7]))

        q.insert_block_filter(134_500, 1, create_address_filter(hashes[7:8]))
        q.insert_block_filter(134_566, 1, create_address_filter([b'beef']))
        q.insert_block_filter(134_567, 1, create_address_filter(hashes[8:9]))

        # check that all required filters did get created
        self.assertEqual(q.get_missing_required_filters(134_567), {})

        # generate addresses with 6 address gap, returns new sub filters needed
        self.assertEqual(
            q.generate_addresses_using_filters(134_567, 6, (
                    self.root_pubkey.address, self.RECEIVING_KEY_N,
                    self.receiving_pubkey.pubkey_bytes,
                    self.receiving_pubkey.chain_code,
                    self.receiving_pubkey.depth
            )), {
                (1, 134500),
                (1, 134567),
                (2, 134000),
                (2, 134400),
                (3, 130000),
                (3, 133000),
                (4, 0),
                (4, 100000),
                (4, 120000)
            }
        )

        # all addresses generated
        self.assertEqual([key.address for key in pubkeys], self.get_ordered_addresses())

        # "download" missing sub filters
        self.insert_sub_filters(4, hashes[0:1], 0)
        self.insert_sub_filters(4, hashes[1:2], 100_000)
        self.insert_sub_filters(4, hashes[2:3], 120_000)
        self.insert_sub_filters(3, hashes[3:4], 130_000)
        self.insert_sub_filters(3, hashes[4:5], 133_000)
        self.insert_sub_filters(2, hashes[5:6], 134_000)
        self.insert_sub_filters(2, hashes[6:7], 134_400)
        self.insert_sub_filters(1, hashes[7:8], 134_500)
        self.insert_sub_filters(1, hashes[8:9], 134_567)

        # no sub filters needed to be downloaded now when re-checking all addresses
        self.assertEqual(
            q.generate_addresses_using_filters(134_567, 6, (
                self.root_pubkey.address, self.RECEIVING_KEY_N,
                self.receiving_pubkey.pubkey_bytes,
                self.receiving_pubkey.chain_code,
                self.receiving_pubkey.depth
            )), set()
        )

        # no new addresses should have been generated
        self.assertEqual([key.address for key in pubkeys], self.get_ordered_addresses())

        self.assertEqual(
            q.generate_addresses_using_filters(134_567, 6, (
                self.root_pubkey.address, self.RECEIVING_KEY_N,
                self.receiving_pubkey.pubkey_bytes,
                self.receiving_pubkey.chain_code,
                self.receiving_pubkey.depth
            )), set()
        )
