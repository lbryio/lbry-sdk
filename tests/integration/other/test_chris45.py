from lbry.testcase import CommandTestCase


class EpicAdventuresOfChris45(CommandTestCase):

    async def test_no_this_is_not_a_test_its_an_adventure(self):

        # Chris45 is an avid user of LBRY and this is his story. It's fact and fiction
        # and everything in between; it's also the setting of some record setting
        # integration tests.

        # Chris45 starts everyday by checking his balance.
        result = await self.daemon.jsonrpc_account_balance()
        self.assertEqual(result['available'], '10.0')
        # "10 LBC, yippy! I can do a lot with that.", he thinks to himself,
        # enthusiastically. But he is hungry so he goes into the kitchen
        # to make himself a spamdwich.

        # While making the spamdwich he wonders... has anyone on LBRY
        # registered the @spam channel yet? "I should do that!" he
        # exclaims and goes back to his computer to do just that!
        tx = await self.channel_create('@spam', '1.0')
        channel_id = self.get_claim_id(tx)

        # Do we have it locally?
        channels = await self.out(self.daemon.jsonrpc_channel_list())
        self.assertItemCount(channels, 1)
        self.assertEqual(channels['items'][0]['name'], '@spam')

        # As the new channel claim travels through the intertubes and makes its
        # way into the mempool and then a block and then into the claimtrie,
        # Chris doesn't sit idly by: he checks his balance!

        result = await self.daemon.jsonrpc_account_balance()
        self.assertEqual(result['available'], '8.989893')

        # He waits for 6 more blocks (confirmations) to make sure the balance has been settled.
        await self.generate(6)
        result = await self.daemon.jsonrpc_account_balance(confirmations=6)
        self.assertEqual(result['available'], '8.989893')

        # And is the channel resolvable and empty?
        response = await self.resolve('lbry://@spam')
        self.assertEqual(response['value_type'], 'channel')

        # "What goes well with spam?" ponders Chris...
        # "A hovercraft with eels!" he exclaims.
        # "That's what goes great with spam!" he further confirms.

        # And so, many hours later, Chris is finished writing his epic story
        # about eels driving a hovercraft across the wetlands while eating spam
        # and decides it's time to publish it to the @spam channel.
        tx = await self.stream_create(
            'hovercraft', '1.0',
            data=b'[insert long story about eels driving hovercraft]',
            channel_id=channel_id
        )
        claim_id = self.get_claim_id(tx)

        # He quickly checks the unconfirmed balance to make sure everything looks
        # correct.
        result = await self.daemon.jsonrpc_account_balance()
        self.assertEqual(result['available'], '7.969786')

        # Also checks that his new story can be found on the blockchain before
        # giving the link to all his friends.
        response = await self.resolve('lbry://@spam/hovercraft')
        self.assertEqual(response['value_type'], 'stream')

        # He goes to tell everyone about it and in the meantime 5 blocks are confirmed.
        await self.generate(5)
        # When he comes back he verifies the confirmed balance.
        result = await self.daemon.jsonrpc_account_balance()
        self.assertEqual(result['available'], '7.969786')

        # As people start reading his story they discover some typos and notify
        # Chris who explains in despair "Oh! Noooooos!" but then remembers
        # "No big deal! I can update my claim." And so he updates his claim.
        await self.stream_update(claim_id, data=b'[typo fixing sounds being made]')

        # After some soul searching Chris decides that his story needs more
        # heart and a better ending. He takes down the story and begins the rewrite.
        abandon = await self.out(self.daemon.jsonrpc_stream_abandon(claim_id, blocking=True))
        self.assertEqual(abandon['inputs'][0]['claim_id'], claim_id)
        await self.confirm_tx(abandon['txid'])

        # And now checks that the claim doesn't resolve anymore.
        self.assertEqual(
            {'error': {
                'name': 'NOT_FOUND',
                'text': 'Could not find claim at "lbry://@spam/hovercraft".'
            }},
            await self.resolve('lbry://@spam/hovercraft')
        )

        # After abandoning he just waits for his LBCs to be returned to his account
        await self.generate(5)
        result = await self.daemon.jsonrpc_account_balance()
        self.assertEqual(result['available'], '8.9693455')

        # Amidst all this Chris receives a call from his friend Ramsey
        # who says that it is of utmost urgency that Chris transfer him
        # 1 LBC to which Chris readily obliges
        ramsey_account_id = (await self.out(self.daemon.jsonrpc_account_create("Ramsey")))['id']
        ramsey_address = await self.daemon.jsonrpc_address_unused(ramsey_account_id)
        result = await self.out(self.daemon.jsonrpc_account_send('1.0', ramsey_address, blocking=True))
        self.assertIn("txid", result)
        await self.confirm_tx(result['txid'])

        # Chris then eagerly waits for 6 confirmations to check his balance and then calls Ramsey to verify whether
        # he received it or not
        await self.generate(5)
        result = await self.daemon.jsonrpc_account_balance()
        # Chris' balance was correct
        self.assertEqual(result['available'], '7.9692215')

        # Ramsey too assured him that he had received the 1 LBC and thanks him
        result = await self.daemon.jsonrpc_account_balance(ramsey_account_id)
        self.assertEqual(result['available'], '1.0')

        # After Chris is done with all the "helping other people" stuff he decides that it's time to
        # write a new story and publish it to lbry. All he needed was a fresh start and he came up with:
        tx = await self.stream_create(
            'fresh-start', '1.0', data=b'Amazingly Original First Line', channel_id=channel_id
        )
        claim_id2 = self.get_claim_id(tx)

        await self.generate(5)

        # He gives the link of his story to all his friends and hopes that this is the much needed break for him
        uri = 'lbry://@spam/fresh-start'

        # And voila, and bravo and encore! His Best Friend Ramsey read the story and immediately knew this was a hit
        # Now to keep this claim winning on the lbry blockchain he immediately supports the claim
        tx = await self.out(self.daemon.jsonrpc_support_create(
            claim_id2, '0.2', account_id=ramsey_account_id, blocking=True
        ))
        await self.confirm_tx(tx['txid'])

        # And check if his support showed up
        resolve_result = await self.resolve(uri)
        # It obviously did! Because, blockchain baby \O/
        self.assertEqual(resolve_result['amount'], '1.0')
        self.assertEqual(resolve_result['meta']['effective_amount'], '1.2')
        await self.generate(5)

        # Now he also wanted to support the original creator of the Award Winning Novel
        # So he quickly decides to send a tip to him
        tx = await self.out(
            self.daemon.jsonrpc_support_create(claim_id2, '0.3', tip=True, account_id=ramsey_account_id, blocking=True)
        )
        await self.confirm_tx(tx['txid'])

        # And again checks if it went to the just right place
        resolve_result = await self.resolve(uri)
        # Which it obviously did. Because....?????
        self.assertEqual(resolve_result['meta']['effective_amount'], '1.5')
        await self.generate(5)

        # Seeing the ravishing success of his novel Chris adds support to his claim too
        tx = await self.out(self.daemon.jsonrpc_support_create(claim_id2, '0.4', blocking=True))
        await self.confirm_tx(tx['txid'])

        # And check if his support showed up
        resolve_result = await self.out(self.daemon.jsonrpc_resolve(uri))
        # It did!
        self.assertEqual(resolve_result[uri]['meta']['effective_amount'], '1.9')
        await self.generate(5)

        # Now Ramsey who is a singer by profession, is preparing for his new "gig". He has everything in place for that
        # the instruments, the theatre, the ads, everything, EXCEPT lyrics!! He panicked.. But then he remembered
        # something, so he un-panicked. He quickly calls up his best bud Chris and requests him to write hit lyrics for
        # his song, seeing as his novel had smashed all the records, he was the perfect candidate!
        # .......
        # Chris agrees.. 17 hours 43 minutes and 14 seconds later, he makes his publish
        tx = await self.stream_create(
            'hit-song', '1.0', data=b'The Whale and The Bookmark', channel_id=channel_id
        )
        await self.generate(5)

        # He sends the link to Ramsey, all happy and proud
        uri = 'lbry://@spam/hit-song'

        # But sadly Ramsey wasn't so pleased. It was hard for him to tell Chris...
        # Chris, though a bit heartbroken, abandoned the claim for now, but instantly started working on new hit lyrics
        abandon = await self.out(self.daemon.jsonrpc_stream_abandon(txid=tx['txid'], nout=0, blocking=True))
        self.assertTrue(abandon['inputs'][0]['txid'], tx['txid'])
        await self.confirm_tx(abandon['txid'])

        # He them checks that the claim doesn't resolve anymore.
        self.assertEqual(
            {'error': {
                'name': 'NOT_FOUND',
                'text': f'Could not find claim at "{uri}".'
            }},
            await self.resolve(uri)
        )

        # He closes and opens the wallet server databases to see how horribly they break
        db = self.conductor.spv_node.server.db
        db.close()
        db.open_db()
        await db.initialize_caches()
        # They didn't! (error would be AssertionError: 276 vs 266 (264 counts) on startup)
