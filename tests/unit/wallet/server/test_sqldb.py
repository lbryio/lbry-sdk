import unittest
import ecdsa
import hashlib
import logging
from binascii import hexlify
from typing import List, Tuple

from lbry.wallet.constants import COIN, NULL_HASH32
from lbry.schema.claim import Claim
from lbry.schema.result import Censor
from lbry.wallet.server.db import writer
from lbry.wallet.server.coin import LBCRegTest
from lbry.wallet.server.db.trending import zscore
from lbry.wallet.server.db.canonical import FindShortestID
from lbry.wallet.transaction import Transaction, Input, Output
try:
    import reader
except:
    from . import reader


def get_output(amount=COIN, pubkey_hash=NULL_HASH32):
    return Transaction() \
        .add_outputs([Output.pay_pubkey_hash(amount, pubkey_hash)]) \
        .outputs[0]


def get_input():
    return Input.spend(get_output())


def get_tx():
    return Transaction().add_inputs([get_input()])


def search(**constraints) -> List:
    return reader.search_claims(Censor(Censor.SEARCH), **constraints)


def censored_search(**constraints) -> Tuple[List, Censor]:
    rows, _, _, _, censor = reader.search(constraints)
    return rows, censor


class TestSQLDB(unittest.TestCase):
    query_timeout = 0.25

    def setUp(self):
        self.first_sync = False
        self.daemon_height = 1
        self.coin = LBCRegTest()
        db_url = 'file:test_sqldb?mode=memory&cache=shared'
        self.sql = writer.SQLDB(self, db_url, [], [], [zscore])
        self.addCleanup(self.sql.close)
        self.sql.open()
        reader.initializer(
            logging.getLogger(__name__), db_url, 'regtest',
            self.query_timeout, block_and_filter=(
                self.sql.blocked_streams, self.sql.blocked_channels,
                self.sql.filtered_streams, self.sql.filtered_channels
            )
        )
        self.addCleanup(reader.cleanup)
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

    def get_stream(self, title, amount, name='foo', channel=None, **kwargs):
        claim = Claim()
        claim.stream.update(title=title, **kwargs)
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

    def get_repost(self, claim_id, amount, channel):
        claim = Claim()
        claim.repost.reference.claim_id = claim_id
        result = self._make_tx(Output.pay_claim_name_pubkey_hash(amount, 'repost', claim, b'abc'))
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


@unittest.skip("port canonical url tests to leveldb")  # TODO: port canonical url tests to leveldb
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
        self.assertTrue(search()[0])

    def test_double_updates_in_same_block(self):
        advance, state = self.advance, self.state
        stream = self.get_stream('Claim A', 10*COIN)
        advance(10, [stream])
        update = self.get_stream_update(stream, 11*COIN)
        advance(20, [update, self.get_stream_update(update, 9*COIN)])
        self.assertTrue(search()[0])

    def test_create_and_abandon_in_same_block(self):
        advance, state = self.advance, self.state
        stream = self.get_stream('Claim A', 10*COIN)
        advance(10, [stream, self.get_abandon(stream)])
        self.assertFalse(search())

    def test_update_and_abandon_in_same_block(self):
        advance, state = self.advance, self.state
        stream = self.get_stream('Claim A', 10*COIN)
        advance(10, [stream])
        update = self.get_stream_update(stream, 11*COIN)
        advance(20, [update, self.get_abandon(update)])
        self.assertFalse(search())

    def test_create_update_and_delete_in_same_block(self):
        advance, state = self.advance, self.state
        stream = self.get_stream('Claim A', 10*COIN)
        update = self.get_stream_update(stream, 11*COIN)
        advance(10, [stream, update, self.get_abandon(update)])
        self.assertFalse(search())

    def test_support_added_and_removed_in_same_block(self):
        advance, state = self.advance, self.state
        stream = self.get_stream('Claim A', 10*COIN)
        advance(10, [stream])
        support = self.get_support(stream, COIN)
        advance(20, [support, self.get_abandon(support)])
        self.assertEqual(search()[0]['support_amount'], 0)

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
        (r_ab, r_a) = search(order_by=['creation_height'], limit=2)
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
        (r_abc, r_ab, r_a) = search(order_by=['creation_height', 'tx_position'], limit=3)
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
        (r_ab2, r_a2) = search(order_by=['creation_height'], limit=2)
        self.assertEqual(f"foo#{a2_claim.claim_id[:2]}", r_a2['short_url'])
        self.assertEqual(f"foo#{ab2_claim.claim_id[:4]}", r_ab2['short_url'])
        self.assertEqual("@foo#a/foo#a", r_a2['canonical_url'])
        self.assertEqual("@foo#a/foo#ab", r_ab2['canonical_url'])
        self.assertEqual(2, search(claim_id=txo_chan_a.claim_id, limit=1)[0]['claims_in_channel'])

        # change channel public key, invaliding stream claim signatures
        advance(8, [self.get_channel_update(txo_chan_a, COIN, key=b'a')])
        (r_ab2, r_a2) = search(order_by=['creation_height'], limit=2)
        self.assertEqual(f"foo#{a2_claim.claim_id[:2]}", r_a2['short_url'])
        self.assertEqual(f"foo#{ab2_claim.claim_id[:4]}", r_ab2['short_url'])
        self.assertIsNone(r_a2['canonical_url'])
        self.assertIsNone(r_ab2['canonical_url'])
        self.assertEqual(0, search(claim_id=txo_chan_a.claim_id, limit=1)[0]['claims_in_channel'])

        # reinstate previous channel public key (previous stream claim signatures become valid again)
        channel_update = self.get_channel_update(txo_chan_a, COIN, key=b'c')
        advance(9, [channel_update])
        (r_ab2, r_a2) = search(order_by=['creation_height'], limit=2)
        self.assertEqual(f"foo#{a2_claim.claim_id[:2]}", r_a2['short_url'])
        self.assertEqual(f"foo#{ab2_claim.claim_id[:4]}", r_ab2['short_url'])
        self.assertEqual("@foo#a/foo#a", r_a2['canonical_url'])
        self.assertEqual("@foo#a/foo#ab", r_ab2['canonical_url'])
        self.assertEqual(2, search(claim_id=txo_chan_a.claim_id, limit=1)[0]['claims_in_channel'])
        self.assertEqual(0, search(claim_id=txo_chan_ab.claim_id, limit=1)[0]['claims_in_channel'])

        # change channel of stream
        self.assertEqual("@foo#a/foo#ab", search(claim_id=ab2_claim.claim_id, limit=1)[0]['canonical_url'])
        tx_ab2 = self.get_stream_update(tx_ab2, COIN, txo_chan_ab)
        advance(10, [tx_ab2])
        self.assertEqual("@foo#ab/foo#a", search(claim_id=ab2_claim.claim_id, limit=1)[0]['canonical_url'])
        # TODO: currently there is a bug where stream leaving a channel does not update that channels claims count
        self.assertEqual(2, search(claim_id=txo_chan_a.claim_id, limit=1)[0]['claims_in_channel'])
        # TODO: after bug is fixed remove test above and add test below
        #self.assertEqual(1, search(claim_id=txo_chan_a.claim_id, limit=1)[0]['claims_in_channel'])
        self.assertEqual(1, search(claim_id=txo_chan_ab.claim_id, limit=1)[0]['claims_in_channel'])

        # claim abandon updates claims_in_channel
        advance(11, [self.get_abandon(tx_ab2)])
        self.assertEqual(0, search(claim_id=txo_chan_ab.claim_id, limit=1)[0]['claims_in_channel'])

        # delete channel, invaliding stream claim signatures
        advance(12, [self.get_abandon(channel_update)])
        (r_a2,) = search(order_by=['creation_height'], limit=1)
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


@unittest.skip("port trending tests to ES")  # TODO: port trending tests to ES
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
            advance(zscore.TRENDING_WINDOW * window, [
                self.get_support(downwards, (20-window)*COIN),
                self.get_support(up_small, int(20+(window/10)*COIN)),
                self.get_support(up_medium, (20+(window*(2 if window == 7 else 1)))*COIN),
                self.get_support(up_biggly, (20+(window*(3 if window == 7 else 1)))*COIN),
            ])
        results = search(order_by=['trending_local'])
        self.assertEqual([c.claim_id for c in claims], [hexlify(c['claim_hash'][::-1]).decode() for c in results])
        self.assertEqual([10, 6, 2, 0, -2], [int(c['trending_local']) for c in results])
        self.assertEqual([53, 38, -32, 0, -6], [int(c['trending_global']) for c in results])
        self.assertEqual([4, 4, 2, 0, 1], [int(c['trending_group']) for c in results])
        self.assertEqual([53, 38, 2, 0, -6], [int(c['trending_mixed']) for c in results])

    def test_edge(self):
        problematic = self.get_stream('Problem', COIN)
        self.advance(1, [problematic])
        self.advance(zscore.TRENDING_WINDOW, [self.get_support(problematic, 53000000000)])
        self.advance(zscore.TRENDING_WINDOW * 2, [self.get_support(problematic, 500000000)])


@unittest.skip("filtering/blocking is applied during ES sync, this needs to be ported to integration test")
class TestContentBlocking(TestSQLDB):

    def test_blocking_and_filtering(self):
        # content claims and channels
        tx0 = self.get_channel('A Channel', COIN, '@channel1')
        regular_channel = tx0[0].outputs[0]
        tx1 = self.get_stream('Claim One', COIN, 'claim1')
        tx2 = self.get_stream('Claim Two', COIN, 'claim2', regular_channel)
        tx3 = self.get_stream('Claim Three', COIN, 'claim3')
        self.advance(1, [tx0, tx1, tx2, tx3])
        claim1, claim2, claim3 = tx1[0].outputs[0], tx2[0].outputs[0], tx3[0].outputs[0]

        # block and filter channels
        tx0 = self.get_channel('Blocking Channel', COIN, '@block')
        tx1 = self.get_channel('Filtering Channel', COIN, '@filter')
        blocking_channel = tx0[0].outputs[0]
        filtering_channel = tx1[0].outputs[0]
        self.sql.blocking_channel_hashes.add(blocking_channel.claim_hash)
        self.sql.filtering_channel_hashes.add(filtering_channel.claim_hash)
        self.advance(2, [tx0, tx1])
        self.assertEqual({}, dict(self.sql.blocked_streams))
        self.assertEqual({}, dict(self.sql.blocked_channels))
        self.assertEqual({}, dict(self.sql.filtered_streams))
        self.assertEqual({}, dict(self.sql.filtered_channels))

        # nothing blocked
        results, _ = reader.resolve([
            claim1.claim_name, claim2.claim_name,
            claim3.claim_name, regular_channel.claim_name
        ])
        self.assertEqual(claim1.claim_hash, results[0]['claim_hash'])
        self.assertEqual(claim2.claim_hash, results[1]['claim_hash'])
        self.assertEqual(claim3.claim_hash, results[2]['claim_hash'])
        self.assertEqual(regular_channel.claim_hash, results[3]['claim_hash'])

        # nothing filtered
        results, censor = censored_search()
        self.assertEqual(6, len(results))
        self.assertEqual(0, censor.total)
        self.assertEqual({}, censor.censored)

        # block claim reposted to blocking channel, also gets filtered
        repost_tx1 = self.get_repost(claim1.claim_id, COIN, blocking_channel)
        repost1 = repost_tx1[0].outputs[0]
        self.advance(3, [repost_tx1])
        self.assertEqual(
            {repost1.claim.repost.reference.claim_hash: blocking_channel.claim_hash},
            dict(self.sql.blocked_streams)
        )
        self.assertEqual({}, dict(self.sql.blocked_channels))
        self.assertEqual(
            {repost1.claim.repost.reference.claim_hash: blocking_channel.claim_hash},
            dict(self.sql.filtered_streams)
        )
        self.assertEqual({}, dict(self.sql.filtered_channels))

        # claim is blocked from results by direct repost
        results, censor = censored_search(text='Claim')
        self.assertEqual(2, len(results))
        self.assertEqual(claim2.claim_hash, results[0]['claim_hash'])
        self.assertEqual(claim3.claim_hash, results[1]['claim_hash'])
        self.assertEqual(1, censor.total)
        self.assertEqual({blocking_channel.claim_hash: 1}, censor.censored)
        results, _ = reader.resolve([claim1.claim_name])
        self.assertEqual(
            f"Resolve of 'claim1' was censored by channel with claim id '{blocking_channel.claim_id}'.",
            results[0].args[0]
        )
        results, _ = reader.resolve([
            claim2.claim_name, regular_channel.claim_name  # claim2 and channel still resolved
        ])
        self.assertEqual(claim2.claim_hash, results[0]['claim_hash'])
        self.assertEqual(regular_channel.claim_hash, results[1]['claim_hash'])

        # block claim indirectly by blocking its parent channel
        repost_tx2 = self.get_repost(regular_channel.claim_id, COIN, blocking_channel)
        repost2 = repost_tx2[0].outputs[0]
        self.advance(4, [repost_tx2])
        self.assertEqual(
            {repost1.claim.repost.reference.claim_hash: blocking_channel.claim_hash},
            dict(self.sql.blocked_streams)
        )
        self.assertEqual(
            {repost2.claim.repost.reference.claim_hash: blocking_channel.claim_hash},
            dict(self.sql.blocked_channels)
        )
        self.assertEqual(
            {repost1.claim.repost.reference.claim_hash: blocking_channel.claim_hash},
            dict(self.sql.filtered_streams)
        )
        self.assertEqual(
            {repost2.claim.repost.reference.claim_hash: blocking_channel.claim_hash},
            dict(self.sql.filtered_channels)
        )

        # claim in blocked channel is filtered from search and can't resolve
        results, censor = censored_search(text='Claim')
        self.assertEqual(1, len(results))
        self.assertEqual(claim3.claim_hash, results[0]['claim_hash'])
        self.assertEqual(2, censor.total)
        self.assertEqual({blocking_channel.claim_hash: 2}, censor.censored)
        results, _ = reader.resolve([
            claim2.claim_name, regular_channel.claim_name  # claim2 and channel don't resolve
        ])
        self.assertEqual(
            f"Resolve of 'claim2' was censored by channel with claim id '{blocking_channel.claim_id}'.",
            results[0].args[0]
        )
        self.assertEqual(
            f"Resolve of '@channel1' was censored by channel with claim id '{blocking_channel.claim_id}'.",
            results[1].args[0]
        )
        results, _ = reader.resolve([claim3.claim_name])  # claim3 still resolved
        self.assertEqual(claim3.claim_hash, results[0]['claim_hash'])

        # filtered claim is only filtered and not blocked
        repost_tx3 = self.get_repost(claim3.claim_id, COIN, filtering_channel)
        repost3 = repost_tx3[0].outputs[0]
        self.advance(5, [repost_tx3])
        self.assertEqual(
            {repost1.claim.repost.reference.claim_hash: blocking_channel.claim_hash},
            dict(self.sql.blocked_streams)
        )
        self.assertEqual(
            {repost2.claim.repost.reference.claim_hash: blocking_channel.claim_hash},
            dict(self.sql.blocked_channels)
        )
        self.assertEqual(
            {repost1.claim.repost.reference.claim_hash: blocking_channel.claim_hash,
            repost3.claim.repost.reference.claim_hash: filtering_channel.claim_hash},
            dict(self.sql.filtered_streams)
        )
        self.assertEqual(
            {repost2.claim.repost.reference.claim_hash: blocking_channel.claim_hash},
            dict(self.sql.filtered_channels)
        )

        # filtered claim doesn't return in search but is resolveable
        results, censor = censored_search(text='Claim')
        self.assertEqual(0, len(results))
        self.assertEqual(3, censor.total)
        self.assertEqual({blocking_channel.claim_hash: 2, filtering_channel.claim_hash: 1}, censor.censored)
        results, _ = reader.resolve([claim3.claim_name])  # claim3 still resolved
        self.assertEqual(claim3.claim_hash, results[0]['claim_hash'])

        # abandon unblocks content
        self.advance(6, [
            self.get_abandon(repost_tx1),
            self.get_abandon(repost_tx2),
            self.get_abandon(repost_tx3)
        ])
        self.assertEqual({}, dict(self.sql.blocked_streams))
        self.assertEqual({}, dict(self.sql.blocked_channels))
        self.assertEqual({}, dict(self.sql.filtered_streams))
        self.assertEqual({}, dict(self.sql.filtered_channels))
        results, censor = censored_search(text='Claim')
        self.assertEqual(3, len(results))
        self.assertEqual(0, censor.total)
        results, censor = censored_search()
        self.assertEqual(6, len(results))
        self.assertEqual(0, censor.total)
        results, _ = reader.resolve([
            claim1.claim_name, claim2.claim_name,
            claim3.claim_name, regular_channel.claim_name
        ])
        self.assertEqual(claim1.claim_hash, results[0]['claim_hash'])
        self.assertEqual(claim2.claim_hash, results[1]['claim_hash'])
        self.assertEqual(claim3.claim_hash, results[2]['claim_hash'])
        self.assertEqual(regular_channel.claim_hash, results[3]['claim_hash'])

    def test_pagination(self):
        one, two, three, four, five, six, seven, filter_channel = self.advance(1, [
            self.get_stream('One', COIN),
            self.get_stream('Two', COIN),
            self.get_stream('Three', COIN),
            self.get_stream('Four', COIN),
            self.get_stream('Five', COIN),
            self.get_stream('Six', COIN),
            self.get_stream('Seven', COIN),
            self.get_channel('Filtering Channel', COIN, '@filter'),
        ])
        self.sql.filtering_channel_hashes.add(filter_channel.claim_hash)

        # nothing filtered
        results, censor = censored_search(order_by='^height', offset=1, limit=3)
        self.assertEqual(3, len(results))
        self.assertEqual(
            [two.claim_hash, three.claim_hash, four.claim_hash],
            [r['claim_hash'] for r in results]
        )
        self.assertEqual(0, censor.total)

        # content filtered
        repost1, repost2 = self.advance(2, [
            self.get_repost(one.claim_id, COIN, filter_channel),
            self.get_repost(two.claim_id, COIN, filter_channel),
        ])
        results, censor = censored_search(order_by='^height', offset=1, limit=3)
        self.assertEqual(3, len(results))
        self.assertEqual(
            [four.claim_hash, five.claim_hash, six.claim_hash],
            [r['claim_hash'] for r in results]
        )
        self.assertEqual(2, censor.total)
        self.assertEqual({filter_channel.claim_hash: 2}, censor.censored)
