import asyncio
import json
import hashlib
import sys
from bisect import bisect_right
from binascii import hexlify, unhexlify
from collections import defaultdict
from typing import NamedTuple, List
from lbry.testcase import CommandTestCase
from lbry.wallet.transaction import Transaction, Output
from lbry.schema.compat import OldClaimMessage
from lbry.crypto.hash import sha256
from lbry.crypto.base58 import Base58


class ClaimStateValue(NamedTuple):
    claim_id: str
    activation_height: int
    active_in_lbrycrd: bool


class BaseResolveTestCase(CommandTestCase):

    def assertMatchESClaim(self, claim_from_es, claim_from_db):
        self.assertEqual(claim_from_es['claim_hash'][::-1].hex(), claim_from_db.claim_hash.hex())
        self.assertEqual(claim_from_es['claim_id'], claim_from_db.claim_hash.hex())
        self.assertEqual(claim_from_es['activation_height'], claim_from_db.activation_height, f"es height: {claim_from_es['activation_height']}, rocksdb height: {claim_from_db.activation_height}")
        self.assertEqual(claim_from_es['last_take_over_height'], claim_from_db.last_takeover_height)
        self.assertEqual(claim_from_es['tx_id'], claim_from_db.tx_hash[::-1].hex())
        self.assertEqual(claim_from_es['tx_nout'], claim_from_db.position)
        self.assertEqual(claim_from_es['amount'], claim_from_db.amount)
        self.assertEqual(claim_from_es['effective_amount'], claim_from_db.effective_amount)

    def assertMatchDBClaim(self, expected, claim):
        self.assertEqual(expected['claimid'], claim.claim_hash.hex())
        self.assertEqual(expected['validatheight'], claim.activation_height)
        self.assertEqual(expected['lasttakeoverheight'], claim.last_takeover_height)
        self.assertEqual(expected['txid'], claim.tx_hash[::-1].hex())
        self.assertEqual(expected['n'], claim.position)
        self.assertEqual(expected['amount'], claim.amount)
        self.assertEqual(expected['effectiveamount'], claim.effective_amount)

    async def assertResolvesToClaimId(self, name, claim_id):
        other = await self.resolve(name)
        if claim_id is None:
            self.assertIn('error', other)
            self.assertEqual(other['error']['name'], 'NOT_FOUND')
            claims_from_es = (await self.conductor.spv_node.server.session_manager.search_index.search(name=name))[0]
            claims_from_es = [c['claim_hash'][::-1].hex() for c in claims_from_es]
            self.assertNotIn(claim_id, claims_from_es)
        else:
            claim_from_es = await self.conductor.spv_node.server.session_manager.search_index.search(claim_id=claim_id)
            self.assertEqual(claim_id, other['claim_id'])
            self.assertEqual(claim_id, claim_from_es[0][0]['claim_hash'][::-1].hex())

    async def assertNoClaimForName(self, name: str):
        lbrycrd_winning = json.loads(await self.blockchain._cli_cmnd('getclaimsforname', name))
        stream, channel, _, _ = await self.conductor.spv_node.server.db.resolve(name)
        if 'claims' in lbrycrd_winning and lbrycrd_winning['claims'] is not None:
            self.assertEqual(len(lbrycrd_winning['claims']), 0)
        if stream is not None:
            self.assertIsInstance(stream, LookupError)
        else:
            self.assertIsInstance(channel, LookupError)
        claim_from_es = await self.conductor.spv_node.server.session_manager.search_index.search(name=name)
        self.assertListEqual([], claim_from_es[0])

    async def assertNoClaim(self, name: str, claim_id: str):
        expected = json.loads(await self.blockchain._cli_cmnd('getclaimsfornamebyid', name, '["' + claim_id + '"]'))
        if 'claims' in expected and expected['claims'] is not None:
            # ensure that if we do have the matching claim that it is not active
            self.assertEqual(expected['claims'][0]['effectiveamount'], 0)

        claim_from_es = await self.conductor.spv_node.server.session_manager.search_index.search(claim_id=claim_id)
        self.assertListEqual([], claim_from_es[0])
        claim = await self.conductor.spv_node.server.db.fs_getclaimbyid(claim_id)
        self.assertIsNone(claim)

    async def assertMatchWinningClaim(self, name):
        expected = json.loads(await self.blockchain._cli_cmnd('getclaimsfornamebybid', name, "[0]"))
        stream, channel, _, _ = await self.conductor.spv_node.server.db.resolve(name)
        claim = stream if stream else channel
        expected['claims'][0]['lasttakeoverheight'] = expected['lasttakeoverheight']
        await self._assertMatchClaim(expected['claims'][0], claim)
        return claim

    async def _assertMatchClaim(self, expected, claim):
        self.assertMatchDBClaim(expected, claim)
        claim_from_es = await self.conductor.spv_node.server.session_manager.search_index.search(
            claim_id=claim.claim_hash.hex()
        )
        self.assertEqual(len(claim_from_es[0]), 1)
        self.assertMatchESClaim(claim_from_es[0][0], claim)
        self._check_supports(claim.claim_hash.hex(), expected.get('supports', []),
                             claim_from_es[0][0]['support_amount'])

    async def assertMatchClaim(self, name, claim_id, is_active_in_lbrycrd=True):
        claim = await self.conductor.spv_node.server.db.fs_getclaimbyid(claim_id)
        claim_from_es = await self.conductor.spv_node.server.session_manager.search_index.search(
            claim_id=claim.claim_hash.hex()
        )
        self.assertEqual(len(claim_from_es[0]), 1)
        self.assertEqual(claim_from_es[0][0]['claim_hash'][::-1].hex(), claim.claim_hash.hex())
        self.assertMatchESClaim(claim_from_es[0][0], claim)

        expected = json.loads(await self.blockchain._cli_cmnd('getclaimsfornamebyid', name, '["' + claim_id + '"]'))
        if is_active_in_lbrycrd:
            if not expected:
                self.assertIsNone(claim)
                return
            expected['claims'][0]['lasttakeoverheight'] = expected['lasttakeoverheight']
            self.assertMatchDBClaim(expected['claims'][0], claim)
            self._check_supports(claim.claim_hash.hex(), expected['claims'][0].get('supports', []),
                                 claim_from_es[0][0]['support_amount'])
        else:
            if 'claims' in expected and expected['claims'] is not None:
                # ensure that if we do have the matching claim that it is not active
                self.assertEqual(expected['claims'][0]['effectiveamount'], 0)
        return claim

    async def assertMatchClaimIsWinning(self, name, claim_id):
        self.assertEqual(claim_id, (await self.assertMatchWinningClaim(name)).claim_hash.hex())
        await self.assertMatchClaimsForName(name)

    def _check_supports(self, claim_id, lbrycrd_supports, es_support_amount):
        total_lbrycrd_amount = 0.0
        total_es_amount = 0.0
        active_es_amount = 0.0
        db = self.conductor.spv_node.server.db
        es_supports = db.get_supports(bytes.fromhex(claim_id))

        # we're only concerned about active supports here, and they should match
        self.assertTrue(len(es_supports) >= len(lbrycrd_supports))

        for i, (tx_num, position, amount) in enumerate(es_supports):
            total_es_amount += amount
            valid_height = db.get_activation(tx_num, position, is_support=True)
            if valid_height > db.db_height:
                continue
            active_es_amount += amount
            txid = db.prefix_db.tx_hash.get(tx_num, deserialize_value=False)[::-1].hex()
            support = next(filter(lambda s: s['txid'] == txid and s['n'] == position, lbrycrd_supports))
            total_lbrycrd_amount += support['amount']
            self.assertEqual(support['height'], bisect_right(db.tx_counts, tx_num))
            self.assertEqual(support['validatheight'], valid_height)

        self.assertEqual(total_es_amount, es_support_amount)
        self.assertEqual(active_es_amount, total_lbrycrd_amount)

    async def assertMatchClaimsForName(self, name):
        expected = json.loads(await self.blockchain._cli_cmnd('getclaimsforname', name, "", "true"))
        db = self.conductor.spv_node.server.db

        for c in expected['claims']:
            c['lasttakeoverheight'] = expected['lasttakeoverheight']
            claim_id = c['claimid']
            claim_hash = bytes.fromhex(claim_id)
            claim = db._fs_get_claim_by_hash(claim_hash)
            self.assertMatchDBClaim(c, claim)

            claim_from_es = await self.conductor.spv_node.server.session_manager.search_index.search(
                claim_id=claim_id
            )
            self.assertEqual(len(claim_from_es[0]), 1)
            self.assertEqual(claim_from_es[0][0]['claim_hash'][::-1].hex(), claim_id)
            self.assertMatchESClaim(claim_from_es[0][0], claim)
            self._check_supports(claim_id, c.get('supports', []),
                                 claim_from_es[0][0]['support_amount'])

    async def assertNameState(self, height: int, name: str, winning_claim_id: str, last_takeover_height: int,
                               non_winning_claims: List[ClaimStateValue]):
        self.assertEqual(height, self.conductor.spv_node.server.db.db_height)
        await self.assertMatchClaimIsWinning(name, winning_claim_id)
        for non_winning in non_winning_claims:
            claim = await self.assertMatchClaim(
                name, non_winning.claim_id, is_active_in_lbrycrd=non_winning.active_in_lbrycrd
            )
            self.assertEqual(non_winning.activation_height, claim.activation_height)
            self.assertEqual(last_takeover_height, claim.last_takeover_height)


class ResolveCommand(BaseResolveTestCase):
    async def test_colliding_short_id(self):
        prefixes = defaultdict(list)

        colliding_claim_ids = []
        first_claims_one_char_shortid = {}

        while True:
            chan = self.get_claim_id(
                await self.channel_create('@abc', '0.01', allow_duplicate_name=True)
            )
            if chan[:1] not in first_claims_one_char_shortid:
                first_claims_one_char_shortid[chan[:1]] = chan
            prefixes[chan[:2]].append(chan)
            if len(prefixes[chan[:2]]) > 1:
                colliding_claim_ids.extend(prefixes[chan[:2]])
                break
        first_claim = first_claims_one_char_shortid[colliding_claim_ids[0][:1]]
        await self.assertResolvesToClaimId(
            f'@abc#{colliding_claim_ids[0][:1]}', first_claim
        )
        collision_depth = 0
        for c1, c2 in zip(colliding_claim_ids[0], colliding_claim_ids[1]):
            if c1 == c2:
                collision_depth += 1
            else:
                break
        await self.assertResolvesToClaimId(f'@abc#{colliding_claim_ids[0][:2]}', colliding_claim_ids[0])
        await self.assertResolvesToClaimId(f'@abc#{colliding_claim_ids[0][:7]}', colliding_claim_ids[0])
        await self.assertResolvesToClaimId(f'@abc#{colliding_claim_ids[0][:17]}', colliding_claim_ids[0])
        await self.assertResolvesToClaimId(f'@abc#{colliding_claim_ids[0]}', colliding_claim_ids[0])
        await self.assertResolvesToClaimId(f'@abc#{colliding_claim_ids[1][:collision_depth + 1]}', colliding_claim_ids[1])
        await self.assertResolvesToClaimId(f'@abc#{colliding_claim_ids[1][:7]}', colliding_claim_ids[1])
        await self.assertResolvesToClaimId(f'@abc#{colliding_claim_ids[1][:17]}', colliding_claim_ids[1])
        await self.assertResolvesToClaimId(f'@abc#{colliding_claim_ids[1]}', colliding_claim_ids[1])

        # test resolving different streams for a channel using short urls
        self.get_claim_id(
            await self.stream_create('foo1', '0.01', channel_id=colliding_claim_ids[0])
        )
        self.get_claim_id(
            await self.stream_create('foo2', '0.01', channel_id=colliding_claim_ids[0])
        )
        duplicated_resolved = list((
            await self.ledger.resolve([], [
                f'@abc#{colliding_claim_ids[0][:2]}/foo1', f'@abc#{colliding_claim_ids[0][:2]}/foo2'
            ])
        ).values())
        self.assertEqual('foo1', duplicated_resolved[0].normalized_name)
        self.assertEqual('foo2', duplicated_resolved[1].normalized_name)

    async def test_abandon_channel_and_claims_in_same_tx(self):
        channel_id = self.get_claim_id(
            await self.channel_create('@abc', '0.01')
        )
        await self.stream_create('foo', '0.01', channel_id=channel_id)
        await self.channel_update(channel_id, bid='0.001')
        foo2_id = self.get_claim_id(await self.stream_create('foo2', '0.01', channel_id=channel_id))
        await self.stream_update(foo2_id, bid='0.0001', channel_id=channel_id, confirm=False)
        tx = await self.stream_create('foo3', '0.01', channel_id=channel_id, confirm=False, return_tx=True)
        await self.ledger.wait(tx)

        # db = self.conductor.spv_node.server.bp.db
        # claims = list(db.all_claims_producer())
        # print("claims", claims)
        await self.daemon.jsonrpc_txo_spend(blocking=True)
        await self.generate(1)
        await self.assertNoClaimForName('@abc')
        await self.assertNoClaimForName('foo')
        await self.assertNoClaimForName('foo2')
        await self.assertNoClaimForName('foo3')

    async def test_resolve_response(self):
        channel_id = self.get_claim_id(
            await self.channel_create('@abc', '0.01')
        )

        # resolving a channel @abc
        response = await self.resolve('lbry://@abc')
        self.assertEqual(response['name'], '@abc')
        self.assertEqual(response['value_type'], 'channel')
        self.assertEqual(response['meta']['claims_in_channel'], 0)

        await self.stream_create('foo', '0.01', channel_id=channel_id)
        await self.stream_create('foo2', '0.01', channel_id=channel_id)

        # resolving a channel @abc with some claims in it
        response['confirmations'] += 2
        response['meta']['claims_in_channel'] = 2
        self.assertEqual(response, await self.resolve('lbry://@abc'))

        # resolving claim foo within channel @abc
        claim = await self.resolve('lbry://@abc/foo')
        self.assertEqual(claim['name'], 'foo')
        self.assertEqual(claim['value_type'], 'stream')
        self.assertEqual(claim['signing_channel']['name'], '@abc')
        self.assertTrue(claim['is_channel_signature_valid'])
        self.assertEqual(
            claim['timestamp'],
            self.ledger.headers.estimated_timestamp(claim['height'])
        )
        self.assertEqual(
            claim['signing_channel']['timestamp'],
            self.ledger.headers.estimated_timestamp(claim['signing_channel']['height'])
        )

        # resolving claim foo by itself
        self.assertEqual(claim, await self.resolve('lbry://foo'))
        # resolving from the given permanent url
        self.assertEqual(claim, await self.resolve(claim['permanent_url']))

        # resolving multiple at once
        response = await self.out(self.daemon.jsonrpc_resolve(['lbry://foo', 'lbry://foo2']))
        self.assertSetEqual({'lbry://foo', 'lbry://foo2'}, set(response))
        claim = response['lbry://foo2']
        self.assertEqual(claim['name'], 'foo2')
        self.assertEqual(claim['value_type'], 'stream')
        self.assertEqual(claim['signing_channel']['name'], '@abc')
        self.assertTrue(claim['is_channel_signature_valid'])

        # resolve has correct confirmations
        tx_details = await self.blockchain.get_raw_transaction(claim['txid'])
        self.assertEqual(claim['confirmations'], json.loads(tx_details)['confirmations'])

        # FIXME :  claimname/updateclaim is gone. #3480 wip, unblock #3479"
        # resolve handles invalid data
        # await self.blockchain_claim_name("gibberish", hexlify(b"{'invalid':'json'}").decode(), "0.1")
        # await self.generate(1)
        # response = await self.out(self.daemon.jsonrpc_resolve("lbry://gibberish"))
        # self.assertSetEqual({'lbry://gibberish'}, set(response))
        # claim = response['lbry://gibberish']
        # self.assertEqual(claim['name'], 'gibberish')
        # self.assertNotIn('value', claim)

        # resolve retries
        await self.conductor.spv_node.stop()
        resolve_task = asyncio.create_task(self.resolve('foo'))
        await self.conductor.spv_node.start(self.conductor.lbcwallet_node)
        self.assertIsNotNone((await resolve_task)['claim_id'])

    async def test_winning_by_effective_amount(self):
        # first one remains winner unless something else changes
        claim_id1 = self.get_claim_id(
            await self.channel_create('@foo', allow_duplicate_name=True))
        await self.assertResolvesToClaimId('@foo', claim_id1)
        claim_id2 = self.get_claim_id(
            await self.channel_create('@foo', allow_duplicate_name=True))
        await self.assertResolvesToClaimId('@foo', claim_id1)
        claim_id3 = self.get_claim_id(
            await self.channel_create('@foo', allow_duplicate_name=True))
        await self.assertResolvesToClaimId('@foo', claim_id1)
        # supports change the winner
        await self.support_create(claim_id3, '0.09')
        await self.assertResolvesToClaimId('@foo', claim_id3)
        await self.support_create(claim_id2, '0.19')
        await self.assertResolvesToClaimId('@foo', claim_id2)
        await self.support_create(claim_id1, '0.29')
        await self.assertResolvesToClaimId('@foo', claim_id1)

        await self.support_abandon(claim_id1)
        await self.assertResolvesToClaimId('@foo', claim_id2)

    async def test_resolve_duplicate_name_in_channel(self):
        db_resolve = self.conductor.spv_node.server.db.resolve
        # first one remains winner unless something else changes
        channel_id = self.get_claim_id(await self.channel_create('@foo'))

        file_path = self.create_upload_file(data=b'hi!')
        tx = await self.daemon.jsonrpc_stream_create('duplicate', '0.1', file_path=file_path, allow_duplicate_name=True, channel_id=channel_id)
        await self.ledger.wait(tx)

        first_claim = tx.outputs[0].claim_id

        file_path = self.create_upload_file(data=b'hi!')
        tx = await self.daemon.jsonrpc_stream_create('duplicate', '0.1', file_path=file_path, allow_duplicate_name=True, channel_id=channel_id)
        await self.ledger.wait(tx)
        duplicate_claim = tx.outputs[0].claim_id
        await self.generate(1)

        stream, channel, _, _ = await db_resolve(f"@foo:{channel_id}/duplicate:{first_claim}")
        self.assertEqual(stream.claim_hash.hex(), first_claim)
        self.assertEqual(channel.claim_hash.hex(), channel_id)
        stream, channel, _, _ = await db_resolve(f"@foo:{channel_id}/duplicate:{duplicate_claim}")
        self.assertEqual(stream.claim_hash.hex(), duplicate_claim)
        self.assertEqual(channel.claim_hash.hex(), channel_id)

    async def test_advanced_resolve(self):
        claim_id1 = self.get_claim_id(
            await self.stream_create('foo', '0.7', allow_duplicate_name=True))
        await self.assertResolvesToClaimId('foo$1', claim_id1)
        claim_id2 = self.get_claim_id(
            await self.stream_create('foo', '0.8', allow_duplicate_name=True))
        await self.assertResolvesToClaimId('foo$1', claim_id2)
        await self.assertResolvesToClaimId('foo$2', claim_id1)
        claim_id3 = self.get_claim_id(
            await self.stream_create('foo', '0.9', allow_duplicate_name=True))
        # plain winning claim
        await self.assertResolvesToClaimId('foo', claim_id3)

        # amount order resolution
        await self.assertResolvesToClaimId('foo$1', claim_id3)
        await self.assertResolvesToClaimId('foo$2', claim_id2)
        await self.assertResolvesToClaimId('foo$3', claim_id1)
        await self.assertResolvesToClaimId('foo$4', None)

    # async def test_partial_claim_id_resolve(self):
    #     # add some noise
    #     await self.channel_create('@abc', '0.1', allow_duplicate_name=True)
    #     await self.channel_create('@abc', '0.2', allow_duplicate_name=True)
    #     await self.channel_create('@abc', '1.0', allow_duplicate_name=True)
    #
    #     channel_id = self.get_claim_id(await self.channel_create('@abc', '1.1', allow_duplicate_name=True))
    #     await self.assertResolvesToClaimId(f'@abc', channel_id)
    #     await self.assertResolvesToClaimId(f'@abc#{channel_id[:10]}', channel_id)
    #     await self.assertResolvesToClaimId(f'@abc#{channel_id}', channel_id)
    #
    #     channel = await self.claim_get(channel_id)
    #     await self.assertResolvesToClaimId(channel['short_url'], channel_id)
    #     await self.assertResolvesToClaimId(channel['canonical_url'], channel_id)
    #     await self.assertResolvesToClaimId(channel['permanent_url'], channel_id)
    #
    #     # add some noise
    #     await self.stream_create('foo', '0.1', allow_duplicate_name=True, channel_id=channel['claim_id'])
    #     await self.stream_create('foo', '0.2', allow_duplicate_name=True, channel_id=channel['claim_id'])
    #     await self.stream_create('foo', '0.3', allow_duplicate_name=True, channel_id=channel['claim_id'])
    #
    #     claim_id1 = self.get_claim_id(
    #         await self.stream_create('foo', '0.7', allow_duplicate_name=True, channel_id=channel['claim_id']))
    #     claim1 = await self.claim_get(claim_id=claim_id1)
    #
    #     await self.assertResolvesToClaimId('foo', claim_id1)
    #     await self.assertResolvesToClaimId('@abc/foo', claim_id1)
    #     await self.assertResolvesToClaimId(claim1['short_url'], claim_id1)
    #     await self.assertResolvesToClaimId(claim1['canonical_url'], claim_id1)
    #     await self.assertResolvesToClaimId(claim1['permanent_url'], claim_id1)
    #
    #     claim_id2 = self.get_claim_id(
    #         await self.stream_create('foo', '0.8', allow_duplicate_name=True, channel_id=channel['claim_id']))
    #     claim2 = await self.claim_get(claim_id=claim_id2)
    #     await self.assertResolvesToClaimId('foo', claim_id2)
    #     await self.assertResolvesToClaimId('@abc/foo', claim_id2)
    #     await self.assertResolvesToClaimId(claim2['short_url'], claim_id2)
    #     await self.assertResolvesToClaimId(claim2['canonical_url'], claim_id2)
    #     await self.assertResolvesToClaimId(claim2['permanent_url'], claim_id2)

    async def test_abandoned_channel_with_signed_claims(self):
        channel = (await self.channel_create('@abc', '1.0'))['outputs'][0]
        orphan_claim = await self.stream_create('on-channel-claim', '0.0001', channel_id=channel['claim_id'])
        abandoned_channel_id = channel['claim_id']
        await self.channel_abandon(txid=channel['txid'], nout=0)
        channel = (await self.channel_create('@abc', '1.0'))['outputs'][0]
        orphan_claim_id = self.get_claim_id(orphan_claim)

        # Original channel doesn't exists anymore, so the signature is invalid. For invalid signatures, resolution is
        # only possible outside a channel
        self.assertEqual(
            {'error': {
                'name': 'NOT_FOUND',
                'text': 'Could not find claim at "lbry://@abc/on-channel-claim".',
            }},
            await self.resolve('lbry://@abc/on-channel-claim')
        )
        response = await self.resolve('lbry://on-channel-claim')
        self.assertFalse(response['is_channel_signature_valid'])
        self.assertEqual({'channel_id': abandoned_channel_id}, response['signing_channel'])
        direct_uri = 'lbry://on-channel-claim#' + orphan_claim_id
        response = await self.resolve(direct_uri)
        self.assertFalse(response['is_channel_signature_valid'])
        self.assertEqual({'channel_id': abandoned_channel_id}, response['signing_channel'])
        await self.stream_abandon(claim_id=orphan_claim_id)

        uri = 'lbry://@abc/on-channel-claim'
        # now, claim something on this channel (it will update the invalid claim, but we save and forcefully restore)
        valid_claim = await self.stream_create('on-channel-claim', '0.00000001', channel_id=channel['claim_id'])
        # resolves normally
        response = await self.resolve(uri)
        self.assertTrue(response['is_channel_signature_valid'])

        # ooops! claimed a valid conflict! (this happens on the wild, mostly by accident or race condition)
        await self.stream_create(
            'on-channel-claim', '0.00000001', channel_id=channel['claim_id'], allow_duplicate_name=True
        )

        # it still resolves! but to the older claim
        response = await self.resolve(uri)
        self.assertTrue(response['is_channel_signature_valid'])
        self.assertEqual(response['txid'], valid_claim['txid'])
        claims = [await self.resolve('on-channel-claim'), await self.resolve('on-channel-claim$2')]
        self.assertEqual(2, len(claims))
        self.assertEqual(
            {channel['claim_id']}, {claim['signing_channel']['claim_id'] for claim in claims}
        )

    async def test_normalization_resolution(self):

        one = 'ΣίσυφοςﬁÆ'
        two = 'ΣΊΣΥΦΟσFIæ'

        c1 = await self.stream_create(one, '0.1')
        c2 = await self.stream_create(two, '0.2')

        loser_id = self.get_claim_id(c1)
        winner_id = self.get_claim_id(c2)

        # winning_one = await self.check_lbrycrd_winning(one)
        await self.assertMatchClaimIsWinning(two, winner_id)

        claim1 = await self.resolve(f'lbry://{one}')
        claim2 = await self.resolve(f'lbry://{two}')
        claim3 = await self.resolve(f'lbry://{one}:{winner_id[:5]}')
        claim4 = await self.resolve(f'lbry://{two}:{winner_id[:5]}')

        claim5 = await self.resolve(f'lbry://{one}:{loser_id[:5]}')
        claim6 = await self.resolve(f'lbry://{two}:{loser_id[:5]}')

        self.assertEqual(winner_id, claim1['claim_id'])
        self.assertEqual(winner_id, claim2['claim_id'])
        self.assertEqual(winner_id, claim3['claim_id'])
        self.assertEqual(winner_id, claim4['claim_id'])

        self.assertEqual(two, claim1['name'])
        self.assertEqual(two, claim2['name'])
        self.assertEqual(two, claim3['name'])
        self.assertEqual(two, claim4['name'])

        self.assertEqual(loser_id, claim5['claim_id'])
        self.assertEqual(loser_id, claim6['claim_id'])
        self.assertEqual(one, claim5['name'])
        self.assertEqual(one, claim6['name'])

    async def test_resolve_old_claim(self):
        channel = await self.daemon.jsonrpc_channel_create('@olds', '1.0', blocking=True)
        await self.confirm_tx(channel.id)
        address = channel.outputs[0].get_address(self.account.ledger)
        claim = generate_signed_legacy(address, channel.outputs[0])
        tx = await Transaction.claim_create('example', claim.SerializeToString(), 1, address, [self.account], self.account)
        await tx.sign([self.account])
        await self.broadcast_and_confirm(tx)

        response = await self.resolve('@olds/example')
        self.assertTrue('is_channel_signature_valid' in response, str(response))
        self.assertTrue(response['is_channel_signature_valid'])

        claim.publisherSignature.signature = bytes(reversed(claim.publisherSignature.signature))
        tx = await Transaction.claim_create(
            'bad_example', claim.SerializeToString(), 1, address, [self.account], self.account
        )
        await tx.sign([self.account])
        await self.broadcast_and_confirm(tx)

        response = await self.resolve('bad_example')
        self.assertFalse(response['is_channel_signature_valid'])
        self.assertEqual(
            {'error': {
                'name': 'NOT_FOUND',
                'text': 'Could not find claim at "@olds/bad_example".',
            }},
            await self.resolve('@olds/bad_example')
        )

    async def test_resolve_with_includes(self):
        wallet2 = await self.daemon.jsonrpc_wallet_create('wallet2', create_account=True)
        address2 = await self.daemon.jsonrpc_address_unused(wallet_id=wallet2.id)

        await self.wallet_send('1.0', address2)

        stream = await self.stream_create(
            'priced', '0.1', wallet_id=wallet2.id,
            fee_amount='0.5', fee_currency='LBC', fee_address=address2
        )
        stream_id = self.get_claim_id(stream)

        resolve = await self.resolve('priced')
        self.assertNotIn('is_my_output', resolve)
        self.assertNotIn('purchase_receipt', resolve)
        self.assertNotIn('sent_supports', resolve)
        self.assertNotIn('sent_tips', resolve)
        self.assertNotIn('received_tips', resolve)

        # is_my_output
        resolve = await self.resolve('priced', include_is_my_output=True)
        self.assertFalse(resolve['is_my_output'])
        resolve = await self.resolve('priced', wallet_id=wallet2.id, include_is_my_output=True)
        self.assertTrue(resolve['is_my_output'])

        # purchase receipt
        resolve = await self.resolve('priced', include_purchase_receipt=True)
        self.assertNotIn('purchase_receipt', resolve)
        await self.purchase_create(stream_id)
        resolve = await self.resolve('priced', include_purchase_receipt=True)
        self.assertEqual('0.5', resolve['purchase_receipt']['amount'])

        # my supports and my tips
        resolve = await self.resolve(
            'priced', include_sent_supports=True, include_sent_tips=True, include_received_tips=True
        )
        self.assertEqual('0.0', resolve['sent_supports'])
        self.assertEqual('0.0', resolve['sent_tips'])
        self.assertEqual('0.0', resolve['received_tips'])
        await self.support_create(stream_id, '0.3')
        await self.support_create(stream_id, '0.2')
        await self.support_create(stream_id, '0.4', tip=True)
        await self.support_create(stream_id, '0.5', tip=True)
        resolve = await self.resolve(
            'priced', include_sent_supports=True, include_sent_tips=True, include_received_tips=True
        )
        self.assertEqual('0.5', resolve['sent_supports'])
        self.assertEqual('0.9', resolve['sent_tips'])
        self.assertEqual('0.0', resolve['received_tips'])

        resolve = await self.resolve(
            'priced', include_sent_supports=True, include_sent_tips=True, include_received_tips=True,
            wallet_id=wallet2.id
        )
        self.assertEqual('0.0', resolve['sent_supports'])
        self.assertEqual('0.0', resolve['sent_tips'])
        self.assertEqual('0.9', resolve['received_tips'])
        self.assertEqual('1.4', resolve['meta']['support_amount'])

        # make sure nothing is leaked between wallets through cached tx/txos
        resolve = await self.resolve('priced')
        self.assertNotIn('is_my_output', resolve)
        self.assertNotIn('purchase_receipt', resolve)
        self.assertNotIn('sent_supports', resolve)
        self.assertNotIn('sent_tips', resolve)
        self.assertNotIn('received_tips', resolve)


class ResolveClaimTakeovers(BaseResolveTestCase):
    async def test_channel_invalidation(self):
        channel_id = (await self.channel_create('@test', '0.1'))['outputs'][0]['claim_id']
        channel_id2 = (await self.channel_create('@other', '0.1'))['outputs'][0]['claim_id']

        async def make_claim(name, amount, channel_id=None):
            return (
            await self.stream_create(name, amount, channel_id=channel_id)
        )['outputs'][0]['claim_id']

        unsigned_then_signed = await make_claim('unsigned_then_signed', '0.1')
        unsigned_then_updated_then_signed = await make_claim('unsigned_then_updated_then_signed', '0.1')
        signed_then_unsigned = await make_claim(
            'signed_then_unsigned', '0.01',  channel_id=channel_id
        )
        signed_then_signed_different_chan = await make_claim(
            'signed_then_signed_different_chan', '0.01', channel_id=channel_id
        )

        self.assertIn("error", await self.resolve('@test/unsigned_then_signed'))
        await self.assertMatchClaimIsWinning('unsigned_then_signed', unsigned_then_signed)
        self.assertIn("error", await self.resolve('@test/unsigned_then_updated_then_signed'))
        await self.assertMatchClaimIsWinning('unsigned_then_updated_then_signed', unsigned_then_updated_then_signed)
        self.assertDictEqual(
            await self.resolve('@test/signed_then_unsigned'), await self.resolve('signed_then_unsigned')
        )
        await self.assertMatchClaimIsWinning('signed_then_unsigned', signed_then_unsigned)
        # sign 'unsigned_then_signed' and update it
        await self.ledger.wait(await self.daemon.jsonrpc_stream_update(
            unsigned_then_signed, '0.09', channel_id=channel_id))

        await self.ledger.wait(await self.daemon.jsonrpc_stream_update(unsigned_then_updated_then_signed, '0.09'))
        await self.ledger.wait(await self.daemon.jsonrpc_stream_update(
            unsigned_then_updated_then_signed, '0.09', channel_id=channel_id))

        await self.ledger.wait(await self.daemon.jsonrpc_stream_update(
            signed_then_unsigned, '0.09', clear_channel=True))

        await self.ledger.wait(await self.daemon.jsonrpc_stream_update(
            signed_then_signed_different_chan, '0.09', channel_id=channel_id2))

        await self.daemon.jsonrpc_txo_spend(type='channel', claim_id=channel_id)

        signed3 = await make_claim('signed3', '0.01',  channel_id=channel_id)
        signed4 = await make_claim('signed4', '0.01',  channel_id=channel_id2)

        self.assertIn("error", await self.resolve('@test'))
        self.assertIn("error", await self.resolve('@test/signed1'))
        self.assertIn("error", await self.resolve('@test/unsigned_then_updated_then_signed'))
        self.assertIn("error", await self.resolve('@test/unsigned_then_signed'))
        self.assertIn("error", await self.resolve('@test/signed3'))
        self.assertIn("error", await self.resolve('@test/signed4'))

        await self.assertMatchClaimIsWinning('signed_then_unsigned', signed_then_unsigned)
        await self.assertMatchClaimIsWinning('unsigned_then_signed', unsigned_then_signed)
        await self.assertMatchClaimIsWinning('unsigned_then_updated_then_signed', unsigned_then_updated_then_signed)
        await self.assertMatchClaimIsWinning('signed_then_signed_different_chan', signed_then_signed_different_chan)
        await self.assertMatchClaimIsWinning('signed3', signed3)
        await self.assertMatchClaimIsWinning('signed4', signed4)

        self.assertDictEqual(await self.resolve('@other/signed_then_signed_different_chan'),
                             await self.resolve('signed_then_signed_different_chan'))
        self.assertDictEqual(await self.resolve('@other/signed4'),
                             await self.resolve('signed4'))

        self.assertEqual(2, len(await self.claim_search(channel_ids=[channel_id2])))

        await self.channel_update(channel_id2)
        await make_claim('third_signed', '0.01', channel_id=channel_id2)
        self.assertEqual(3, len(await self.claim_search(channel_ids=[channel_id2])))

    async def _test_activation_delay(self):
        name = 'derp'
        # initially claim the name
        first_claim_id = (await self.stream_create(name, '0.1',  allow_duplicate_name=True))['outputs'][0]['claim_id']
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(320)
        # a claim of higher amount made now will have a takeover delay of 10
        second_claim_id = (await self.stream_create(name, '0.2',  allow_duplicate_name=True))['outputs'][0]['claim_id']
        # sanity check
        self.assertNotEqual(first_claim_id, second_claim_id)
        # takeover should not have happened yet
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(9)
        # not yet
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(1)
        # the new claim should have activated
        await self.assertMatchClaimIsWinning(name, second_claim_id)
        return first_claim_id, second_claim_id

    async def test_activation_delay(self):
        await self._test_activation_delay()

    async def test_activation_delay_then_abandon_then_reclaim(self):
        name = 'derp'
        first_claim_id, second_claim_id = await self._test_activation_delay()
        await self.daemon.jsonrpc_txo_spend(type='stream', claim_id=first_claim_id)
        await self.daemon.jsonrpc_txo_spend(type='stream', claim_id=second_claim_id)
        await self.generate(1)
        await self.assertNoClaimForName(name)
        await self._test_activation_delay()

    async def create_stream_claim(self, amount: str, name='derp') -> str:
        return (await self.stream_create(name, amount,  allow_duplicate_name=True))['outputs'][0]['claim_id']

    async def assertNameState(self, height: int, name: str, winning_claim_id: str, last_takeover_height: int,
                               non_winning_claims: List[ClaimStateValue]):
        self.assertEqual(height, self.conductor.spv_node.server.db.db_height)
        await self.assertMatchClaimIsWinning(name, winning_claim_id)
        for non_winning in non_winning_claims:
            claim = await self.assertMatchClaim(name,
                non_winning.claim_id, is_active_in_lbrycrd=non_winning.active_in_lbrycrd
            )
            self.assertEqual(non_winning.activation_height, claim.activation_height)
            self.assertEqual(last_takeover_height, claim.last_takeover_height)

    async def test_delay_takeover_with_update(self):
        name = 'derp'
        first_claim_id = await self.create_stream_claim('0.2', name)
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(320)
        second_claim_id = await self.create_stream_claim('0.1', name)
        third_claim_id = await self.create_stream_claim('0.1', name)
        await self.generate(8)
        await self.assertNameState(
            height=537, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=False),
                ClaimStateValue(third_claim_id, activation_height=539, active_in_lbrycrd=False)
            ]
        )

        await self.generate(1)
        await self.assertNameState(
            height=538, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=539, active_in_lbrycrd=False)
            ]
        )

        await self.generate(1)
        await self.assertNameState(
            height=539, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=539, active_in_lbrycrd=True)
            ]
        )

        await self.daemon.jsonrpc_stream_update(third_claim_id, '0.21')
        await self.generate(1)
        await self.assertNameState(
            height=540, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=550, active_in_lbrycrd=False)
            ]
        )

        await self.generate(9)
        await self.assertNameState(
            height=549, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=550, active_in_lbrycrd=False)
            ]
        )

        await self.generate(1)
        await self.assertNameState(
            height=550, name=name, winning_claim_id=third_claim_id, last_takeover_height=550,
            non_winning_claims=[
                ClaimStateValue(first_claim_id, activation_height=207, active_in_lbrycrd=True),
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True)
            ]
        )

    async def test_delay_takeover_with_update_then_update_to_lower_before_takeover(self):
        name = 'derp'
        first_claim_id = await self.create_stream_claim('0.2', name)
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(320)
        second_claim_id = await self.create_stream_claim('0.1', name)
        third_claim_id = await self.create_stream_claim('0.1', name)
        await self.generate(8)
        await self.assertNameState(
            height=537, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=False),
                ClaimStateValue(third_claim_id, activation_height=539, active_in_lbrycrd=False)
            ]
        )

        await self.generate(1)
        await self.assertNameState(
            height=538, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=539, active_in_lbrycrd=False)
            ]
        )

        await self.generate(1)
        await self.assertNameState(
            height=539, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=539, active_in_lbrycrd=True)
            ]
        )

        await self.daemon.jsonrpc_stream_update(third_claim_id, '0.21')
        await self.generate(1)
        await self.assertNameState(
            height=540, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=550, active_in_lbrycrd=False)
            ]
        )

        await self.generate(8)
        await self.assertNameState(
            height=548, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=550, active_in_lbrycrd=False)
            ]
        )

        await self.daemon.jsonrpc_stream_update(third_claim_id, '0.09')

        await self.generate(1)
        await self.assertNameState(
            height=549, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=559, active_in_lbrycrd=False)
            ]
        )
        await self.generate(10)
        await self.assertNameState(
            height=559, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=559, active_in_lbrycrd=True)
            ]
        )

    async def test_delay_takeover_with_update_then_update_to_lower_on_takeover(self):
        name = 'derp'
        first_claim_id = await self.create_stream_claim('0.2', name)
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(320)
        second_claim_id = await self.create_stream_claim('0.1', name)
        third_claim_id = await self.create_stream_claim('0.1', name)
        await self.generate(8)
        await self.assertNameState(
            height=537, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=False),
                ClaimStateValue(third_claim_id, activation_height=539, active_in_lbrycrd=False)
            ]
        )

        await self.generate(1)
        await self.assertNameState(
            height=538, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=539, active_in_lbrycrd=False)
            ]
        )

        await self.generate(1)
        await self.assertNameState(
            height=539, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=539, active_in_lbrycrd=True)
            ]
        )

        await self.daemon.jsonrpc_stream_update(third_claim_id, '0.21')
        await self.generate(1)
        await self.assertNameState(
            height=540, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=550, active_in_lbrycrd=False)
            ]
        )

        await self.generate(8)
        await self.assertNameState(
            height=548, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=550, active_in_lbrycrd=False)
            ]
        )

        await self.generate(1)
        await self.assertNameState(
            height=549, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=550, active_in_lbrycrd=False)
            ]
        )

        await self.daemon.jsonrpc_stream_update(third_claim_id, '0.09')
        await self.generate(1)
        await self.assertNameState(
            height=550, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=560, active_in_lbrycrd=False)
            ]
        )
        await self.generate(10)
        await self.assertNameState(
            height=560, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=560, active_in_lbrycrd=True)
            ]
        )

    async def test_delay_takeover_with_update_then_update_to_lower_after_takeover(self):
        name = 'derp'
        first_claim_id = await self.create_stream_claim('0.2', name)
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(320)
        second_claim_id = await self.create_stream_claim('0.1', name)
        third_claim_id = await self.create_stream_claim('0.1', name)
        await self.generate(8)
        await self.assertNameState(
            height=537, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=False),
                ClaimStateValue(third_claim_id, activation_height=539, active_in_lbrycrd=False)
            ]
        )
        await self.generate(1)
        await self.assertNameState(
            height=538, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=539, active_in_lbrycrd=False)
            ]
        )

        await self.generate(1)
        await self.assertNameState(
            height=539, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=539, active_in_lbrycrd=True)
            ]
        )

        await self.daemon.jsonrpc_stream_update(third_claim_id, '0.21')
        await self.generate(1)
        await self.assertNameState(
            height=540, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=550, active_in_lbrycrd=False)
            ]
        )

        await self.generate(8)
        await self.assertNameState(
            height=548, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=550, active_in_lbrycrd=False)
            ]
        )

        await self.generate(1)
        await self.assertNameState(
            height=549, name=name, winning_claim_id=first_claim_id, last_takeover_height=207,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=550, active_in_lbrycrd=False)
            ]
        )

        await self.generate(1)
        await self.assertNameState(
            height=550, name=name, winning_claim_id=third_claim_id, last_takeover_height=550,
            non_winning_claims=[
                ClaimStateValue(first_claim_id, activation_height=207, active_in_lbrycrd=True),
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True)
            ]
        )

        await self.daemon.jsonrpc_stream_update(third_claim_id, '0.09')
        await self.generate(1)
        await self.assertNameState(
            height=551, name=name, winning_claim_id=first_claim_id, last_takeover_height=551,
            non_winning_claims=[
                ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True),
                ClaimStateValue(third_claim_id, activation_height=551, active_in_lbrycrd=True)
            ]
        )

    async def test_resolve_signed_claims_with_fees(self):
        channel_name = '@abc'
        channel_id = self.get_claim_id(
            await self.channel_create(channel_name, '0.01')
        )
        self.assertEqual(channel_id, (await self.assertMatchWinningClaim(channel_name)).claim_hash.hex())
        stream_name = 'foo'
        stream_with_no_fee = self.get_claim_id(
            await self.stream_create(stream_name, '0.01', channel_id=channel_id)
        )
        stream_with_fee = self.get_claim_id(
            await self.stream_create('with_a_fee', '0.01', channel_id=channel_id, fee_amount='1', fee_currency='LBC')
        )
        greater_than_or_equal_to_zero = [
            claim['claim_id'] for claim in (
                await self.conductor.spv_node.server.session_manager.search_index.search(
                    channel_id=channel_id, fee_amount=">=0"
                ))[0]
        ]
        self.assertEqual(2, len(greater_than_or_equal_to_zero))
        self.assertSetEqual(set(greater_than_or_equal_to_zero), {stream_with_no_fee, stream_with_fee})
        greater_than_zero = [
            claim['claim_id'] for claim in (
                await self.conductor.spv_node.server.session_manager.search_index.search(
                    channel_id=channel_id, fee_amount=">0"
                ))[0]
        ]
        self.assertEqual(1, len(greater_than_zero))
        self.assertSetEqual(set(greater_than_zero), {stream_with_fee})
        equal_to_zero = [
            claim['claim_id'] for claim in (
                await self.conductor.spv_node.server.session_manager.search_index.search(
                    channel_id=channel_id, fee_amount="<=0"
                ))[0]
        ]
        self.assertEqual(1, len(equal_to_zero))
        self.assertSetEqual(set(equal_to_zero), {stream_with_no_fee})

    async def test_spec_example(self):
        # https://spec.lbry.com/#claim-activation-example
        # this test has adjusted block heights from the example because it uses the regtest chain instead of mainnet
        # on regtest, claims expire much faster, so we can't do the ~1000 block delay in the spec example exactly

        name = 'test'
        await self.generate(494)
        address = (await self.account.receiving.get_addresses(True))[0]
        await self.send_to_address_and_wait(address, 400.0)
        await self.account.ledger.on_address.first
        await self.generate(100)
        self.assertEqual(800, self.conductor.spv_node.server.db.db_height)

        # Block 801: Claim A for 10 LBC is accepted.
        # It is the first claim, so it immediately becomes active and controlling.
        # State: A(10) is controlling
        claim_id_A = (await self.stream_create(name, '10.0',  allow_duplicate_name=True))['outputs'][0]['claim_id']
        await self.assertMatchClaimIsWinning(name, claim_id_A)

        # Block 1121: Claim B for 20 LBC is accepted.
        # Its activation height is 1121 + min(4032, floor((1121-801) / 32)) = 1121 + 10 = 1131.
        # State: A(10) is controlling, B(20) is accepted.
        await self.generate(32 * 10 - 1)
        self.assertEqual(1120, self.conductor.spv_node.server.db.db_height)
        claim_id_B = (await self.stream_create(name, '20.0', allow_duplicate_name=True))['outputs'][0]['claim_id']
        claim_B, _, _, _ = await self.conductor.spv_node.server.db.resolve(f"{name}:{claim_id_B}")
        self.assertEqual(1121, self.conductor.spv_node.server.db.db_height)
        self.assertEqual(1131, claim_B.activation_height)
        await self.assertMatchClaimIsWinning(name, claim_id_A)

        # Block 1122: Support X for 14 LBC for claim A is accepted.
        # Since it is a support for the controlling claim, it activates immediately.
        # State: A(10+14) is controlling, B(20) is accepted.
        await self.support_create(claim_id_A, bid='14.0')
        self.assertEqual(1122, self.conductor.spv_node.server.db.db_height)
        await self.assertMatchClaimIsWinning(name, claim_id_A)

        # Block 1123: Claim C for 50 LBC is accepted.
        # The activation height is 1123 + min(4032, floor((1123-801) / 32)) = 1123 + 10 = 1133.
        # State: A(10+14) is controlling, B(20) is accepted, C(50) is accepted.
        claim_id_C = (await self.stream_create(name, '50.0', allow_duplicate_name=True))['outputs'][0]['claim_id']
        self.assertEqual(1123, self.conductor.spv_node.server.db.db_height)
        claim_C, _, _, _ = await self.conductor.spv_node.server.db.resolve(f"{name}:{claim_id_C}")
        self.assertEqual(1133, claim_C.activation_height)
        await self.assertMatchClaimIsWinning(name, claim_id_A)

        await self.generate(7)
        self.assertEqual(1130, self.conductor.spv_node.server.db.db_height)
        await self.assertMatchClaimIsWinning(name, claim_id_A)
        await self.generate(1)

        # Block 1131: Claim B activates. It has 20 LBC, while claim A has 24 LBC (10 original + 14 from support X). There is no takeover, and claim A remains controlling.
        # State: A(10+14) is controlling, B(20) is active, C(50) is accepted.
        self.assertEqual(1131, self.conductor.spv_node.server.db.db_height)
        await self.assertMatchClaimIsWinning(name, claim_id_A)

        # Block 1132: Claim D for 300 LBC is accepted. The activation height is 1132 + min(4032, floor((1132-801) / 32)) = 1132 + 10 = 1142.
        # State: A(10+14) is controlling, B(20) is active, C(50) is accepted, D(300) is accepted.
        claim_id_D = (await self.stream_create(name, '300.0', allow_duplicate_name=True))['outputs'][0]['claim_id']
        self.assertEqual(1132, self.conductor.spv_node.server.db.db_height)
        claim_D, _, _, _ = await self.conductor.spv_node.server.db.resolve(f"{name}:{claim_id_D}")
        self.assertEqual(False, claim_D.is_controlling)
        self.assertEqual(801, claim_D.last_takeover_height)
        self.assertEqual(1142, claim_D.activation_height)
        await self.assertMatchClaimIsWinning(name, claim_id_A)

        # Block 1133: Claim C activates. It has 50 LBC, while claim A has 24 LBC, so a takeover is initiated. The takeover height for this name is set to 1133, and therefore the activation delay for all the claims becomes min(4032, floor((1133-1133) / 32)) = 0. All the claims become active. The totals for each claim are recalculated, and claim D becomes controlling because it has the highest total.
        # State: A(10+14) is active, B(20) is active, C(50) is active, D(300) is controlling
        await self.generate(1)
        self.assertEqual(1133, self.conductor.spv_node.server.db.db_height)
        claim_D, _, _, _ = await self.conductor.spv_node.server.db.resolve(f"{name}:{claim_id_D}")
        self.assertEqual(True, claim_D.is_controlling)
        self.assertEqual(1133, claim_D.last_takeover_height)
        self.assertEqual(1133, claim_D.activation_height)
        await self.assertMatchClaimIsWinning(name, claim_id_D)

    async def test_early_takeover(self):
        name = 'derp'
        # block 207
        first_claim_id = (await self.stream_create(name, '0.1',  allow_duplicate_name=True))['outputs'][0]['claim_id']
        await self.assertMatchClaimIsWinning(name, first_claim_id)

        await self.generate(96)
        # block 304, activates at 307
        second_claim_id = (await self.stream_create(name, '0.2',  allow_duplicate_name=True))['outputs'][0]['claim_id']
        # block 305, activates at 308 (but gets triggered early by the takeover by the second claim)
        third_claim_id = (await self.stream_create(name, '0.3',  allow_duplicate_name=True))['outputs'][0]['claim_id']
        self.assertNotEqual(first_claim_id, second_claim_id)
        # takeover should not have happened yet
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, third_claim_id)
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, third_claim_id)

    async def test_early_takeover_zero_delay(self):
        name = 'derp'
        # block 207
        first_claim_id = (await self.stream_create(name, '0.1',  allow_duplicate_name=True))['outputs'][0]['claim_id']
        await self.assertMatchClaimIsWinning(name, first_claim_id)

        await self.generate(96)
        # block 304, activates at 307
        second_claim_id = (await self.stream_create(name, '0.2',  allow_duplicate_name=True))['outputs'][0]['claim_id']
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        # on block 307 make a third claim with a yet higher amount, it takes over with no delay because the
        # second claim activates and begins the takeover on this block
        third_claim_id = (await self.stream_create(name, '0.3',  allow_duplicate_name=True))['outputs'][0]['claim_id']
        await self.assertMatchClaimIsWinning(name, third_claim_id)
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, third_claim_id)

    async def test_early_takeover_from_support_zero_delay(self):
        name = 'derp'
        # block 207
        first_claim_id = (await self.stream_create(name, '0.1',  allow_duplicate_name=True))['outputs'][0]['claim_id']
        await self.assertMatchClaimIsWinning(name, first_claim_id)

        await self.generate(96)
        # block 304, activates at 307
        second_claim_id = (await self.stream_create(name, '0.2',  allow_duplicate_name=True))['outputs'][0]['claim_id']
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        third_claim_id = (await self.stream_create(name, '0.19',  allow_duplicate_name=True))['outputs'][0]['claim_id']
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        tx = await self.daemon.jsonrpc_support_create(third_claim_id, '0.1')
        await self.ledger.wait(tx)
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, third_claim_id)
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, third_claim_id)

    async def test_early_takeover_from_support_and_claim_zero_delay(self):
        name = 'derp'
        # block 207
        first_claim_id = (await self.stream_create(name, '0.1',  allow_duplicate_name=True))['outputs'][0]['claim_id']
        await self.assertMatchClaimIsWinning(name, first_claim_id)

        await self.generate(96)
        # block 304, activates at 307
        second_claim_id = (await self.stream_create(name, '0.2',  allow_duplicate_name=True))['outputs'][0]['claim_id']
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(1)

        file_path = self.create_upload_file(data=b'hi!')
        tx = await self.daemon.jsonrpc_stream_create(name, '0.19', file_path=file_path, allow_duplicate_name=True)
        await self.ledger.wait(tx)
        third_claim_id = tx.outputs[0].claim_id

        wallet = self.daemon.wallet_manager.get_wallet_or_default(None)
        funding_accounts = wallet.get_accounts_or_all(None)
        amount = self.daemon.get_dewies_or_error("amount", '0.1')
        account = wallet.get_account_or_default(None)
        claim_address = await account.receiving.get_or_create_usable_address()
        tx = await Transaction.support(
            'derp', third_claim_id, amount, claim_address, funding_accounts, funding_accounts[0], None
        )
        await tx.sign(funding_accounts)
        await self.daemon.broadcast_or_release(tx, True)
        await self.ledger.wait(tx)
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, third_claim_id)
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, third_claim_id)

    async def test_early_takeover_abandoned_controlling_support(self):
        name = 'derp'
        # block 207
        first_claim_id = (await self.stream_create(name, '0.1', allow_duplicate_name=True))['outputs'][0][
            'claim_id']
        tx = await self.daemon.jsonrpc_support_create(first_claim_id, '0.2')
        await self.ledger.wait(tx)
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(96)
        # block 304, activates at 307
        second_claim_id = (await self.stream_create(name, '0.2', allow_duplicate_name=True))['outputs'][0][
            'claim_id']
        # block 305, activates at 308 (but gets triggered early by the takeover by the second claim)
        third_claim_id = (await self.stream_create(name, '0.3', allow_duplicate_name=True))['outputs'][0][
            'claim_id']
        self.assertNotEqual(first_claim_id, second_claim_id)
        # takeover should not have happened yet
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.daemon.jsonrpc_txo_spend(type='support', txid=tx.id)
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, third_claim_id)
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, third_claim_id)

    async def test_block_takeover_with_delay_1_support(self):
        name = 'derp'
        # initially claim the name
        first_claim_id = (await self.stream_create(name, '0.1'))['outputs'][0]['claim_id']
        self.assertEqual(first_claim_id, (await self.assertMatchWinningClaim(name)).claim_hash.hex())
        await self.generate(320)
        # a claim of higher amount made now will have a takeover delay of 10
        second_claim_id = (await self.stream_create(name, '0.2',  allow_duplicate_name=True))['outputs'][0]['claim_id']
        # sanity check
        self.assertNotEqual(first_claim_id, second_claim_id)
        # takeover should not have happened yet
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        for _ in range(8):
            await self.generate(1)
            await self.assertMatchClaimIsWinning(name, first_claim_id)
        # prevent the takeover by adding a support one block before the takeover happens
        await self.support_create(first_claim_id, bid='1.0')
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        # one more block until activation
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, first_claim_id)

    async def test_block_takeover_with_delay_0_support(self):
        name = 'derp'
        # initially claim the name
        first_claim_id = (await self.stream_create(name, '0.1'))['outputs'][0]['claim_id']
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(320)
        # a claim of higher amount made now will have a takeover delay of 10
        second_claim_id = (await self.stream_create(name, '0.2',  allow_duplicate_name=True))['outputs'][0]['claim_id']
        # sanity check
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        # takeover should not have happened yet
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(9)
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        # prevent the takeover by adding a support on the same block the takeover would happen
        await self.support_create(first_claim_id, bid='1.0')
        await self.assertMatchClaimIsWinning(name, first_claim_id)

    async def _test_almost_prevent_takeover(self, name: str, blocks: int = 9):
        # initially claim the name
        first_claim_id = (await self.stream_create(name, '0.1'))['outputs'][0]['claim_id']
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(320)
        # a claim of higher amount made now will have a takeover delay of 10
        second_claim_id = (await self.stream_create(name, '0.2', allow_duplicate_name=True))['outputs'][0]['claim_id']
        # sanity check
        self.assertNotEqual(first_claim_id, second_claim_id)
        # takeover should not have happened yet
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(blocks)
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        # prevent the takeover by adding a support on the same block the takeover would happen
        tx = await self.daemon.jsonrpc_support_create(first_claim_id, '1.0')
        await self.ledger.wait(tx)
        return first_claim_id, second_claim_id, tx

    async def test_almost_prevent_takeover_remove_support_same_block_supported(self):
        name = 'derp'
        first_claim_id, second_claim_id, tx = await self._test_almost_prevent_takeover(name, 9)
        await self.daemon.jsonrpc_txo_spend(type='support', txid=tx.id)
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, second_claim_id)

    async def test_almost_prevent_takeover_remove_support_one_block_after_supported(self):
        name = 'derp'
        first_claim_id, second_claim_id, tx = await self._test_almost_prevent_takeover(name, 8)
        await self.generate(1)
        await self.daemon.jsonrpc_txo_spend(type='support', txid=tx.id)
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, second_claim_id)

    async def test_abandon_before_takeover(self):
        name = 'derp'
        # initially claim the name
        first_claim_id = (await self.stream_create(name, '0.1'))['outputs'][0]['claim_id']
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(320)
        # a claim of higher amount made now will have a takeover delay of 10
        second_claim_id = (await self.stream_create(name, '0.2',  allow_duplicate_name=True))['outputs'][0]['claim_id']
        # sanity check
        self.assertNotEqual(first_claim_id, second_claim_id)
        # takeover should not have happened yet
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(8)
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        # abandon the winning claim
        await self.daemon.jsonrpc_txo_spend(type='stream', claim_id=first_claim_id)
        await self.generate(1)
        # the takeover and activation should happen a block earlier than they would have absent the abandon
        await self.assertMatchClaimIsWinning(name, second_claim_id)
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, second_claim_id)

    async def test_abandon_before_takeover_no_delay_update(self):  # TODO: fix race condition line 506
        name = 'derp'
        # initially claim the name
        first_claim_id = (await self.stream_create(name, '0.1'))['outputs'][0]['claim_id']
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(320)
        # block 527
        # a claim of higher amount made now will have a takeover delay of 10
        second_claim_id = (await self.stream_create(name, '0.2',  allow_duplicate_name=True))['outputs'][0]['claim_id']
        # block 528
        # sanity check
        self.assertNotEqual(first_claim_id, second_claim_id)
        # takeover should not have happened yet
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.assertMatchClaimsForName(name)
        await self.generate(8)
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.assertMatchClaimsForName(name)
        # abandon the winning claim
        await self.daemon.jsonrpc_txo_spend(type='stream', claim_id=first_claim_id)
        await self.daemon.jsonrpc_stream_update(second_claim_id, '0.1')
        await self.generate(1)

        # the takeover and activation should happen a block earlier than they would have absent the abandon
        await self.assertMatchClaimIsWinning(name, second_claim_id)
        await self.assertMatchClaimsForName(name)
        await self.generate(1)
        # await self.ledger.on_header.where(lambda e: e.height == 537)
        await self.assertMatchClaimIsWinning(name, second_claim_id)
        await self.assertMatchClaimsForName(name)

    async def test_abandon_controlling_support_before_pending_takeover(self):
        name = 'derp'
        # initially claim the name
        first_claim_id = (await self.stream_create(name, '0.1'))['outputs'][0]['claim_id']
        controlling_support_tx = await self.daemon.jsonrpc_support_create(first_claim_id, '0.9')
        await self.ledger.wait(controlling_support_tx)
        self.assertEqual(first_claim_id, (await self.assertMatchWinningClaim(name)).claim_hash.hex())
        await self.generate(321)

        second_claim_id = (await self.stream_create(name, '0.9',  allow_duplicate_name=True))['outputs'][0]['claim_id']

        self.assertNotEqual(first_claim_id, second_claim_id)
        # takeover should not have happened yet
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(8)
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        # abandon the support that causes the winning claim to have the highest staked
        tx = await self.daemon.jsonrpc_txo_spend(type='support', txid=controlling_support_tx.id, blocking=True)
        await self.generate(1)
        await self.assertNameState(538, name, first_claim_id, last_takeover_height=207, non_winning_claims=[
            ClaimStateValue(second_claim_id, activation_height=539, active_in_lbrycrd=False)
        ])
        await self.generate(1)
        await self.assertNameState(539, name, second_claim_id, last_takeover_height=539, non_winning_claims=[
            ClaimStateValue(first_claim_id, activation_height=207, active_in_lbrycrd=True)
        ])

    async def test_remove_controlling_support(self):
        name = 'derp'
        # initially claim the name
        first_claim_id = (await self.stream_create(name, '0.2'))['outputs'][0]['claim_id']
        first_support_tx = await self.daemon.jsonrpc_support_create(first_claim_id, '0.9')
        await self.ledger.wait(first_support_tx)
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(320)  # give the first claim long enough for a 10 block takeover delay
        await self.assertNameState(527, name, first_claim_id, last_takeover_height=207, non_winning_claims=[])

        # make a second claim which will take over the name
        second_claim_id = (await self.stream_create(name, '0.1',  allow_duplicate_name=True))['outputs'][0]['claim_id']
        await self.assertNameState(528, name, first_claim_id, last_takeover_height=207, non_winning_claims=[
            ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=False)
        ])

        second_claim_support_tx = await self.daemon.jsonrpc_support_create(second_claim_id, '1.5')
        await self.ledger.wait(second_claim_support_tx)
        await self.generate(1)  # neither the second claim or its support have activated yet
        await self.assertNameState(529, name, first_claim_id, last_takeover_height=207, non_winning_claims=[
            ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=False)
        ])
        await self.generate(9)  # claim activates, but is not yet winning
        await self.assertNameState(538, name, first_claim_id, last_takeover_height=207, non_winning_claims=[
            ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True)
        ])
        await self.generate(1)  # support activates, takeover happens
        await self.assertNameState(539, name, second_claim_id, last_takeover_height=539, non_winning_claims=[
            ClaimStateValue(first_claim_id, activation_height=207, active_in_lbrycrd=True)
        ])

        await self.daemon.jsonrpc_txo_spend(type='support', claim_id=second_claim_id, blocking=True)
        await self.generate(1)  # support activates, takeover happens
        await self.assertNameState(540, name, first_claim_id, last_takeover_height=540, non_winning_claims=[
            ClaimStateValue(second_claim_id, activation_height=538, active_in_lbrycrd=True)
        ])

    async def test_claim_expiration(self):
        name = 'derp'
        # starts at height 206
        vanishing_claim = (await self.stream_create('vanish', '0.1'))['outputs'][0]['claim_id']

        await self.generate(493)
        # in block 701 and 702
        first_claim_id = (await self.stream_create(name, '0.3'))['outputs'][0]['claim_id']
        await self.assertMatchClaimIsWinning('vanish', vanishing_claim)
        await self.generate(100)  # block 801, expiration fork happened
        await self.assertNoClaimForName('vanish')
        # second claim is in block 802
        second_claim_id = (await self.stream_create(name, '0.2', allow_duplicate_name=True))['outputs'][0]['claim_id']
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(498)
        await self.assertMatchClaimIsWinning(name, first_claim_id)
        await self.generate(1)
        await self.assertMatchClaimIsWinning(name, second_claim_id)
        await self.generate(100)
        await self.assertMatchClaimIsWinning(name, second_claim_id)
        await self.generate(1)
        await self.assertNoClaimForName(name)

    async def _test_add_non_winning_already_claimed(self):
        name = 'derp'
        # initially claim the name
        first_claim_id = (await self.stream_create(name, '0.1'))['outputs'][0]['claim_id']
        self.assertEqual(first_claim_id, (await self.assertMatchWinningClaim(name)).claim_hash.hex())
        await self.generate(32)

        second_claim_id = (await self.stream_create(name, '0.01', allow_duplicate_name=True))['outputs'][0]['claim_id']
        await self.assertNoClaim(name, second_claim_id)
        self.assertEqual(
            len((await self.conductor.spv_node.server.session_manager.search_index.search(claim_name=name))[0]), 1
        )
        await self.generate(1)
        await self.assertMatchClaim(name, second_claim_id)
        self.assertEqual(
            len((await self.conductor.spv_node.server.session_manager.search_index.search(claim_name=name))[0]), 2
        )

    async def test_abandon_controlling_same_block_as_new_claim(self):
        name = 'derp'

        first_claim_id = (await self.stream_create(name, '0.1'))['outputs'][0]['claim_id']
        await self.generate(64)
        await self.assertNameState(271, name, first_claim_id, last_takeover_height=207, non_winning_claims=[])

        await self.daemon.jsonrpc_txo_spend(type='stream', claim_id=first_claim_id)
        second_claim_id = (await self.stream_create(name, '0.1', allow_duplicate_name=True))['outputs'][0]['claim_id']
        await self.assertNameState(272, name, second_claim_id, last_takeover_height=272, non_winning_claims=[])

    async def test_trending(self):
        async def get_trending_score(claim_id):
            return (await self.conductor.spv_node.server.session_manager.search_index.search(
                claim_id=claim_id
            ))[0][0]['trending_score']

        claim_id1 = (await self.stream_create('derp', '1.0'))['outputs'][0]['claim_id']
        COIN = int(1E8)

        self.assertEqual(self.conductor.spv_node.writer.height, 207)
        self.conductor.spv_node.writer.db.prefix_db.trending_notification.stage_put(
            (208, bytes.fromhex(claim_id1)), (0, 10 * COIN)
        )
        await self.generate(1)
        self.assertEqual(self.conductor.spv_node.writer.height, 208)

        self.assertEqual(1.7090807854206793, await get_trending_score(claim_id1))
        self.conductor.spv_node.writer.db.prefix_db.trending_notification.stage_put(
            (209, bytes.fromhex(claim_id1)), (10 * COIN, 100 * COIN)
        )
        await self.generate(1)
        self.assertEqual(self.conductor.spv_node.writer.height, 209)
        self.assertEqual(2.2437974397778886, await get_trending_score(claim_id1))
        self.conductor.spv_node.writer.db.prefix_db.trending_notification.stage_put(
            (309, bytes.fromhex(claim_id1)), (100 * COIN, 1000000 * COIN)
        )
        await self.generate(100)
        self.assertEqual(self.conductor.spv_node.writer.height, 309)
        self.assertEqual(5.157053472135866, await get_trending_score(claim_id1))

        self.conductor.spv_node.writer.db.prefix_db.trending_notification.stage_put(
            (409, bytes.fromhex(claim_id1)), (1000000 * COIN, 1 * COIN)
        )

        await self.generate(99)
        self.assertEqual(self.conductor.spv_node.writer.height, 408)
        self.assertEqual(5.157053472135866, await get_trending_score(claim_id1))

        await self.generate(1)
        self.assertEqual(self.conductor.spv_node.writer.height, 409)

        self.assertEqual(-3.4256156592205627, await get_trending_score(claim_id1))
        search_results = (await self.conductor.spv_node.server.session_manager.search_index.search(claim_name="derp"))[0]
        self.assertEqual(1, len(search_results))
        self.assertListEqual([claim_id1], [c['claim_id'] for c in search_results])


class ResolveAfterReorg(BaseResolveTestCase):
    async def reorg(self, start):
        blocks = self.ledger.headers.height - start
        self.blockchain.block_expected = start - 1


        prepare = self.ledger.on_header.where(self.blockchain.is_expected_block)
        self.conductor.spv_node.server.synchronized.clear()

        # go back to start
        await self.blockchain.invalidate_block((await self.ledger.headers.hash(start)).decode())
        # go to previous + 1
        await self.blockchain.generate(blocks + 2)

        await prepare  # no guarantee that it didn't happen already, so start waiting from before calling generate
        await self.conductor.spv_node.server.synchronized.wait()
        # await asyncio.wait_for(self.on_header(self.blockchain.block_expected), 30.0)

    async def assertBlockHash(self, height):
        reader_db = self.conductor.spv_node.server.db
        block_hash = await self.blockchain.get_block_hash(height)

        self.assertEqual(block_hash, (await self.ledger.headers.hash(height)).decode())
        self.assertEqual(block_hash, (await reader_db.fs_block_hashes(height, 1))[0][::-1].hex())
        txids = [
            tx_hash[::-1].hex() for tx_hash in reader_db.get_block_txs(height)
        ]
        txs = await reader_db.get_transactions_and_merkles(txids)
        block_txs = (await self.conductor.spv_node.server.daemon.deserialised_block(block_hash))['tx']
        self.assertSetEqual(set(block_txs), set(txs.keys()), msg='leveldb/lbrycrd is missing transactions')
        self.assertListEqual(block_txs, list(txs.keys()), msg='leveldb/lbrycrd transactions are of order')

    async def test_reorg(self):
        self.assertEqual(self.ledger.headers.height, 206)

        channel_name = '@abc'
        channel_id = self.get_claim_id(
            await self.channel_create(channel_name, '0.01')
        )

        await self.assertNameState(
            height=207, name='@abc', winning_claim_id=channel_id, last_takeover_height=207,
            non_winning_claims=[]
        )

        await self.reorg(206)

        await self.assertNameState(
            height=208, name='@abc', winning_claim_id=channel_id, last_takeover_height=207,
            non_winning_claims=[]
        )

        # await self.assertNoClaimForName(channel_name)
        # self.assertNotIn('error', await self.resolve(channel_name))

        stream_name = 'foo'
        stream_id = self.get_claim_id(
            await self.stream_create(stream_name, '0.01', channel_id=channel_id)
        )

        await self.assertNameState(
            height=209, name=stream_name, winning_claim_id=stream_id, last_takeover_height=209,
            non_winning_claims=[]
        )
        await self.reorg(206)
        await self.assertNameState(
            height=210, name=stream_name, winning_claim_id=stream_id, last_takeover_height=209,
            non_winning_claims=[]
        )

        await self.support_create(stream_id, '0.01')

        await self.assertNameState(
            height=211, name=stream_name, winning_claim_id=stream_id, last_takeover_height=209,
            non_winning_claims=[]
        )
        await self.reorg(206)
        # self.assertNotIn('error', await self.resolve(stream_name))
        await self.assertNameState(
            height=212, name=stream_name, winning_claim_id=stream_id, last_takeover_height=209,
            non_winning_claims=[]
        )

        await self.stream_abandon(stream_id)
        self.assertNotIn('error', await self.resolve(channel_name))
        self.assertIn('error', await self.resolve(stream_name))
        self.assertEqual(channel_id, (await self.assertMatchWinningClaim(channel_name)).claim_hash.hex())
        await self.assertNoClaimForName(stream_name)
        # TODO: check @abc/foo too

        await self.reorg(206)
        self.assertNotIn('error', await self.resolve(channel_name))
        self.assertIn('error', await self.resolve(stream_name))
        self.assertEqual(channel_id, (await self.assertMatchWinningClaim(channel_name)).claim_hash.hex())
        await self.assertNoClaimForName(stream_name)

        await self.channel_abandon(channel_id)
        self.assertIn('error', await self.resolve(channel_name))
        self.assertIn('error', await self.resolve(stream_name))
        await self.reorg(206)
        self.assertIn('error', await self.resolve(channel_name))
        self.assertIn('error', await self.resolve(stream_name))

    async def test_reorg_change_claim_height(self):
        # sanity check
        result = await self.resolve('hovercraft')  # TODO: do these for claim_search and resolve both
        self.assertIn('error', result)

        still_valid = await self.daemon.jsonrpc_stream_create(
            'still-valid', '1.0', file_path=self.create_upload_file(data=b'hi!')
        )
        await self.ledger.wait(still_valid)
        await self.generate(1)
        # create a claim and verify it's returned by claim_search
        self.assertEqual(self.ledger.headers.height, 207)
        await self.assertBlockHash(207)

        broadcast_tx = await self.daemon.jsonrpc_stream_create(
            'hovercraft', '1.0', file_path=self.create_upload_file(data=b'hi!')
        )
        await self.ledger.wait(broadcast_tx)
        await self.support_create(still_valid.outputs[0].claim_id, '0.01')

        await self.ledger.wait(broadcast_tx, self.blockchain.block_expected)
        self.assertEqual(self.ledger.headers.height, 208)
        await self.assertBlockHash(208)

        claim = await self.resolve('hovercraft')
        self.assertEqual(claim['txid'], broadcast_tx.id)
        self.assertEqual(claim['height'], 208)

        # check that our tx is in block 208 as returned by lbrycrdd
        invalidated_block_hash = (await self.ledger.headers.hash(208)).decode()
        block_207 = await self.blockchain.get_block(invalidated_block_hash)
        self.assertIn(claim['txid'], block_207['tx'])
        self.assertEqual(208, claim['height'])

        # reorg the last block dropping our claim tx
        await self.blockchain.invalidate_block(invalidated_block_hash)
        await self.conductor.clear_mempool()
        await self.blockchain.generate(2)

        # wait for the client to catch up and verify the reorg
        await asyncio.wait_for(self.on_header(209), 3.0)
        await self.assertBlockHash(207)
        await self.assertBlockHash(208)
        await self.assertBlockHash(209)

        # verify the claim was dropped from block 208 as returned by lbrycrdd
        reorg_block_hash = await self.blockchain.get_block_hash(208)
        self.assertNotEqual(invalidated_block_hash, reorg_block_hash)
        block_207 = await self.blockchain.get_block(reorg_block_hash)
        self.assertNotIn(claim['txid'], block_207['tx'])

        client_reorg_block_hash = (await self.ledger.headers.hash(208)).decode()
        self.assertEqual(client_reorg_block_hash, reorg_block_hash)

        # verify the dropped claim is no longer returned by claim search
        self.assertDictEqual(
            {'error': {'name': 'NOT_FOUND', 'text': 'Could not find claim at "hovercraft".'}},
            await self.resolve('hovercraft')
        )

        # verify the claim published a block earlier wasn't also reverted
        self.assertEqual(207, (await self.resolve('still-valid'))['height'])

        # broadcast the claim in a different block
        new_txid = await self.blockchain.sendrawtransaction(hexlify(broadcast_tx.raw).decode())
        self.assertEqual(broadcast_tx.id, new_txid)
        await self.blockchain.generate(1)

        # wait for the client to catch up
        await asyncio.wait_for(self.on_header(210), 3.0)

        # verify the claim is in the new block and that it is returned by claim_search
        republished = await self.resolve('hovercraft')
        self.assertEqual(210, republished['height'])
        self.assertEqual(claim['claim_id'], republished['claim_id'])

        # this should still be unchanged
        self.assertEqual(207, (await self.resolve('still-valid'))['height'])

    async def test_reorg_drop_claim(self):
        # sanity check
        result = await self.resolve('hovercraft')  # TODO: do these for claim_search and resolve both
        self.assertIn('error', result)

        still_valid = await self.daemon.jsonrpc_stream_create(
            'still-valid', '1.0', file_path=self.create_upload_file(data=b'hi!')
        )
        await self.ledger.wait(still_valid)
        await self.generate(1)

        # create a claim and verify it's returned by claim_search
        self.assertEqual(self.ledger.headers.height, 207)
        await self.assertBlockHash(207)

        broadcast_tx = await self.daemon.jsonrpc_stream_create(
            'hovercraft', '1.0', file_path=self.create_upload_file(data=b'hi!')
        )
        await self.ledger.wait(broadcast_tx)
        await self.generate(1)
        await self.ledger.wait(broadcast_tx, self.blockchain.block_expected)
        self.assertEqual(self.ledger.headers.height, 208)
        await self.assertBlockHash(208)

        claim = await self.resolve('hovercraft')
        self.assertEqual(claim['txid'], broadcast_tx.id)
        self.assertEqual(claim['height'], 208)

        # check that our tx is in block 208 as returned by lbrycrdd
        invalidated_block_hash = (await self.ledger.headers.hash(208)).decode()
        block_207 = await self.blockchain.get_block(invalidated_block_hash)
        self.assertIn(claim['txid'], block_207['tx'])
        self.assertEqual(208, claim['height'])

        # reorg the last block dropping our claim tx
        await self.blockchain.invalidate_block(invalidated_block_hash)
        await self.conductor.clear_mempool()
        await self.blockchain.generate(2)

        # wait for the client to catch up and verify the reorg
        await asyncio.wait_for(self.on_header(209), 30.0)
        await self.assertBlockHash(207)
        await self.assertBlockHash(208)
        await self.assertBlockHash(209)

        # verify the claim was dropped from block 208 as returned by lbrycrdd
        reorg_block_hash = await self.blockchain.get_block_hash(208)
        self.assertNotEqual(invalidated_block_hash, reorg_block_hash)
        block_207 = await self.blockchain.get_block(reorg_block_hash)
        self.assertNotIn(claim['txid'], block_207['tx'])

        client_reorg_block_hash = (await self.ledger.headers.hash(208)).decode()
        self.assertEqual(client_reorg_block_hash, reorg_block_hash)

        # verify the dropped claim is no longer returned by claim search
        self.assertDictEqual(
            {'error': {'name': 'NOT_FOUND', 'text': 'Could not find claim at "hovercraft".'}},
            await self.resolve('hovercraft')
        )

        # verify the claim published a block earlier wasn't also reverted
        self.assertEqual(207, (await self.resolve('still-valid'))['height'])

        # broadcast the claim in a different block
        new_txid = await self.blockchain.sendrawtransaction(hexlify(broadcast_tx.raw).decode())
        self.assertEqual(broadcast_tx.id, new_txid)
        await self.blockchain.generate(1)

        # wait for the client to catch up
        await asyncio.wait_for(self.on_header(210), 1.0)

        # verify the claim is in the new block and that it is returned by claim_search
        republished = await self.resolve('hovercraft')
        self.assertEqual(210, republished['height'])
        self.assertEqual(claim['claim_id'], republished['claim_id'])

        # this should still be unchanged
        self.assertEqual(207, (await self.resolve('still-valid'))['height'])


def generate_signed_legacy(address: bytes, output: Output):
    decoded_address = Base58.decode(address)
    claim = OldClaimMessage()
    claim.ParseFromString(unhexlify(
        '080110011aee04080112a604080410011a2b4865726520617265203520526561736f6e73204920e29da4e'
        'fb88f204e657874636c6f7564207c20544c4722920346696e64206f7574206d6f72652061626f7574204e'
        '657874636c6f75643a2068747470733a2f2f6e657874636c6f75642e636f6d2f0a0a596f752063616e206'
        '6696e64206d65206f6e20746865736520736f6369616c733a0a202a20466f72756d733a2068747470733a'
        '2f2f666f72756d2e6865617679656c656d656e742e696f2f0a202a20506f64636173743a2068747470733'
        'a2f2f6f6666746f706963616c2e6e65740a202a2050617472656f6e3a2068747470733a2f2f7061747265'
        '6f6e2e636f6d2f7468656c696e757867616d65720a202a204d657263683a2068747470733a2f2f7465657'
        '37072696e672e636f6d2f73746f7265732f6f6666696369616c2d6c696e75782d67616d65720a202a2054'
        '77697463683a2068747470733a2f2f7477697463682e74762f786f6e64616b0a202a20547769747465723'
        'a2068747470733a2f2f747769747465722e636f6d2f7468656c696e757867616d65720a0a2e2e2e0a6874'
        '7470733a2f2f7777772e796f75747562652e636f6d2f77617463683f763d4672546442434f535f66632a0'
        'f546865204c696e75782047616d6572321c436f7079726967687465642028636f6e746163742061757468'
        '6f722938004a2968747470733a2f2f6265726b2e6e696e6a612f7468756d626e61696c732f46725464424'
        '34f535f666352005a001a41080110011a30040e8ac6e89c061f982528c23ad33829fd7146435bf7a4cc22'
        'f0bff70c4fe0b91fd36da9a375e3e1c171db825bf5d1f32209766964656f2f6d70342a5c080110031a406'
        '2b2dd4c45e364030fbfad1a6fefff695ebf20ea33a5381b947753e2a0ca359989a5cc7d15e5392a0d354c'
        '0b68498382b2701b22c03beb8dcb91089031b871e72214feb61536c007cdf4faeeaab4876cb397feaf6b51'
    ))
    claim.ClearField("publisherSignature")
    digest = sha256(b''.join([
        decoded_address,
        claim.SerializeToString(),
        output.claim_hash[::-1]
    ]))
    signature = output.private_key.sign_compact(digest)
    claim.publisherSignature.version = 1
    claim.publisherSignature.signatureType = 1
    claim.publisherSignature.signature = signature
    claim.publisherSignature.certificateId = output.claim_hash[::-1]
    return claim
