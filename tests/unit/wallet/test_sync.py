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
        self.assertEqual(q.get_missing_required_filters(134_567), {
            (4, 0, 120_000),
            (3, 130_000, 133_000),
            (2, 134_000, 134_400),
            (1, 134_500, 134_567)
        })

        q.insert_block_filter(110_000, 4, b'beef')
        q.insert_block_filter(129_000, 3, b'beef')
        q.insert_block_filter(133_900, 2, b'beef')
        q.insert_block_filter(134_499, 1, b'beef')
        # we we have some filters, but not recent enough (all except 10k are adjusted)
        self.assertEqual(q.get_missing_required_filters(134_567), {
            (4, 120_000, 120_000),  # 0 -> 120_000
            (3, 130_000, 133_000),
            (2, 134_000, 134_400),
            (1, 134_500, 134_567)
        })

        q.insert_block_filter(132_000, 3, b'beef')
        q.insert_block_filter(134_300, 2, b'beef')
        q.insert_block_filter(134_550, 1, b'beef')
        # all filters get adjusted because we have recent of each
        self.assertEqual(q.get_missing_required_filters(134_567), {
            (4, 120_000, 120_000),  # 0       -> 120_000
            (3, 133_000, 133_000),  # 130_000 -> 133_000
            (2, 134_400, 134_400),  # 134_000 -> 134_400
            (1, 134_551, 134_567)   # 134_500 -> 134_551
        })

        q.insert_block_filter(120_000, 4, b'beef')
        q.insert_block_filter(133_000, 3, b'beef')
        q.insert_block_filter(134_400, 2, b'beef')
        q.insert_block_filter(134_566, 1, b'beef')
        # we have latest filters for all except latest single block
        self.assertEqual(q.get_missing_required_filters(134_567), {
            (1, 134_567, 134_567)   # 134_551 -> 134_567
        })

        q.insert_block_filter(134_567, 1, b'beef')
        # we have all latest filters
        self.assertEqual(q.get_missing_required_filters(134_567), set())


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

    def test_generate_from_filters_and_download_txs(self):
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
        self.assertEqual(q.get_missing_required_filters(134_567), set())

        # no addresses
        self.assertEqual([], self.get_ordered_addresses())

        # generate addresses with 6 address gap, returns new sub filters needed
        self.assertEqual(
            q.generate_addresses_using_filters(134_567, 6, (
                    self.root_pubkey.address, self.RECEIVING_KEY_N,
                    self.receiving_pubkey.pubkey_bytes,
                    self.receiving_pubkey.chain_code,
                    self.receiving_pubkey.depth
            )), {
                (0, 134500, 134500),
                (0, 134567, 134567),
                (1, 134000, 134099),
                (1, 134400, 134499),
                (2, 130000, 130900),
                (2, 133000, 133900),
                (3, 0, 9000),
                (3, 100000, 109000),
                (3, 120000, 129000)
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
        # no new addresses should have been generated either
        self.assertEqual([key.address for key in pubkeys], self.get_ordered_addresses())

        # check sub filters at 1,000
        self.assertEqual(
            q.get_missing_sub_filters_for_addresses(3, (
                self.root_pubkey.address, self.RECEIVING_KEY_N,
            )), {
                (2, 3000, 3900),
                (2, 103000, 103900),
                (2, 123000, 123900),
            }
        )
        # "download" missing 1,000 sub filters
        self.insert_sub_filters(3, hashes[0:1], 3000)
        self.insert_sub_filters(3, hashes[1:2], 103_000)
        self.insert_sub_filters(3, hashes[2:3], 123_000)
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
                (1, 3300, 3399),
                (1, 103300, 103399),
                (1, 123300, 123399),
                (1, 130300, 130399),
                (1, 133300, 133399),
            }
        )
        # "download" missing 100 sub filters
        self.insert_sub_filters(2, hashes[0:1], 3300)
        self.insert_sub_filters(2, hashes[1:2], 103_300)
        self.insert_sub_filters(2, hashes[2:3], 123_300)
        self.insert_sub_filters(2, hashes[3:4], 130_300)
        self.insert_sub_filters(2, hashes[4:5], 133_300)
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
                (0, 3303, 3303),
                (0, 103303, 103303),
                (0, 123303, 123303),
                (0, 130303, 130303),
                (0, 133303, 133303),
                (0, 134003, 134003),
                (0, 134403, 134403),
            }
        )
        # "download" missing tx filters
        self.insert_sub_filters(1, hashes[0:1], 3303)
        self.insert_sub_filters(1, hashes[1:2], 103_303)
        self.insert_sub_filters(1, hashes[2:3], 123_303)
        self.insert_sub_filters(1, hashes[3:4], 130_303)
        self.insert_sub_filters(1, hashes[4:5], 133_303)
        self.insert_sub_filters(1, hashes[5:6], 134_003)
        self.insert_sub_filters(1, hashes[6:7], 134_403)
        # no more missing tx filters
        self.assertEqual(
            q.get_missing_sub_filters_for_addresses(1, (
                self.root_pubkey.address, self.RECEIVING_KEY_N,
            )), set()
        )

        # find TXs we need to download
        missing_txs = {
            b'7478313033333033',
            b'7478313233333033',
            b'7478313330333033',
            b'7478313333333033',
            b'7478313334303033',
            b'7478313334343033',
            b'7478313334353030',
            b'7478313334353637',
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
