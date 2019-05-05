import json
import tempfile
from binascii import hexlify
from lbrynet.testcase import CommandTestCase


class ResolveCommand(CommandTestCase):

    async def test_resolve(self):
        tx = await self.channel_create('@abc', '0.01')
        channel_id = tx['outputs'][0]['claim_id']

        # resolving a channel @abc
        response = await self.resolve('lbry://@abc')
        self.assertSetEqual({'lbry://@abc'}, set(response))
        self.assertIn('certificate', response['lbry://@abc'])
        self.assertNotIn('claim', response['lbry://@abc'])
        self.assertEqual(response['lbry://@abc']['certificate']['name'], '@abc')
        self.assertEqual(response['lbry://@abc']['claims_in_channel'], 0)

        await self.stream_create('foo', '0.01', channel_id=channel_id)
        await self.stream_create('foo2', '0.01', channel_id=channel_id)

        # resolving a channel @abc with some claims in it
        response = await self.resolve('lbry://@abc')
        self.assertSetEqual({'lbry://@abc'}, set(response))
        self.assertIn('certificate', response['lbry://@abc'])
        self.assertNotIn('claim', response['lbry://@abc'])
        self.assertEqual(response['lbry://@abc']['certificate']['name'], '@abc')
        self.assertEqual(response['lbry://@abc']['claims_in_channel'], 2)

        # resolving claim foo within channel @abc
        response = await self.resolve('lbry://@abc/foo')
        self.assertSetEqual({'lbry://@abc/foo'}, set(response))
        claim = response['lbry://@abc/foo']
        self.assertIn('certificate', claim)
        self.assertIn('claim', claim)
        self.assertEqual(claim['claim']['name'], 'foo')
        self.assertEqual(claim['claim']['channel_name'], '@abc')
        self.assertEqual(claim['certificate']['name'], '@abc')
        self.assertEqual(claim['claims_in_channel'], 0)
        self.assertEqual(
            claim['claim']['timestamp'],
            self.ledger.headers[claim['claim']['height']]['timestamp']
        )
        self.assertEqual(
            claim['certificate']['timestamp'],
            self.ledger.headers[claim['certificate']['height']]['timestamp']
        )

        # resolving claim foo by itself
        response = await self.resolve('lbry://foo')
        self.assertSetEqual({'lbry://foo'}, set(response))
        claim = response['lbry://foo']
        self.assertIn('certificate', claim)
        self.assertIn('claim', claim)
        self.assertEqual(claim['claim']['name'], 'foo')
        self.assertEqual(claim['claim']['channel_name'], '@abc')
        self.assertEqual(claim['certificate']['name'], '@abc')
        self.assertEqual(claim['claims_in_channel'], 0)

        # resolving from the given permanent url
        new_response = await self.resolve(claim['claim']['permanent_url'])
        self.assertEqual(new_response[claim['claim']['permanent_url']], claim)

        # resolving multiple at once
        response = await self.resolve(['lbry://foo', 'lbry://foo2'])
        self.assertSetEqual({'lbry://foo', 'lbry://foo2'}, set(response))
        claim = response['lbry://foo2']
        self.assertIn('certificate', claim)
        self.assertIn('claim', claim)
        self.assertEqual(claim['claim']['name'], 'foo2')
        self.assertEqual(claim['claim']['channel_name'], '@abc')
        self.assertEqual(claim['certificate']['name'], '@abc')
        self.assertEqual(claim['claims_in_channel'], 0)

        # resolve has correct confirmations
        tx_details = await self.blockchain.get_raw_transaction(claim['claim']['txid'])
        self.assertEqual(claim['claim']['confirmations'], json.loads(tx_details)['confirmations'])

        # resolve handles invalid data
        txid = await self.blockchain_claim_name(
            "gibberish", hexlify(b"{'invalid':'json'}").decode(), "0.1")
        response = await self.resolve("lbry://gibberish")
        self.assertSetEqual({'lbry://gibberish'}, set(response))
        claim = response['lbry://gibberish']['claim']
        self.assertEqual(claim['name'], 'gibberish')
        self.assertEqual(claim['protobuf'], hexlify(b"{'invalid':'json'}").decode())
        self.assertFalse(claim['decoded_claim'])
        self.assertEqual(claim['txid'], txid)
        self.assertEqual(claim['effective_amount'], "0.1")

    async def test_canonical_resolve_url(self):
        # test replicating https://github.com/lbryio/lbry/issues/958#issue-266120456

        # create 3 channels
        channel_k1 = await self.channel_create('@kauffj', '0.00001')
        claim_id_kauffj1 = channel_k1["outputs"][0]['claim_id']
        await self.assertCorrectCanonicalUrl('@kauffj', claim_id_kauffj1)

        channel_k2 = await self.get_colliding_claim('@kauffj', claim_id_kauffj1, 1, "channel", None)
        claim_id_kauffj2 = channel_k2["outputs"][0]['claim_id']
        await self.assertCorrectCanonicalUrl('@kauffj', claim_id_kauffj2)

        channel_grin = await self.channel_create('@grin', "0.00001")
        claim_id_grin = channel_grin["outputs"][0]['claim_id']
        await self.assertCorrectCanonicalUrl('@grin', claim_id_grin)

        # create and test claims
        claim_g1 = await self.stream_create('gornado', '0.00001')
        claim_id_g1 = claim_g1["outputs"][0]['claim_id']
        await self.assertCorrectCanonicalUrl('gornado', claim_id_g1)

        claim_g2 = await self.get_colliding_claim('gornado', claim_id_g1, 1, 'claim', None)
        await self.assertCorrectCanonicalUrl('gornado', claim_g2["outputs"][0]['claim_id'])

        claim_gk1 = await self.stream_create('gornado', '0.001', channel_id=claim_id_kauffj1, allow_duplicate_name=True)
        await self.assertCorrectCanonicalUrl('gornado', claim_gk1["outputs"][0]['claim_id'])

        # claim_g21 = await self.get_colliding_claim('gornado', claim_gk1["outputs"][0]['claim_id'], 1, 'claim',
        #                                            claim_id_kauffj1)
        # await self.assertCorrectCanonicalUrl('gornado', claim_g21["outputs"][0]['claim_id'])

        claim_gk2 = await self.stream_create('gornado', '0.001', channel_id=claim_id_kauffj2, allow_duplicate_name=True)
        await self.assertCorrectCanonicalUrl('gornado', claim_gk2["outputs"][0]['claim_id'])

        claim_gg = await self.stream_create('gornado', '0.00001', channel_id=claim_id_grin, allow_duplicate_name=True)
        await self.assertCorrectCanonicalUrl('gornado', claim_gg["outputs"][0]['claim_id'])

    async def assertCorrectCanonicalUrl(self, name, claim_id):
        full_url = "{}#{}".format(name, claim_id)
        resolve_with_claim_id = (await self.resolve(full_url))[full_url]
        result = resolve_with_claim_id.get('claim', resolve_with_claim_id.get('certificate'))
        canonical_url = result.get('canonical_url')

        resolve_with_canonical_url = (await self.resolve(canonical_url))[canonical_url]

        self.assertResolveDictEqual(
            resolve_with_claim_id,
            resolve_with_canonical_url
        )

    def assertResolveDictEqual(self, resolve_dict1, resolve_dict2):
        keys = ['certificate', 'claim']
        for key in resolve_dict1:
            if key in keys:
                if 'valid_at_height' in resolve_dict1[key]:
                    resolve_dict1[key].pop('valid_at_height')
                if 'absolute_channel_position' in resolve_dict1[key]:
                    resolve_dict1[key].pop('absolute_channel_position')

        for key in resolve_dict2:
            if key in keys:
                if 'valid_at_height' in resolve_dict2[key]:
                    resolve_dict2[key].pop('valid_at_height')
                if 'absolute_channel_position' in resolve_dict2[key]:
                    resolve_dict2[key].pop('absolute_channel_position')

        self.assertDictEqual(resolve_dict1, resolve_dict2)

    async def get_colliding_claim(self, name, claim_id, length, claim_type, channel_id):
        if claim_type == "channel":
            claim_tx = await self.daemon.jsonrpc_channel_create(name, "0.001", preview=True,
                                                                allow_duplicate_name=True)
        else:
            with tempfile.NamedTemporaryFile() as file:
                file.write(b'Hi!')
                file.flush()
                claim_tx = await self.daemon.jsonrpc_stream_create(name, "0.001", file.name, channel_id=channel_id,
                                                                   allow_duplicate_name=True, preview=True)

        while True:
            if claim_tx.outputs[0].claim_id.startswith(claim_id[:length]):
                await self.broadcast(claim_tx)
                await self.confirm_tx(claim_tx.id)
                if claim_type == "channel":
                    self.daemon.default_account.add_channel_private_key(claim_tx.outputs[0].ref,
                                                                        claim_tx.outputs[0].private_key)
                    self.daemon.default_wallet.save()
                return self.sout(claim_tx)

            if claim_type == "channel":
                claim_tx.outputs[0].claim.channel.title += "."
                claim_tx.outputs[0].generate_channel_private_key()
            else:
                claim_tx.outputs[0].claim.stream.title += "."

            claim_tx.outputs[0].script.generate()
            claim_tx._reset()
            await claim_tx.sign([self.daemon.default_account])
