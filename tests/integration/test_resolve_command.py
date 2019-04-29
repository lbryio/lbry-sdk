import asyncio
import json
from binascii import hexlify
from lbrynet.testcase import CommandTestCase


class ResolveCommand(CommandTestCase):

    async def test_resolve(self):
        tx = await self.channel_create('@abc', '0.01')
        channel_id = tx['outputs'][0]['claim_id']

        # resolving a channel @abc
        response = await self.resolve('lbry://@abc')
        self.assertSetEqual({'lbry://@abc'}, set(response))
        self.assertEqual(response['lbry://@abc']['name'], '@abc')
        self.assertEqual(response['lbry://@abc']['value_type'], 'channel')
        self.assertEqual(response['lbry://@abc']['meta']['claims_in_channel'], 0)

        await self.stream_create('foo', '0.01', channel_id=channel_id)
        await self.stream_create('foo2', '0.01', channel_id=channel_id)

        # resolving a channel @abc with some claims in it
        response['lbry://@abc']['confirmations'] += 2
        response['lbry://@abc']['meta']['claims_in_channel'] = 2
        self.assertEqual(response, await self.resolve('lbry://@abc'))

        # resolving claim foo within channel @abc
        response = await self.resolve('lbry://@abc/foo')
        self.assertSetEqual({'lbry://@abc/foo'}, set(response))
        claim = response['lbry://@abc/foo']
        self.assertEqual(claim['name'], 'foo')
        self.assertEqual(claim['value_type'], 'stream')
        self.assertEqual(claim['signing_channel']['name'], '@abc')
        self.assertTrue(claim['is_channel_signature_valid'])
        self.assertEqual(
            claim['claim']['timestamp'],
            self.ledger.headers[claim['claim']['height']]['timestamp']
        )
        self.assertEqual(
            claim['certificate']['timestamp'],
            self.ledger.headers[claim['certificate']['height']]['timestamp']
        )

        # resolving claim foo by itself
        self.assertEqual(claim, (await self.resolve('lbry://foo'))['lbry://foo'])
        # resolving from the given permanent url
        permanent_url = response['lbry://@abc/foo']['permanent_url']
        self.assertEqual(claim, (await self.resolve(permanent_url))[permanent_url])

        # resolving multiple at once
        response = await self.resolve(['lbry://foo', 'lbry://foo2'])
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
        response = await self.resolve("lbry://gibberish")
        self.assertSetEqual({'lbry://gibberish'}, set(response))
        claim = response['lbry://gibberish']
        self.assertEqual(claim['name'], 'gibberish')
        self.assertNotIn('value', claim)

    async def _test_resolve_abc_foo(self):
        response = await self.resolve('lbry://@abc/foo')
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

    async def test_resolve_lru_cache_doesnt_persist_errors(self):
        original_get_transaction = self.daemon.wallet_manager.ledger.network.get_transaction

        async def timeout_get_transaction(txid):
            fut = self.loop.create_future()

            def delayed_raise_cancelled_error():
                fut.set_exception(asyncio.CancelledError())

            self.loop.call_soon(delayed_raise_cancelled_error)
            return await fut

        tx = await self.channel_create('@abc', '0.01')
        channel_id = tx['outputs'][0]['claim_id']
        await self.stream_create('foo', '0.01', channel_id=channel_id)

        # raise a cancelled error from get_transaction
        self.daemon.wallet_manager.ledger.network.get_transaction = timeout_get_transaction
        with self.assertRaises(KeyError):
            await self._test_resolve_abc_foo()

        # restore the real get_transaction that doesn't cancel, it should be called and the result cached
        self.daemon.wallet_manager.ledger.network.get_transaction = original_get_transaction
        await self._test_resolve_abc_foo()
        called_again = asyncio.Event(loop=self.loop)

        def check_result_cached(txid):
            called_again.set()
            return original_get_transaction(txid)

        # check that the result was cached
        self.daemon.wallet_manager.ledger.network.get_transaction = check_result_cached
        await self._test_resolve_abc_foo()
        self.assertFalse(called_again.is_set())
