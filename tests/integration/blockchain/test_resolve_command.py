import asyncio
import json
import hashlib
from binascii import hexlify, unhexlify
from lbry.testcase import CommandTestCase
from lbry.wallet.transaction import Transaction, Output
from lbry.schema.compat import OldClaimMessage
from lbry.crypto.hash import sha256
from lbry.crypto.base58 import Base58


class BaseResolveTestCase(CommandTestCase):

    async def assertResolvesToClaimId(self, name, claim_id):
        other = await self.resolve(name)
        if claim_id is None:
            self.assertIn('error', other)
            self.assertEqual(other['error']['name'], 'NOT_FOUND')
        else:
            self.assertEqual(claim_id, other['claim_id'])


class ResolveCommand(BaseResolveTestCase):

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

        # resolve handles invalid data
        await self.blockchain_claim_name("gibberish", hexlify(b"{'invalid':'json'}").decode(), "0.1")
        await self.generate(1)
        response = await self.out(self.daemon.jsonrpc_resolve("lbry://gibberish"))
        self.assertSetEqual({'lbry://gibberish'}, set(response))
        claim = response['lbry://gibberish']
        self.assertEqual(claim['name'], 'gibberish')
        self.assertNotIn('value', claim)

        # resolve retries
        await self.conductor.spv_node.stop()
        resolve_task = asyncio.create_task(self.resolve('foo'))
        await self.conductor.spv_node.start(self.conductor.blockchain_node)
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

    async def test_advanced_resolve(self):
        claim_id1 = self.get_claim_id(
            await self.stream_create('foo', '0.7', allow_duplicate_name=True))
        claim_id2 = self.get_claim_id(
            await self.stream_create('foo', '0.8', allow_duplicate_name=True))
        claim_id3 = self.get_claim_id(
            await self.stream_create('foo', '0.9', allow_duplicate_name=True))
        # plain winning claim
        await self.assertResolvesToClaimId('foo', claim_id3)
        # amount order resolution
        await self.assertResolvesToClaimId('foo$1', claim_id3)
        await self.assertResolvesToClaimId('foo$2', claim_id2)
        await self.assertResolvesToClaimId('foo$3', claim_id1)
        await self.assertResolvesToClaimId('foo$4', None)

    async def test_partial_claim_id_resolve(self):
        # add some noise
        await self.channel_create('@abc', '0.1', allow_duplicate_name=True)
        await self.channel_create('@abc', '0.2', allow_duplicate_name=True)
        await self.channel_create('@abc', '1.0', allow_duplicate_name=True)

        channel_id = self.get_claim_id(await self.channel_create('@abc', '1.1', allow_duplicate_name=True))
        await self.assertResolvesToClaimId(f'@abc', channel_id)
        await self.assertResolvesToClaimId(f'@abc#{channel_id[:10]}', channel_id)
        await self.assertResolvesToClaimId(f'@abc#{channel_id}', channel_id)

        channel = await self.claim_get(channel_id)
        await self.assertResolvesToClaimId(channel['short_url'], channel_id)
        await self.assertResolvesToClaimId(channel['canonical_url'], channel_id)
        await self.assertResolvesToClaimId(channel['permanent_url'], channel_id)

        # add some noise
        await self.stream_create('foo', '0.1', allow_duplicate_name=True, channel_id=channel['claim_id'])
        await self.stream_create('foo', '0.2', allow_duplicate_name=True, channel_id=channel['claim_id'])
        await self.stream_create('foo', '0.3', allow_duplicate_name=True, channel_id=channel['claim_id'])

        claim_id1 = self.get_claim_id(
            await self.stream_create('foo', '0.7', allow_duplicate_name=True, channel_id=channel['claim_id']))
        claim1 = await self.claim_get(claim_id=claim_id1)

        await self.assertResolvesToClaimId('foo', claim_id1)
        await self.assertResolvesToClaimId('@abc/foo', claim_id1)
        await self.assertResolvesToClaimId(claim1['short_url'], claim_id1)
        await self.assertResolvesToClaimId(claim1['canonical_url'], claim_id1)
        await self.assertResolvesToClaimId(claim1['permanent_url'], claim_id1)

        claim_id2 = self.get_claim_id(
            await self.stream_create('foo', '0.8', allow_duplicate_name=True, channel_id=channel['claim_id']))
        claim2 = await self.claim_get(claim_id=claim_id2)
        await self.assertResolvesToClaimId('foo', claim_id2)
        await self.assertResolvesToClaimId('@abc/foo', claim_id2)
        await self.assertResolvesToClaimId(claim2['short_url'], claim_id2)
        await self.assertResolvesToClaimId(claim2['canonical_url'], claim_id2)
        await self.assertResolvesToClaimId(claim2['permanent_url'], claim_id2)

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

        _ = await self.stream_create(one, '0.1')
        c = await self.stream_create(two, '0.2')

        winner_id = self.get_claim_id(c)

        r1 = await self.resolve(f'lbry://{one}')
        r2 = await self.resolve(f'lbry://{two}')

        self.assertEqual(winner_id, r1['claim_id'])
        self.assertEqual(winner_id, r2['claim_id'])

    async def test_resolve_old_claim(self):
        channel = await self.daemon.jsonrpc_channel_create('@olds', '1.0')
        await self.confirm_tx(channel.id)
        address = channel.outputs[0].get_address(self.account.ledger)
        claim = generate_signed_legacy(address, channel.outputs[0])
        tx = await Transaction.claim_create('example', claim.SerializeToString(), 1, address, [self.account], self.account)
        await tx.sign([self.account])
        await self.broadcast(tx)
        await self.confirm_tx(tx.id)

        response = await self.resolve('@olds/example')
        self.assertTrue(response['is_channel_signature_valid'])

        claim.publisherSignature.signature = bytes(reversed(claim.publisherSignature.signature))
        tx = await Transaction.claim_create(
            'bad_example', claim.SerializeToString(), 1, address, [self.account], self.account
        )
        await tx.sign([self.account])
        await self.broadcast(tx)
        await self.confirm_tx(tx.id)

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


class ResolveAfterReorg(BaseResolveTestCase):

    async def reorg(self, start):
        blocks = self.ledger.headers.height - start
        self.blockchain.block_expected = start - 1
        # go back to start
        await self.blockchain.invalidate_block((await self.ledger.headers.hash(start)).decode())
        # go to previous + 1
        await self.generate(blocks + 2)

    async def test_reorg(self):
        self.assertEqual(self.ledger.headers.height, 206)

        channel_name = '@abc'
        channel_id = self.get_claim_id(
            await self.channel_create(channel_name, '0.01')
        )
        self.assertNotIn('error', await self.resolve(channel_name))
        await self.reorg(206)
        self.assertNotIn('error', await self.resolve(channel_name))

        stream_name = 'foo'
        stream_id = self.get_claim_id(
            await self.stream_create(stream_name, '0.01', channel_id=channel_id)
        )
        self.assertNotIn('error', await self.resolve(stream_name))
        await self.reorg(206)
        self.assertNotIn('error', await self.resolve(stream_name))

        await self.support_create(stream_id, '0.01')
        self.assertNotIn('error', await self.resolve(stream_name))
        await self.reorg(206)
        self.assertNotIn('error', await self.resolve(stream_name))

        await self.stream_abandon(stream_id)
        self.assertNotIn('error', await self.resolve(channel_name))
        self.assertIn('error', await self.resolve(stream_name))
        await self.reorg(206)
        self.assertNotIn('error', await self.resolve(channel_name))
        self.assertIn('error', await self.resolve(stream_name))

        await self.channel_abandon(channel_id)
        self.assertIn('error', await self.resolve(channel_name))
        self.assertIn('error', await self.resolve(stream_name))
        await self.reorg(206)
        self.assertIn('error', await self.resolve(channel_name))
        self.assertIn('error', await self.resolve(stream_name))


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
    signature = output.private_key.sign_digest_deterministic(digest, hashfunc=hashlib.sha256)
    claim.publisherSignature.version = 1
    claim.publisherSignature.signatureType = 1
    claim.publisherSignature.signature = signature
    claim.publisherSignature.certificateId = output.claim_hash[::-1]
    return claim
