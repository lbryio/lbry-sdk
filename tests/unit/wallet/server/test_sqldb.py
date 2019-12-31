import unittest
import ecdsa
import hashlib
import logging
from binascii import hexlify
from lbry.wallet.client.constants import COIN, NULL_HASH32

from lbry.schema.claim import Claim
from lbry.wallet.server.db import reader, writer
from lbry.wallet.server.coin import LBCRegTest
from lbry.wallet.server.db.trending import TRENDING_WINDOW
from lbry.wallet.server.db.canonical import FindShortestID
from lbry.wallet.server.block_processor import Timer
from lbry.wallet.transaction import Transaction, Input, Output


def get_output(amount=COIN, pubkey_hash=NULL_HASH32):
    return Transaction() \
        .add_outputs([Output.pay_pubkey_hash(amount, pubkey_hash)]) \
        .outputs[0]


def get_input():
    return Input.spend(get_output())


def get_tx():
    return Transaction().add_inputs([get_input()])


class TestSQLDB(unittest.TestCase):
    query_timeout = 0.25

    def setUp(self):
        self.first_sync = False
        self.daemon_height = 1
        self.coin = LBCRegTest()
        db_url = 'file:test_sqldb?mode=memory&cache=shared'
        self.sql = writer.SQLDB(self, db_url)
        self.addCleanup(self.sql.close)
        self.sql.open()
        reader.initializer(logging.getLogger(__name__), db_url, 'regtest', self.query_timeout)
        self.addCleanup(reader.cleanup)
        self.timer = Timer('BlockProcessor')
        self._current_height = 0
        self._txos = {}

    def _make_tx(self, output, txi=None):
        tx = get_tx().add_outputs([output])
        if txi is not None:
            tx.add_inputs([txi])
        self._txos[output.ref.hash] = output
        return tx, tx.hash

    def _set_channel_key(self, channel, key):
        private_key = ecdsa.SigningKey.from_string(key*32, curve=ecdsa.SECP256k1, hashfunc=hashlib.sha256)
        channel.private_key = private_key
        channel.claim.channel.public_key_bytes = private_key.get_verifying_key().to_der()
        channel.script.generate()

    def get_channel(self, title, amount, name='@foo', key=b'a'):
        claim = Claim()
        claim.channel.title = title
        channel = Output.pay_claim_name_pubkey_hash(amount, name, claim, b'abc')
        self._set_channel_key(channel, key)
        return self._make_tx(channel)

    def get_channel_update(self, channel, amount, key=b'a'):
        self._set_channel_key(channel, key)
        return self._make_tx(
            Output.pay_update_claim_pubkey_hash(
                amount, channel.claim_name, channel.claim_id, channel.claim, b'abc'
            ),
            Input.spend(channel)
        )

    def get_stream(self, title, amount, name='foo', channel=None):
        claim = Claim()
        claim.stream.title = title
        result = self._make_tx(Output.pay_claim_name_pubkey_hash(amount, name, claim, b'abc'))
        if channel:
            result[0].outputs[0].sign(channel)
            result[0]._reset()
        return result

    def get_stream_update(self, tx, amount, channel=None):
        stream = Transaction(tx[0].raw).outputs[0]
        result = self._make_tx(
            Output.pay_update_claim_pubkey_hash(
                amount, stream.claim_name, stream.claim_id, stream.claim, b'abc'
            ),
            Input.spend(stream)
        )
        if channel:
            result[0].outputs[0].sign(channel)
            result[0]._reset()
        return result

    def get_abandon(self, tx):
        claim = Transaction(tx[0].raw).outputs[0]
        return self._make_tx(
            Output.pay_pubkey_hash(claim.amount, b'abc'),
            Input.spend(claim)
        )

    def get_support(self, tx, amount):
        claim = Transaction(tx[0].raw).outputs[0]
        return self._make_tx(
            Output.pay_support_pubkey_hash(
                amount, claim.claim_name, claim.claim_id, b'abc'
             )
        )

    def get_controlling(self):
        for claim in self.sql.execute("select claim.* from claimtrie natural join claim"):
            txo = self._txos[claim.txo_hash]
            controlling = txo.claim.stream.title, claim.amount, claim.effective_amount, claim.activation_height
            return controlling

    def get_active(self):
        controlling = self.get_controlling()
        active = []
        for claim in self.sql.execute(
                f"select * from claim where activation_height <= {self._current_height}"):
            txo = self._txos[claim.txo_hash]
            if controlling and controlling[0] == txo.claim.stream.title:
                continue
            active.append((txo.claim.stream.title, claim.amount, claim.effective_amount, claim.activation_height))
        return active

    def get_accepted(self):
        accepted = []
        for claim in self.sql.execute(
                f"select * from claim where activation_height > {self._current_height}"):
            txo = self._txos[claim.txo_hash]
            accepted.append((txo.claim.stream.title, claim.amount, claim.effective_amount, claim.activation_height))
        return accepted

    def advance(self, height, txs):
        self._current_height = height
        self.sql.advance_txs(height, txs, {'timestamp': 1}, self.daemon_height, self.timer)
        return [otx[0].outputs[0] for otx in txs]

    def state(self, controlling=None, active=None, accepted=None):
        self.assertEqual(controlling, self.get_controlling())
        self.assertEqual(active or [], self.get_active())
        self.assertEqual(accepted or [], self.get_accepted())


class TestClaimtrie(TestSQLDB):

    def test_example_from_spec(self):
        # https://spec.lbry.com/#claim-activation-example
        advance, state = self.advance, self.state
        stream = self.get_stream('Claim A', 10*COIN)
        advance(13, [stream])
        state(
            controlling=('Claim A', 10*COIN, 10*COIN, 13),
            active=[],
            accepted=[]
        )
        advance(1001, [self.get_stream('Claim B', 20*COIN)])
        state(
            controlling=('Claim A', 10*COIN, 10*COIN, 13),
            active=[],
            accepted=[('Claim B', 20*COIN, 0, 1031)]
        )
        advance(1010, [self.get_support(stream, 14*COIN)])
        state(
            controlling=('Claim A', 10*COIN, 24*COIN, 13),
            active=[],
            accepted=[('Claim B', 20*COIN, 0, 1031)]
        )
        advance(1020, [self.get_stream('Claim C', 50*COIN)])
        state(
            controlling=('Claim A', 10*COIN, 24*COIN, 13),
            active=[],
            accepted=[
                ('Claim B', 20*COIN, 0, 1031),
                ('Claim C', 50*COIN, 0, 1051)]
        )
        advance(1031, [])
        state(
            controlling=('Claim A', 10*COIN, 24*COIN, 13),
            active=[('Claim B', 20*COIN, 20*COIN, 1031)],
            accepted=[('Claim C', 50*COIN, 0, 1051)]
        )
        advance(1040, [self.get_stream('Claim D', 300*COIN)])
        state(
            controlling=('Claim A', 10*COIN, 24*COIN, 13),
            active=[('Claim B', 20*COIN, 20*COIN, 1031)],
            accepted=[
                ('Claim C', 50*COIN, 0, 1051),
                ('Claim D', 300*COIN, 0, 1072)]
        )
        advance(1051, [])
        state(
            controlling=('Claim D', 300*COIN, 300*COIN, 1051),
            active=[
                ('Claim A', 10*COIN, 24*COIN, 13),
                ('Claim B', 20*COIN, 20*COIN, 1031),
                ('Claim C', 50*COIN, 50*COIN, 1051)],
            accepted=[]
        )
        # beyond example
        advance(1052, [self.get_stream_update(stream, 290*COIN)])
        state(
            controlling=('Claim A', 290*COIN, 304*COIN, 13),
            active=[
                ('Claim B', 20*COIN, 20*COIN, 1031),
                ('Claim C', 50*COIN, 50*COIN, 1051),
                ('Claim D', 300*COIN, 300*COIN, 1051),
            ],
            accepted=[]
        )

    def test_competing_claims_subsequent_blocks_height_wins(self):
        advance, state = self.advance, self.state
        advance(13, [self.get_stream('Claim A', 10*COIN)])
        state(
            controlling=('Claim A', 10*COIN, 10*COIN, 13),
            active=[],
            accepted=[]
        )
        advance(14, [self.get_stream('Claim B', 10*COIN)])
        state(
            controlling=('Claim A', 10*COIN, 10*COIN, 13),
            active=[('Claim B', 10*COIN, 10*COIN, 14)],
            accepted=[]
        )
        advance(15, [self.get_stream('Claim C', 10*COIN)])
        state(
            controlling=('Claim A', 10*COIN, 10*COIN, 13),
            active=[
                ('Claim B', 10*COIN, 10*COIN, 14),
                ('Claim C', 10*COIN, 10*COIN, 15)],
            accepted=[]
        )

    def test_competing_claims_in_single_block_position_wins(self):
        advance, state = self.advance, self.state
        stream = self.get_stream('Claim A', 10*COIN)
        stream2 = self.get_stream('Claim B', 10*COIN)
        advance(13, [stream, stream2])
        state(
            controlling=('Claim A', 10*COIN, 10*COIN, 13),
            active=[('Claim B', 10*COIN, 10*COIN, 13)],
            accepted=[]
        )

    def test_competing_claims_in_single_block_effective_amount_wins(self):
        advance, state = self.advance, self.state
        stream = self.get_stream('Claim A', 10*COIN)
        stream2 = self.get_stream('Claim B', 11*COIN)
        advance(13, [stream, stream2])
        state(
            controlling=('Claim B', 11*COIN, 11*COIN, 13),
            active=[('Claim A', 10*COIN, 10*COIN, 13)],
            accepted=[]
        )

    def test_winning_claim_deleted(self):
        advance, state = self.advance, self.state
        stream = self.get_stream('Claim A', 10*COIN)
        stream2 = self.get_stream('Claim B', 11*COIN)
        advance(13, [stream, stream2])
        state(
            controlling=('Claim B', 11*COIN, 11*COIN, 13),
            active=[('Claim A', 10*COIN, 10*COIN, 13)],
            accepted=[]
        )
        advance(14, [self.get_abandon(stream2)])
        state(
            controlling=('Claim A', 10*COIN, 10*COIN, 13),
            active=[],
            accepted=[]
        )

    def test_winning_claim_deleted_and_new_claim_becomes_winner(self):
        advance, state = self.advance, self.state
        stream = self.get_stream('Claim A', 10*COIN)
        stream2 = self.get_stream('Claim B', 11*COIN)
        advance(13, [stream, stream2])
        state(
            controlling=('Claim B', 11*COIN, 11*COIN, 13),
            active=[('Claim A', 10*COIN, 10*COIN, 13)],
            accepted=[]
        )
        advance(15, [self.get_abandon(stream2), self.get_stream('Claim C', 12*COIN)])
        state(
            controlling=('Claim C', 12*COIN, 12*COIN, 15),
            active=[('Claim A', 10*COIN, 10*COIN, 13)],
            accepted=[]
        )

    def test_winning_claim_expires_and_another_takes_over(self):
        advance, state = self.advance, self.state
        advance(10, [self.get_stream('Claim A', 11*COIN)])
        advance(20, [self.get_stream('Claim B', 10*COIN)])
        state(
            controlling=('Claim A', 11*COIN, 11*COIN, 10),
            active=[('Claim B', 10*COIN, 10*COIN, 20)],
            accepted=[]
        )
        advance(262984, [])
        state(
            controlling=('Claim B', 10*COIN, 10*COIN, 20),
            active=[],
            accepted=[]
        )
        advance(262994, [])
        state(
            controlling=None,
            active=[],
            accepted=[]
        )

    def test_create_and_update_in_same_block(self):
        advance, state = self.advance, self.state
        stream = self.get_stream('Claim A', 10*COIN)
        advance(10, [stream, self.get_stream_update(stream, 11*COIN)])
        self.assertTrue(reader._search())

    def test_double_updates_in_same_block(self):
        advance, state = self.advance, self.state
        stream = self.get_stream('Claim A', 10*COIN)
        advance(10, [stream])
        update = self.get_stream_update(stream, 11*COIN)
        advance(20, [update, self.get_stream_update(update, 9*COIN)])
        self.assertTrue(reader._search())

    def test_create_and_abandon_in_same_block(self):
        advance, state = self.advance, self.state
        stream = self.get_stream('Claim A', 10*COIN)
        advance(10, [stream, self.get_abandon(stream)])
        self.assertFalse(reader._search())

    def test_update_and_abandon_in_same_block(self):
        advance, state = self.advance, self.state
        stream = self.get_stream('Claim A', 10*COIN)
        advance(10, [stream])
        update = self.get_stream_update(stream, 11*COIN)
        advance(20, [update, self.get_abandon(update)])
        self.assertFalse(reader._search())

    def test_create_update_and_delete_in_same_block(self):
        advance, state = self.advance, self.state
        stream = self.get_stream('Claim A', 10*COIN)
        update = self.get_stream_update(stream, 11*COIN)
        advance(10, [stream, update, self.get_abandon(update)])
        self.assertFalse(reader._search())

    def test_support_added_and_removed_in_same_block(self):
        advance, state = self.advance, self.state
        stream = self.get_stream('Claim A', 10*COIN)
        advance(10, [stream])
        support = self.get_support(stream, COIN)
        advance(20, [support, self.get_abandon(support)])
        self.assertEqual(reader._search()[0]['support_amount'], 0)

    @staticmethod
    def _get_x_with_claim_id_prefix(getter, prefix, cached_iteration=None, **kwargs):
        iterations = cached_iteration+1 if cached_iteration else 100
        for i in range(cached_iteration or 1, iterations):
            stream = getter(f'claim #{i}', COIN, **kwargs)
            if stream[0].outputs[0].claim_id.startswith(prefix):
                cached_iteration is None and print(f'Found "{prefix}" in {i} iterations.')
                return stream
        if cached_iteration:
            raise ValueError(f'Failed to find "{prefix}" at cached iteration, run with None to find iteration.')
        raise ValueError(f'Failed to find "{prefix}" in {iterations} iterations, try different values.')

    def get_channel_with_claim_id_prefix(self, prefix, cached_iteration=None, **kwargs):
        return self._get_x_with_claim_id_prefix(self.get_channel, prefix, cached_iteration, **kwargs)

    def get_stream_with_claim_id_prefix(self, prefix, cached_iteration=None, **kwargs):
        return self._get_x_with_claim_id_prefix(self.get_stream, prefix, cached_iteration, **kwargs)

    def test_canonical_url_and_channel_validation(self):
        advance = self.advance

        tx_chan_a = self.get_channel_with_claim_id_prefix('a', 1, key=b'c')
        tx_chan_ab = self.get_channel_with_claim_id_prefix('ab', 72, key=b'c')
        txo_chan_a = tx_chan_a[0].outputs[0]
        txo_chan_ab = tx_chan_ab[0].outputs[0]
        advance(1, [tx_chan_a])
        advance(2, [tx_chan_ab])
        r_ab, r_a = reader._search(order_by=['creation_height'], limit=2)
        self.assertEqual("@foo#a", r_a['short_url'])
        self.assertEqual("@foo#ab", r_ab['short_url'])
        self.assertIsNone(r_a['canonical_url'])
        self.assertIsNone(r_ab['canonical_url'])
        self.assertEqual(0, r_a['claims_in_channel'])
        self.assertEqual(0, r_ab['claims_in_channel'])

        tx_a = self.get_stream_with_claim_id_prefix('a', 2)
        tx_ab = self.get_stream_with_claim_id_prefix('ab', 42)
        tx_abc = self.get_stream_with_claim_id_prefix('abc', 65)
        advance(3, [tx_a])
        advance(4, [tx_ab, tx_abc])
        r_abc, r_ab, r_a = reader._search(order_by=['creation_height', 'tx_position'], limit=3)
        self.assertEqual("foo#a", r_a['short_url'])
        self.assertEqual("foo#ab", r_ab['short_url'])
        self.assertEqual("foo#abc", r_abc['short_url'])
        self.assertIsNone(r_a['canonical_url'])
        self.assertIsNone(r_ab['canonical_url'])
        self.assertIsNone(r_abc['canonical_url'])

        tx_a2 = self.get_stream_with_claim_id_prefix('a', 7, channel=txo_chan_a)
        tx_ab2 = self.get_stream_with_claim_id_prefix('ab', 23, channel=txo_chan_a)
        a2_claim = tx_a2[0].outputs[0]
        ab2_claim = tx_ab2[0].outputs[0]
        advance(6, [tx_a2])
        advance(7, [tx_ab2])
        r_ab2, r_a2 = reader._search(order_by=['creation_height'], limit=2)
        self.assertEqual(f"foo#{a2_claim.claim_id[:2]}", r_a2['short_url'])
        self.assertEqual(f"foo#{ab2_claim.claim_id[:4]}", r_ab2['short_url'])
        self.assertEqual("@foo#a/foo#a", r_a2['canonical_url'])
        self.assertEqual("@foo#a/foo#ab", r_ab2['canonical_url'])
        self.assertEqual(2, reader._search(claim_id=txo_chan_a.claim_id, limit=1)[0]['claims_in_channel'])

        # change channel public key, invaliding stream claim signatures
        advance(8, [self.get_channel_update(txo_chan_a, COIN, key=b'a')])
        r_ab2, r_a2 = reader._search(order_by=['creation_height'], limit=2)
        self.assertEqual(f"foo#{a2_claim.claim_id[:2]}", r_a2['short_url'])
        self.assertEqual(f"foo#{ab2_claim.claim_id[:4]}", r_ab2['short_url'])
        self.assertIsNone(r_a2['canonical_url'])
        self.assertIsNone(r_ab2['canonical_url'])
        self.assertEqual(0, reader._search(claim_id=txo_chan_a.claim_id, limit=1)[0]['claims_in_channel'])

        # reinstate previous channel public key (previous stream claim signatures become valid again)
        channel_update = self.get_channel_update(txo_chan_a, COIN, key=b'c')
        advance(9, [channel_update])
        r_ab2, r_a2 = reader._search(order_by=['creation_height'], limit=2)
        self.assertEqual(f"foo#{a2_claim.claim_id[:2]}", r_a2['short_url'])
        self.assertEqual(f"foo#{ab2_claim.claim_id[:4]}", r_ab2['short_url'])
        self.assertEqual("@foo#a/foo#a", r_a2['canonical_url'])
        self.assertEqual("@foo#a/foo#ab", r_ab2['canonical_url'])
        self.assertEqual(2, reader._search(claim_id=txo_chan_a.claim_id, limit=1)[0]['claims_in_channel'])
        self.assertEqual(0, reader._search(claim_id=txo_chan_ab.claim_id, limit=1)[0]['claims_in_channel'])

        # change channel of stream
        self.assertEqual("@foo#a/foo#ab", reader._search(claim_id=ab2_claim.claim_id, limit=1)[0]['canonical_url'])
        tx_ab2 = self.get_stream_update(tx_ab2, COIN, txo_chan_ab)
        advance(10, [tx_ab2])
        self.assertEqual("@foo#ab/foo#a", reader._search(claim_id=ab2_claim.claim_id, limit=1)[0]['canonical_url'])
        # TODO: currently there is a bug where stream leaving a channel does not update that channels claims count
        self.assertEqual(2, reader._search(claim_id=txo_chan_a.claim_id, limit=1)[0]['claims_in_channel'])
        # TODO: after bug is fixed remove test above and add test below
        #self.assertEqual(1, reader._search(claim_id=txo_chan_a.claim_id, limit=1)[0]['claims_in_channel'])
        self.assertEqual(1, reader._search(claim_id=txo_chan_ab.claim_id, limit=1)[0]['claims_in_channel'])

        # claim abandon updates claims_in_channel
        advance(11, [self.get_abandon(tx_ab2)])
        self.assertEqual(0, reader._search(claim_id=txo_chan_ab.claim_id, limit=1)[0]['claims_in_channel'])

        # delete channel, invaliding stream claim signatures
        advance(12, [self.get_abandon(channel_update)])
        r_a2, = reader._search(order_by=['creation_height'], limit=1)
        self.assertEqual(f"foo#{a2_claim.claim_id[:2]}", r_a2['short_url'])
        self.assertIsNone(r_a2['canonical_url'])

    def test_resolve_issue_2448(self):
        advance = self.advance

        tx_chan_a = self.get_channel_with_claim_id_prefix('a', 1, key=b'c')
        tx_chan_ab = self.get_channel_with_claim_id_prefix('ab', 72, key=b'c')
        txo_chan_a = tx_chan_a[0].outputs[0]
        txo_chan_ab = tx_chan_ab[0].outputs[0]
        advance(1, [tx_chan_a])
        advance(2, [tx_chan_ab])

        self.assertEqual(reader.resolve_url("@foo#a")['claim_hash'], txo_chan_a.claim_hash)
        self.assertEqual(reader.resolve_url("@foo#ab")['claim_hash'], txo_chan_ab.claim_hash)

        # update increase last height change of channel
        advance(9, [self.get_channel_update(txo_chan_a, COIN, key=b'c')])

        # make sure that activation_height is used instead of height (issue #2448)
        self.assertEqual(reader.resolve_url("@foo#a")['claim_hash'], txo_chan_a.claim_hash)
        self.assertEqual(reader.resolve_url("@foo#ab")['claim_hash'], txo_chan_ab.claim_hash)

    def test_canonical_find_shortest_id(self):
        new_hash = 'abcdef0123456789beef'
        other0 = '1bcdef0123456789beef'
        other1 = 'ab1def0123456789beef'
        other2 = 'abc1ef0123456789beef'
        other3 = 'abcdef0123456789bee1'
        f = FindShortestID()
        f.step(other0, new_hash)
        self.assertEqual('#a', f.finalize())
        f.step(other1, new_hash)
        self.assertEqual('#abc', f.finalize())
        f.step(other2, new_hash)
        self.assertEqual('#abcd', f.finalize())
        f.step(other3, new_hash)
        self.assertEqual('#abcdef0123456789beef', f.finalize())


class TestTrending(TestSQLDB):

    def test_trending(self):
        advance, state = self.advance, self.state
        no_trend = self.get_stream('Claim A', COIN)
        downwards = self.get_stream('Claim B', COIN)
        up_small = self.get_stream('Claim C', COIN)
        up_medium = self.get_stream('Claim D', COIN)
        up_biggly = self.get_stream('Claim E', COIN)
        claims = advance(1, [up_biggly, up_medium, up_small, no_trend, downwards])
        for window in range(1, 8):
            advance(TRENDING_WINDOW * window, [
                self.get_support(downwards, (20-window)*COIN),
                self.get_support(up_small, int(20+(window/10)*COIN)),
                self.get_support(up_medium, (20+(window*(2 if window == 7 else 1)))*COIN),
                self.get_support(up_biggly, (20+(window*(3 if window == 7 else 1)))*COIN),
            ])
        results = reader._search(order_by=['trending_local'])
        self.assertEqual([c.claim_id for c in claims], [hexlify(c['claim_hash'][::-1]).decode() for c in results])
        self.assertEqual([10, 6, 2, 0, -2], [int(c['trending_local']) for c in results])
        self.assertEqual([53, 38, -32, 0, -6], [int(c['trending_global']) for c in results])
        self.assertEqual([4, 4, 2, 0, 1], [int(c['trending_group']) for c in results])
        self.assertEqual([53, 38, 2, 0, -6], [int(c['trending_mixed']) for c in results])

    def test_edge(self):
        problematic = self.get_stream('Problem', COIN)
        self.advance(1, [problematic])
        self.advance(TRENDING_WINDOW, [self.get_support(problematic, 53000000000)])
        self.advance(TRENDING_WINDOW * 2, [self.get_support(problematic, 500000000)])
