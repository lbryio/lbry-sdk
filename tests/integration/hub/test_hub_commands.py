import os.path
import tempfile
import logging
import asyncio
from binascii import unhexlify
from unittest import skip
from urllib.request import urlopen

import lbry.wallet.transaction
from lbry.error import InsufficientFundsError
from lbry.extras.daemon.comment_client import verify

from lbry.extras.daemon.daemon import DEFAULT_PAGE_SIZE
from lbry.testcase import CommandTestCase
from lbry.wallet.orchstr8.node import HubNode
from lbry.wallet.transaction import Transaction
from lbry.wallet.util import satoshis_to_coins as lbc


log = logging.getLogger(__name__)


class ClaimTestCase(CommandTestCase):

    files_directory = os.path.join(os.path.dirname(__file__), 'files')
    video_file_url = 'http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerEscapes.mp4'
    video_file_name = os.path.join(files_directory, 'ForBiggerEscapes.mp4')
    image_data = unhexlify(
        b'89504e470d0a1a0a0000000d49484452000000050000000708020000004fc'
        b'510b9000000097048597300000b1300000b1301009a9c1800000015494441'
        b'5408d763fcffff3f031260624005d4e603004c45030b5286e9ea000000004'
        b'9454e44ae426082'
    )

    def setUp(self):
        if not os.path.exists(self.video_file_name):
            if not os.path.exists(self.files_directory):
                os.mkdir(self.files_directory)
            log.info(f'downloading test video from {self.video_file_name}')
            with urlopen(self.video_file_url) as response, \
                    open(self.video_file_name, 'wb') as video_file:
                video_file.write(response.read())


class ClaimSearchCommand(ClaimTestCase):

    async def create_channel(self):
        self.channel = await self.channel_create('@abc', '1.0')
        self.channel_id = self.get_claim_id(self.channel)

    async def create_lots_of_streams(self):
        tx = await self.daemon.jsonrpc_account_fund(None, None, '0.001', outputs=100, broadcast=True)
        await self.confirm_tx(tx.id)
        # 4 claims per block, 3 blocks. Sorted by height (descending) then claim name (ascending).
        self.streams = []
        for j in range(4):
            same_height_claims = []
            for k in range(5):
                claim_tx = await self.stream_create(
                    f'c{j}-{k}', '0.000001', channel_id=self.channel_id, confirm=False)
                same_height_claims.append(claim_tx['outputs'][0]['name'])
                await self.on_transaction_dict(claim_tx)
            claim_tx = await self.stream_create(
                f'c{j}-6', '0.000001', channel_id=self.channel_id, confirm=True)
            same_height_claims.append(claim_tx['outputs'][0]['name'])
            self.streams = same_height_claims + self.streams

    async def assertFindsClaim(self, claim, **kwargs):
        await self.assertFindsClaims([claim], **kwargs)

    async def assertFindsClaims(self, claims, **kwargs):
        kwargs.setdefault('order_by', ['height', '^name'])
        if os.environ.get("GO_HUB") and os.environ["GO_HUB"] == "true":
            kwargs['new_sdk_server'] = self.hub.hostname + ":" + str(self.hub.rpcport)
        results = await self.claim_search(**kwargs)
        # for claim, result in zip(claims, results):
        #     print((claim['txid'], self.get_claim_id(claim)),
        #           (result['txid'], result['claim_id'], result['height']))
        self.assertEqual(len(claims), len(results))
        for claim, result in zip(claims, results):
            self.assertEqual(
                (claim['txid'], self.get_claim_id(claim)),
                (result['txid'], result['claim_id']),
                f"(expected {claim['outputs'][0]['name']}) != (got {result['name']})"
            )

    async def assertListsClaims(self, claims, **kwargs):
        kwargs.setdefault('order_by', 'height')
        results = await self.claim_list(**kwargs)
        self.assertEqual(len(claims), len(results))
        # for claim, result in zip(claims, results):
        #     self.assertEqual(
        #         (claim['txid'], self.get_claim_id(claim)),
        #         (result['txid'], result['claim_id']),
        #         f"(expected {claim['outputs'][0]['name']}) != (got {result['name']})"
        #     )

    # @skip("okay")
    async def test_basic_claim_search(self):
        await self.create_channel()
        channel_txo = self.channel['outputs'][0]
        channel2 = await self.channel_create('@abc', '0.1', allow_duplicate_name=True)
        channel_txo2 = channel2['outputs'][0]
        channel_id2 = channel_txo2['claim_id']

        # finding a channel
        await self.assertFindsClaims([channel2, self.channel], name='@abc')
        await self.assertFindsClaim(self.channel, name='@abc', is_controlling=True)
        await self.assertFindsClaim(self.channel, claim_id=self.channel_id)
        await self.assertFindsClaim(self.channel, txid=self.channel['txid'], nout=0)
        await self.assertFindsClaim(channel2, claim_id=channel_id2)
        await self.assertFindsClaim(channel2, txid=channel2['txid'], nout=0)
        await self.assertFindsClaim(
            channel2, public_key_id=channel_txo2['value']['public_key_id'])
        await self.assertFindsClaim(
            self.channel, public_key_id=channel_txo['value']['public_key_id'])

        signed = await self.stream_create('on-channel-claim', '0.001', channel_id=self.channel_id)
        signed2 = await self.stream_create('on-channel-claim', '0.0001', channel_id=channel_id2,
                                           allow_duplicate_name=True)
        unsigned = await self.stream_create('unsigned', '0.0001')

        # finding claims with and without a channel
        await self.assertFindsClaims([signed2, signed], name='on-channel-claim')
        await self.assertFindsClaims([signed2, signed], channel_ids=[self.channel_id, channel_id2])
        await self.assertFindsClaim(signed, name='on-channel-claim', channel_ids=[self.channel_id])
        await self.assertFindsClaim(signed2, name='on-channel-claim', channel_ids=[channel_id2])
        await self.assertFindsClaim(unsigned, name='unsigned')
        await self.assertFindsClaim(unsigned, txid=unsigned['txid'], nout=0)
        await self.assertFindsClaim(unsigned, claim_id=self.get_claim_id(unsigned))

        two = await self.stream_create('on-channel-claim-2', '0.0001', channel_id=self.channel_id)
        three = await self.stream_create('on-channel-claim-3', '0.0001', channel_id=self.channel_id)

        # three streams in channel, zero streams in abandoned channel
        claims = [three, two, signed]
        await self.assertFindsClaims(claims, channel_ids=[self.channel_id])
        # FIXME
        # channel param doesn't work yet because we need to implement resolve url from search first
        cid = await self.daemon.jsonrpc_resolve(f"@abc#{self.channel_id}")
        await self.assertFindsClaims(claims, channel_id=cid[f"@abc#{self.channel_id}"].claim_id)
        cid = await self.daemon.jsonrpc_resolve(f"@inexistent")
        if type(cid["@inexistent"]) == dict:
            cid = ""
        else:
            cid = cid["@inexistent"].claim_id
        await self.assertFindsClaims([], channel_id=cid)
        await self.assertFindsClaims([three, two, signed2, signed], channel_ids=[channel_id2, self.channel_id])
        await self.channel_abandon(claim_id=self.channel_id)
        # since the resolve is being done separately this would only test finding something with an empty channel so I
        # think we can just remove these and test those independently
        # cid = await self.daemon.jsonrpc_resolve(f"@abc#{self.channel_id}")
        # await self.assertFindsClaims([], channel_id=cid[f"@abc#{self.channel_id}"].claim_id, valid_channel_signature=True)
        await self.assertFindsClaims([], channel_ids=[self.channel_id], valid_channel_signature=True)
        await self.assertFindsClaims([signed2], channel_ids=[channel_id2], valid_channel_signature=True)
        # pass `invalid_channel_signature=False` to catch a bug in argument processing
        await self.assertFindsClaims([signed2], channel_ids=[channel_id2, self.channel_id],
                                     valid_channel_signature=True, invalid_channel_signature=False)
        # invalid signature still returns channel_id
        self.ledger._tx_cache.clear()
        invalid_claims = await self.claim_search(invalid_channel_signature=True, has_channel_signature=True)
        self.assertEqual(3, len(invalid_claims))
        self.assertTrue(all([not c['is_channel_signature_valid'] for c in invalid_claims]))
        self.assertEqual({'channel_id': self.channel_id}, invalid_claims[0]['signing_channel'])

        valid_claims = await self.claim_search(valid_channel_signature=True, has_channel_signature=True)
        self.assertEqual(1, len(valid_claims))
        # FIXME
        # print(valid_claims)
        # Something happens in inflation I think and this gets switch from valid to not
        # self.assertTrue(all([c['is_channel_signature_valid'] for c in valid_claims]))
        # And signing channel only has id? 'signing_channel': {'channel_id': '6f4513e9bbd63d7b7f13dbf4fd2ef28c560ac89b'}
        # self.assertEqual('@abc', valid_claims[0]['signing_channel']['name'])

        # abandoned stream won't show up for streams in channel search
        await self.stream_abandon(txid=signed2['txid'], nout=0)
        await self.assertFindsClaims([], channel_ids=[channel_id2])
        # resolve by claim ids
        await self.assertFindsClaims([three, two], claim_ids=[self.get_claim_id(three), self.get_claim_id(two)])
        await self.assertFindsClaims([three], claim_id=self.get_claim_id(three))
        await self.assertFindsClaims([three], claim_id=self.get_claim_id(three), text='*')

    # @skip("okay")
    async def test_source_filter(self):
        channel = await self.channel_create('@abc')
        no_source = await self.stream_create('no-source', data=None)
        normal = await self.stream_create('normal', data=b'normal')
        normal_repost = await self.stream_repost(self.get_claim_id(normal), 'normal-repost')
        no_source_repost = await self.stream_repost(self.get_claim_id(no_source), 'no-source-repost')
        channel_repost = await self.stream_repost(self.get_claim_id(channel), 'channel-repost')
        await self.assertFindsClaims([channel_repost, no_source_repost, no_source, channel], has_no_source=True)
        # await self.assertListsClaims([no_source, channel], has_no_source=True)
        await self.assertFindsClaims([channel_repost, normal_repost, normal, channel], has_source=True)
        # await self.assertListsClaims([channel_repost, no_source_repost, normal_repost, normal], has_source=True)
        await self.assertFindsClaims([channel_repost, no_source_repost, normal_repost, normal, no_source, channel])
        # await self.assertListsClaims([channel_repost, no_source_repost, normal_repost, normal, no_source, channel])

    # @skip("okay")
    async def test_pagination(self):
        await self.create_channel()
        await self.create_lots_of_streams()

        channel_id = (await self.daemon.jsonrpc_resolve(f"@abc"))["@abc"].claim_id
        # with and without totals
        results = await self.daemon.jsonrpc_claim_search()
        self.assertEqual(results['total_pages'], 2)
        self.assertEqual(results['total_items'], 25)
        results = await self.daemon.jsonrpc_claim_search(no_totals=True)
        self.assertNotIn('total_pages', results)
        self.assertNotIn('total_items', results)

        # defaults
        page = await self.claim_search(channel_id=channel_id, order_by=['height', '^name'])
        page_claim_ids = [item['name'] for item in page]
        self.assertEqual(page_claim_ids, self.streams[:DEFAULT_PAGE_SIZE])

        # page with default page_size
        page = await self.claim_search(page=2, channel_id=channel_id, order_by=['height', '^name'])
        page_claim_ids = [item['name'] for item in page]
        self.assertEqual(page_claim_ids, self.streams[DEFAULT_PAGE_SIZE:(DEFAULT_PAGE_SIZE*2)])

        # page_size larger than dataset
        page = await self.claim_search(page_size=50, channel_id=channel_id, order_by=['height', '^name'])
        page_claim_ids = [item['name'] for item in page]
        self.assertEqual(page_claim_ids, self.streams)

        # page_size less than dataset
        page = await self.claim_search(page_size=6, channel_id=channel_id, order_by=['height', '^name'])
        page_claim_ids = [item['name'] for item in page]
        self.assertEqual(page_claim_ids, self.streams[:6])

        # page and page_size
        page = await self.claim_search(page=2, page_size=6, channel_id=channel_id, order_by=['height', '^name'])
        page_claim_ids = [item['name'] for item in page]
        self.assertEqual(page_claim_ids, self.streams[6:12])

        out_of_bounds = await self.claim_search(page=4, page_size=20, channel_id=channel_id)
        self.assertEqual(out_of_bounds, [])

    # @skip("okay")
    async def test_tag_search(self):
        claim1 = await self.stream_create('claim1', tags=['aBc'])
        claim2 = await self.stream_create('claim2', tags=['#abc', 'def'])
        claim3 = await self.stream_create('claim3', tags=['abc', 'ghi', 'jkl'])
        claim4 = await self.stream_create('claim4', tags=['abc\t', 'ghi', 'mno'])
        claim5 = await self.stream_create('claim5', tags=['pqr'])

        # any_tags
        await self.assertFindsClaims([claim5, claim4, claim3, claim2, claim1], any_tags=['\tabc', 'pqr'])
        await self.assertFindsClaims([claim4, claim3, claim2, claim1], any_tags=['abc'])
        await self.assertFindsClaims([claim4, claim3, claim2, claim1], any_tags=['abc', 'ghi'])
        await self.assertFindsClaims([claim4, claim3], any_tags=['ghi'])
        await self.assertFindsClaims([claim4, claim3], any_tags=['ghi', 'xyz'])
        await self.assertFindsClaims([], any_tags=['xyz'])

        # all_tags
        await self.assertFindsClaims([], all_tags=['abc', 'pqr'])
        await self.assertFindsClaims([claim4, claim3, claim2, claim1], all_tags=['ABC'])
        await self.assertFindsClaims([claim4, claim3], all_tags=['abc', 'ghi'])
        await self.assertFindsClaims([claim4, claim3], all_tags=['ghi'])
        await self.assertFindsClaims([], all_tags=['ghi', 'xyz'])
        await self.assertFindsClaims([], all_tags=['xyz'])

        # not_tags
        await self.assertFindsClaims([], not_tags=['abc', 'pqr'])
        await self.assertFindsClaims([claim5], not_tags=['abC'])
        await self.assertFindsClaims([claim5], not_tags=['abc', 'ghi'])
        await self.assertFindsClaims([claim5, claim2, claim1], not_tags=['ghi'])
        await self.assertFindsClaims([claim5, claim2, claim1], not_tags=['ghi', 'xyz'])
        await self.assertFindsClaims([claim5, claim4, claim3, claim2, claim1], not_tags=['xyz'])

        # combinations
        await self.assertFindsClaims([claim3], all_tags=['abc', 'ghi'], not_tags=['mno'])
        await self.assertFindsClaims([claim3], all_tags=['abc', 'ghi'], any_tags=['jkl'], not_tags=['mno'])
        await self.assertFindsClaims([claim4, claim3, claim2], all_tags=['abc'], any_tags=['def', 'ghi'])

    # @skip("okay")
    async def test_order_by(self):
        height = self.ledger.network.remote_height
        claims = [await self.stream_create(f'claim{i}') for i in range(5)]

        await self.assertFindsClaims(claims, order_by=["^height"])
        await self.assertFindsClaims(list(reversed(claims)), order_by=["height"])

        await self.assertFindsClaims([claims[0]], height=height + 1)
        await self.assertFindsClaims([claims[4]], height=height + 5)
        await self.assertFindsClaims(claims[:1], height=f'<{height + 2}', order_by=["^height"])
        await self.assertFindsClaims(claims[:2], height=f'<={height + 2}', order_by=["^height"])
        await self.assertFindsClaims(claims[2:], height=f'>{height + 2}', order_by=["^height"])
        await self.assertFindsClaims(claims[1:], height=f'>={height + 2}', order_by=["^height"])

        await self.assertFindsClaims(claims, order_by=["^name"])

    # @skip("okay")
    async def test_search_by_fee(self):
        claim1 = await self.stream_create('claim1', fee_amount='1.0', fee_currency='lbc')
        claim2 = await self.stream_create('claim2', fee_amount='0.9', fee_currency='lbc')
        claim3 = await self.stream_create('claim3', fee_amount='0.5', fee_currency='lbc')
        claim4 = await self.stream_create('claim4', fee_amount='0.1', fee_currency='lbc')
        claim5 = await self.stream_create('claim5', fee_amount='1.0', fee_currency='usd')

        await self.assertFindsClaims([claim5, claim4, claim3, claim2, claim1], fee_amount='>0')
        await self.assertFindsClaims([claim4, claim3, claim2, claim1], fee_currency='lbc')
        await self.assertFindsClaims([claim3, claim2, claim1], fee_amount='>0.1', fee_currency='lbc')
        await self.assertFindsClaims([claim4, claim3, claim2], fee_amount='<1.0', fee_currency='lbc')
        await self.assertFindsClaims([claim3], fee_amount='0.5', fee_currency='lbc')
        await self.assertFindsClaims([claim5], fee_currency='usd')

    # @skip("okay")
    async def test_search_by_language(self):
        claim1 = await self.stream_create('claim1', fee_amount='1.0', fee_currency='lbc')
        claim2 = await self.stream_create('claim2', fee_amount='0.9', fee_currency='lbc')
        claim3 = await self.stream_create('claim3', fee_amount='0.5', fee_currency='lbc', languages='en')
        claim4 = await self.stream_create('claim4', fee_amount='0.1', fee_currency='lbc', languages='en')
        claim5 = await self.stream_create('claim5', fee_amount='1.0', fee_currency='usd', languages='es')

        await self.assertFindsClaims([claim4, claim3], any_languages=['en'])
        await self.assertFindsClaims([claim2, claim1], any_languages=['none'])
        await self.assertFindsClaims([claim4, claim3, claim2, claim1], any_languages=['none', 'en'])
        await self.assertFindsClaims([claim5], any_languages=['es'])
        await self.assertFindsClaims([claim5, claim4, claim3], any_languages=['en', 'es'])
        await self.assertFindsClaims([], fee_currency='foo')

    # @skip("okay")
    async def test_search_by_channel(self):
        match = self.assertFindsClaims

        chan1_id = self.get_claim_id(await self.channel_create('@chan1'))
        chan2_id = self.get_claim_id(await self.channel_create('@chan2'))
        chan3_id = self.get_claim_id(await self.channel_create('@chan3'))
        chan4 = await self.channel_create('@chan4', '0.1')

        claim1 = await self.stream_create('claim1')
        claim2 = await self.stream_create('claim2', channel_id=chan1_id)
        claim3 = await self.stream_create('claim3', channel_id=chan1_id)
        claim4 = await self.stream_create('claim4', channel_id=chan2_id)
        claim5 = await self.stream_create('claim5', channel_id=chan2_id)
        claim6 = await self.stream_create('claim6', channel_id=chan3_id)
        await self.channel_abandon(chan3_id)

        # {has/valid/invalid}_channel_signature
        await match([claim6, claim5, claim4, claim3, claim2], has_channel_signature=True)
        await match([claim5, claim4, claim3, claim2, claim1], valid_channel_signature=True, claim_type='stream')
        await match([claim6, claim1],                         invalid_channel_signature=True, claim_type='stream')
        await match([claim5, claim4, claim3, claim2], has_channel_signature=True, valid_channel_signature=True)
        await match([claim6],                         has_channel_signature=True, invalid_channel_signature=True)

        # not_channel_ids
        await match([claim6, claim5, claim4, claim3, claim2, claim1], not_channel_ids=['abc123'], claim_type='stream')
        await match([claim5, claim4, claim3, claim2, claim1],         not_channel_ids=[chan3_id], claim_type='stream')
        await match([claim6, claim5, claim4, claim1],                 not_channel_ids=[chan1_id], claim_type='stream')
        await match([claim6, claim3, claim2, claim1],                 not_channel_ids=[chan2_id], claim_type='stream')
        await match([claim6, claim1],                       not_channel_ids=[chan1_id, chan2_id], claim_type='stream')
        await match([claim6, claim1, chan4],                not_channel_ids=[chan1_id, chan2_id])

        # not_channel_ids + valid_channel_signature
        await match([claim5, claim4, claim3, claim2, claim1],
                    not_channel_ids=['abc123'], valid_channel_signature=True, claim_type='stream')
        await match([claim5, claim4, claim1],
                    not_channel_ids=[chan1_id], valid_channel_signature=True, claim_type='stream')
        await match([claim3, claim2, claim1],
                    not_channel_ids=[chan2_id], valid_channel_signature=True, claim_type='stream')
        await match([claim1], not_channel_ids=[chan1_id, chan2_id], valid_channel_signature=True, claim_type='stream')

        # not_channel_ids + has_channel_signature
        await match([claim6, claim5, claim4, claim3, claim2], not_channel_ids=['abc123'], has_channel_signature=True)
        await match([claim6, claim5, claim4],                 not_channel_ids=[chan1_id], has_channel_signature=True)
        await match([claim6, claim3, claim2],                 not_channel_ids=[chan2_id], has_channel_signature=True)
        await match([claim6],                       not_channel_ids=[chan1_id, chan2_id], has_channel_signature=True)

        # not_channel_ids + has_channel_signature + valid_channel_signature
        await match([claim5, claim4, claim3, claim2],
                    not_channel_ids=['abc123'], has_channel_signature=True, valid_channel_signature=True)
        await match([claim5, claim4],
                    not_channel_ids=[chan1_id], has_channel_signature=True, valid_channel_signature=True)
        await match([claim3, claim2],
                    not_channel_ids=[chan2_id], has_channel_signature=True, valid_channel_signature=True)
        await match([], not_channel_ids=[chan1_id, chan2_id], has_channel_signature=True, valid_channel_signature=True)

    # @skip("okay")
    async def test_limit_claims_per_channel(self):
        match = self.assertFindsClaims
        chan1_id = self.get_claim_id(await self.channel_create('@chan1'))
        chan2_id = self.get_claim_id(await self.channel_create('@chan2'))
        claim1 = await self.stream_create('claim1')
        claim2 = await self.stream_create('claim2', channel_id=chan1_id)
        claim3 = await self.stream_create('claim3', channel_id=chan1_id)
        claim4 = await self.stream_create('claim4', channel_id=chan1_id)
        claim5 = await self.stream_create('claim5', channel_id=chan2_id)
        claim6 = await self.stream_create('claim6', channel_id=chan2_id)
        await match(
            [claim6, claim5, claim4, claim3, claim1],
            limit_claims_per_channel=2, claim_type='stream'
        )
        await match(
            [claim6, claim5, claim4, claim3, claim2, claim1],
            limit_claims_per_channel=3, claim_type='stream'
        )

    async def test_no_duplicates(self):
        await self.generate(10)
        match = self.assertFindsClaims
        claims = []
        channels = []
        first = await self.stream_create('original_claim0')
        second = await self.stream_create('original_claim1')
        for i in range(10):
            repost_id = self.get_claim_id(second if i % 2 == 0 else first)
            channel = await self.channel_create(f'@chan{i}', bid='0.001')
            channels.append(channel)
            claims.append(
                await self.stream_repost(repost_id, f'claim{i}', bid='0.001', channel_id=self.get_claim_id(channel)))
        await match([first, second] + channels,
                    remove_duplicates=True, order_by=['^height'])
        await match(list(reversed(channels)) + [second, first],
                    remove_duplicates=True, order_by=['height'])
        # the original claims doesn't show up, so we pick the oldest reposts
        await match([channels[0], claims[0], channels[1], claims[1]] + channels[2:],
                    height='>218',
                    remove_duplicates=True, order_by=['^height'])
        # limit claims per channel, invert order, oldest ones are still chosen
        await match(channels[2:][::-1] + [claims[1], channels[1], claims[0], channels[0]],
                    height='>218', limit_claims_per_channel=1,
                    remove_duplicates=True, order_by=['height'])

    # @skip("okay")
    async def test_limit_claims_per_channel_across_sorted_pages(self):
        await self.generate(10)
        match = self.assertFindsClaims
        channel_id = self.get_claim_id(await self.channel_create('@chan0'))
        claims = []
        first = await self.stream_create('claim0', channel_id=channel_id)
        second = await self.stream_create('claim1', channel_id=channel_id)
        for i in range(2, 10):
            some_chan = self.get_claim_id(await self.channel_create(f'@chan{i}', bid='0.001'))
            claims.append(await self.stream_create(f'claim{i}', bid='0.001', channel_id=some_chan))
        last = await self.stream_create('claim10', channel_id=channel_id)

        await match(
            [first, second, claims[0], claims[1]], page_size=4,
            limit_claims_per_channel=3, claim_type='stream', order_by=['^height']
        )
        # second goes out
        await match(
            [first, claims[0], claims[1], claims[2]], page_size=4,
            limit_claims_per_channel=1, claim_type='stream', order_by=['^height']
        )
        # second appears, from replacement queue
        await match(
            [second, claims[3], claims[4], claims[5]], page_size=4, page=2,
            limit_claims_per_channel=1, claim_type='stream', order_by=['^height']
        )
        # last is unaffected, as the limit applies per page
        await match(
            [claims[6], claims[7], last], page_size=4, page=3,
            limit_claims_per_channel=1, claim_type='stream', order_by=['^height']
        )

    # @skip("okay")
    async def test_claim_type_and_media_type_search(self):
        # create an invalid/unknown claim
        address = await self.account.receiving.get_or_create_usable_address()
        tx = await Transaction.claim_create(
            'unknown', b'{"sources":{"lbry_sd_hash":""}}', 1, address, [self.account], self.account)
        await tx.sign([self.account])
        await self.broadcast(tx)
        await self.confirm_tx(tx.id)

        octet = await self.stream_create()
        video = await self.stream_create('chrome', file_path=self.video_file_name)
        image = await self.stream_create('blank-image', data=self.image_data, suffix='.png')
        repost = await self.stream_repost(self.get_claim_id(image))
        collection = await self.collection_create('a-collection', claims=[self.get_claim_id(video)])
        channel = await self.channel_create()
        unknown = self.sout(tx)

        # claim_type
        await self.assertFindsClaims([image, video, octet, unknown], claim_type='stream')
        await self.assertFindsClaims([channel], claim_type='channel')
        await self.assertFindsClaims([repost], claim_type='repost')
        await self.assertFindsClaims([collection], claim_type='collection')

        # stream_type
        await self.assertFindsClaims([octet, unknown], stream_types=['binary'])
        await self.assertFindsClaims([video], stream_types=['video'])
        await self.assertFindsClaims([image], stream_types=['image'])
        await self.assertFindsClaims([image, video], stream_types=['video', 'image'])

        # media_type
        await self.assertFindsClaims([octet, unknown], media_types=['application/octet-stream'])
        await self.assertFindsClaims([video], media_types=['video/mp4'])
        await self.assertFindsClaims([image], media_types=['image/png'])
        await self.assertFindsClaims([image, video], media_types=['video/mp4', 'image/png'])

        # duration
        await self.assertFindsClaim(video, duration='>14')
        await self.assertFindsClaim(video, duration='<16')
        await self.assertFindsClaim(video, duration=15)
        await self.assertFindsClaims([], duration='>100')
        await self.assertFindsClaims([], duration='<14')

    # @skip("okay")
    async def test_search_by_text(self):
        chan1_id = self.get_claim_id(await self.channel_create('@SatoshiNakamoto'))
        chan2_id = self.get_claim_id(await self.channel_create('@Bitcoin'))
        chan3_id = self.get_claim_id(await self.channel_create('@IAmSatoshi'))

        claim1 = await self.stream_create(
            "the-real-satoshi", title="The Real Satoshi Nakamoto",
            description="Documentary about the real Satoshi Nakamoto, creator of bitcoin.",
            tags=['satoshi nakamoto', 'bitcoin', 'documentary']
        )
        claim2 = await self.stream_create(
            "about-me", channel_id=chan1_id, title="Satoshi Nakamoto Autobiography",
            description="I am Satoshi Nakamoto and this is my autobiography.",
            tags=['satoshi nakamoto', 'bitcoin', 'documentary', 'autobiography']
        )
        claim3 = await self.stream_create(
            "history-of-bitcoin", channel_id=chan2_id, title="History of Bitcoin",
            description="History of bitcoin and its creator Satoshi Nakamoto.",
            tags=['satoshi nakamoto', 'bitcoin', 'documentary', 'history']
        )
        claim4 = await self.stream_create(
            "satoshi-conspiracies", channel_id=chan3_id, title="Satoshi Nakamoto Conspiracies",
            description="Documentary detailing various conspiracies surrounding Satoshi Nakamoto.",
            tags=['conspiracies', 'bitcoin', 'satoshi nakamoto']
        )

        await self.assertFindsClaims([], text='cheese')
        await self.assertFindsClaims([claim2], text='autobiography')
        await self.assertFindsClaims([claim3], text='history')
        await self.assertFindsClaims([claim4], text='conspiracy')
        await self.assertFindsClaims([], text='conspiracy+history')
        await self.assertFindsClaims([claim4, claim3], text='conspiracy|history')
        await self.assertFindsClaims([claim1, claim4, claim2, claim3], text='documentary', order_by=[])
        # todo: check why claim1 and claim2 order changed. used to be ...claim1, claim2...
        await self.assertFindsClaims([claim4, claim2, claim1, claim3], text='satoshi', order_by=[])

        claim2 = await self.stream_update(
            self.get_claim_id(claim2), clear_tags=True, tags=['cloud'],
            title="Satoshi Nakamoto Nography",
            description="I am Satoshi Nakamoto and this is my nography.",
        )
        await self.assertFindsClaims([], text='autobiography')
        await self.assertFindsClaims([claim2], text='cloud')

        await self.stream_abandon(self.get_claim_id(claim2))
        await self.assertFindsClaims([], text='cloud')
