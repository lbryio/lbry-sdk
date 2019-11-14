import os.path
import tempfile
import logging
from binascii import unhexlify
from urllib.request import urlopen


from torba.client.errors import InsufficientFundsError

from lbry.extras.daemon.Daemon import DEFAULT_PAGE_SIZE
from lbry.testcase import CommandTestCase
from lbry.wallet.transaction import Transaction


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
        results = await self.claim_search(**kwargs)
        self.assertEqual(len(claims), len(results))
        for claim, result in zip(claims, results):
            self.assertEqual(
                (claim['txid'], self.get_claim_id(claim)),
                (result['txid'], result['claim_id'])
            )

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
        await self.assertFindsClaims(claims, channel=f"@abc#{self.channel_id}")
        await self.assertFindsClaims([three, two, signed2, signed], channel_ids=[channel_id2, self.channel_id])
        await self.channel_abandon(claim_id=self.channel_id)
        await self.assertFindsClaims([], channel=f"@abc#{self.channel_id}", valid_channel_signature=True)
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
        self.assertTrue(all([c['is_channel_signature_valid'] for c in valid_claims]))
        self.assertEqual('@abc', valid_claims[0]['signing_channel']['name'])

        # abandoned stream won't show up for streams in channel search
        await self.stream_abandon(txid=signed2['txid'], nout=0)
        await self.assertFindsClaims([], channel_ids=[channel_id2])

    async def test_pagination(self):
        await self.create_channel()
        await self.create_lots_of_streams()

        # with and without totals
        results = await self.daemon.jsonrpc_claim_search()
        self.assertEqual(results['total_pages'], 2)
        self.assertEqual(results['total_items'], 25)
        results = await self.daemon.jsonrpc_claim_search(no_totals=True)
        self.assertNotIn('total_pages', results)
        self.assertNotIn('total_items', results)

        # defaults
        page = await self.claim_search(channel='@abc', order_by=['height', '^name'])
        page_claim_ids = [item['name'] for item in page]
        self.assertEqual(page_claim_ids, self.streams[:DEFAULT_PAGE_SIZE])

        # page with default page_size
        page = await self.claim_search(page=2, channel='@abc', order_by=['height', '^name'])
        page_claim_ids = [item['name'] for item in page]
        self.assertEqual(page_claim_ids, self.streams[DEFAULT_PAGE_SIZE:(DEFAULT_PAGE_SIZE*2)])

        # page_size larger than dataset
        page = await self.claim_search(page_size=50, channel='@abc', order_by=['height', '^name'])
        page_claim_ids = [item['name'] for item in page]
        self.assertEqual(page_claim_ids, self.streams)

        # page_size less than dataset
        page = await self.claim_search(page_size=6, channel='@abc', order_by=['height', '^name'])
        page_claim_ids = [item['name'] for item in page]
        self.assertEqual(page_claim_ids, self.streams[:6])

        # page and page_size
        page = await self.claim_search(page=2, page_size=6, channel='@abc', order_by=['height', '^name'])
        page_claim_ids = [item['name'] for item in page]
        self.assertEqual(page_claim_ids, self.streams[6:12])

        out_of_bounds = await self.claim_search(page=4, page_size=20, channel='@abc')
        self.assertEqual(out_of_bounds, [])

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

    async def test_order_by(self):
        height = self.ledger.network.remote_height
        claims = [await self.stream_create(f'claim{i}') for i in range(5)]

        await self.assertFindsClaims(claims, order_by=["^height"])
        await self.assertFindsClaims(list(reversed(claims)), order_by=["height"])

        await self.assertFindsClaims([claims[0]], height=height+1)
        await self.assertFindsClaims([claims[4]], height=height+5)
        await self.assertFindsClaims(claims[:1], height=f'<{height+2}', order_by=["^height"])
        await self.assertFindsClaims(claims[:2], height=f'<={height+2}', order_by=["^height"])
        await self.assertFindsClaims(claims[2:], height=f'>{height+2}', order_by=["^height"])
        await self.assertFindsClaims(claims[1:], height=f'>={height+2}', order_by=["^height"])

        await self.assertFindsClaims(claims, order_by=["^name"])

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
        await self.assertFindsClaims([], fee_currency='foo')

    async def test_search_by_channel(self):
        match = self.assertFindsClaims

        chan1_id = self.get_claim_id(await self.channel_create('@chan1'))
        chan2_id = self.get_claim_id(await self.channel_create('@chan2'))
        chan3_id = self.get_claim_id(await self.channel_create('@chan3'))

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
        channel = await self.channel_create()
        unknown = self.sout(tx)

        # claim_type
        await self.assertFindsClaims([image, video, octet, unknown], claim_type='stream')
        await self.assertFindsClaims([channel], claim_type='channel')

        # stream_type
        await self.assertFindsClaims([octet, unknown], stream_types=['binary'])
        await self.assertFindsClaims([video], stream_types=['video'])
        await self.assertFindsClaims([image], stream_types=['image'])
        await self.assertFindsClaims([image, video], stream_types=['video', 'image'])

        # stream_type
        await self.assertFindsClaims([octet, unknown], media_types=['application/octet-stream'])
        await self.assertFindsClaims([video], media_types=['video/mp4'])
        await self.assertFindsClaims([image], media_types=['image/png'])
        await self.assertFindsClaims([image, video], media_types=['video/mp4', 'image/png'])

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
        await self.assertFindsClaims([claim3], text='history')
        await self.assertFindsClaims([claim4], text='conspiracy')
        await self.assertFindsClaims([claim1, claim4, claim2, claim3], text='documentary')
        await self.assertFindsClaims([claim4, claim1, claim2, claim3], text='satoshi')


class ChannelCommands(CommandTestCase):

    async def test_create_channel_names(self):
        # claim new name
        await self.channel_create('@foo')
        self.assertItemCount(await self.daemon.jsonrpc_channel_list(), 1)
        await self.assertBalance(self.account, '8.991893')

        # fail to claim duplicate
        with self.assertRaisesRegex(Exception, "You already have a channel under the name '@foo'."):
            await self.channel_create('@foo')

        # fail to claim invalid name
        with self.assertRaisesRegex(Exception, "Channel names must start with '@' symbol."):
            await self.channel_create('foo')

        # nothing's changed after failed attempts
        self.assertItemCount(await self.daemon.jsonrpc_channel_list(), 1)
        await self.assertBalance(self.account, '8.991893')

        # succeed overriding duplicate restriction
        await self.channel_create('@foo', allow_duplicate_name=True)
        self.assertItemCount(await self.daemon.jsonrpc_channel_list(), 2)
        await self.assertBalance(self.account, '7.983786')

    async def test_channel_bids(self):
        # enough funds
        tx = await self.channel_create('@foo', '5.0')
        claim_id = self.get_claim_id(tx)
        self.assertItemCount(await self.daemon.jsonrpc_channel_list(), 1)
        await self.assertBalance(self.account, '4.991893')

        # bid preserved on update
        tx = await self.channel_update(claim_id)
        self.assertEqual(tx['outputs'][0]['amount'], '5.0')

        # bid changed on update
        tx = await self.channel_update(claim_id, bid='4.0')
        self.assertEqual(tx['outputs'][0]['amount'], '4.0')

        await self.assertBalance(self.account, '5.991447')

        # not enough funds
        with self.assertRaisesRegex(
                InsufficientFundsError, "Not enough funds to cover this transaction."):
            await self.channel_create('@foo2', '9.0')
        self.assertItemCount(await self.daemon.jsonrpc_channel_list(), 1)
        await self.assertBalance(self.account, '5.991447')

        # spend exactly amount available, no change
        tx = await self.channel_create('@foo3', '5.981266')
        await self.assertBalance(self.account, '0.0')
        self.assertEqual(len(tx['outputs']), 1)  # no change
        self.assertItemCount(await self.daemon.jsonrpc_channel_list(), 2)

    async def test_setting_channel_fields(self):
        values = {
            'title': "Cool Channel",
            'description': "Best channel on LBRY.",
            'thumbnail_url': "https://co.ol/thumbnail.png",
            'tags': ["cool", "awesome"],
            'languages': ["en-US"],
            'locations': ['US::Manchester'],
            'email': "human@email.com",
            'website_url': "https://co.ol",
            'cover_url': "https://co.ol/cover.png",
            'featured': ['cafe']
        }
        fixed_values = values.copy()
        fixed_values['thumbnail'] = {'url': fixed_values.pop('thumbnail_url')}
        fixed_values['locations'] = [{'country': 'US', 'city': 'Manchester'}]
        fixed_values['cover'] = {'url': fixed_values.pop('cover_url')}

        # create new channel with all fields set
        tx = await self.out(self.channel_create('@bigchannel', **values))
        channel = tx['outputs'][0]['value']
        self.assertEqual(channel, {
            'public_key': channel['public_key'],
            'public_key_id': channel['public_key_id'],
            **fixed_values
        })

        # create channel with nothing set
        tx = await self.out(self.channel_create('@lightchannel'))
        channel = tx['outputs'][0]['value']
        self.assertEqual(
            channel, {'public_key': channel['public_key'], 'public_key_id': channel['public_key_id']})

        # create channel with just a featured claim
        tx = await self.out(self.channel_create('@featurechannel', featured='beef'))
        txo = tx['outputs'][0]
        claim_id, channel = txo['claim_id'], txo['value']
        fixed_values['public_key'] = channel['public_key']
        fixed_values['public_key_id'] = channel['public_key_id']
        self.assertEqual(channel, {
            'public_key': fixed_values['public_key'],
            'public_key_id': fixed_values['public_key_id'],
            'featured': ['beef']
        })

        # update channel "@featurechannel" setting all fields
        tx = await self.out(self.channel_update(claim_id, **values))
        channel = tx['outputs'][0]['value']
        fixed_values['featured'].insert(0, 'beef')  # existing featured claim
        self.assertEqual(channel, fixed_values)

        # clearing and settings featured content
        tx = await self.out(self.channel_update(claim_id, featured='beefcafe', clear_featured=True))
        channel = tx['outputs'][0]['value']
        fixed_values['featured'] = ['beefcafe']
        self.assertEqual(channel, fixed_values)

        # reset signing key
        tx = await self.out(self.channel_update(claim_id, new_signing_key=True))
        channel = tx['outputs'][0]['value']
        self.assertNotEqual(channel['public_key'], fixed_values['public_key'])

        # replace mode (clears everything except public_key)
        tx = await self.out(self.channel_update(claim_id, replace=True, title='foo', email='new@email.com'))
        self.assertEqual(tx['outputs'][0]['value'], {
            'public_key': channel['public_key'],
            'public_key_id': channel['public_key_id'],
            'title': 'foo', 'email': 'new@email.com'}
        )

        # move channel to another account
        new_account = await self.out(self.daemon.jsonrpc_account_create('second account'))
        account2_id, account2 = new_account['id'], self.wallet.get_account_or_error(new_account['id'])

        # before moving
        self.assertItemCount(await self.daemon.jsonrpc_channel_list(), 3)
        self.assertItemCount(await self.daemon.jsonrpc_channel_list(account_id=account2_id), 0)

        other_address = await account2.receiving.get_or_create_usable_address()
        tx = await self.out(self.channel_update(claim_id, claim_address=other_address))

        # after moving
        self.assertItemCount(await self.daemon.jsonrpc_channel_list(), 3)
        self.assertItemCount(await self.daemon.jsonrpc_channel_list(account_id=self.account.id), 2)
        self.assertItemCount(await self.daemon.jsonrpc_channel_list(account_id=account2_id), 1)

    async def test_channel_export_import_before_sending_channel(self):
        # export
        tx = await self.channel_create('@foo', '1.0')
        claim_id = self.get_claim_id(tx)
        channel_private_key = (await self.account.get_channels())[0].private_key
        exported_data = await self.out(self.daemon.jsonrpc_channel_export(claim_id))

        # import
        daemon2 = await self.add_daemon()
        self.assertItemCount(await daemon2.jsonrpc_channel_list(), 0)
        await daemon2.jsonrpc_channel_import(exported_data)
        channels = (await daemon2.jsonrpc_channel_list())['items']
        self.assertEqual(1, len(channels))
        self.assertEqual(channel_private_key.to_string(), channels[0].private_key.to_string())

        # second wallet can't update until channel is sent to it
        with self.assertRaisesRegex(AssertionError, 'Cannot find private key for signing output.'):
            await daemon2.jsonrpc_channel_update(claim_id, bid='0.5')

        # now send the channel as well
        await self.channel_update(claim_id, claim_address=await daemon2.jsonrpc_address_unused())

        # second wallet should be able to update now
        await daemon2.jsonrpc_channel_update(claim_id, bid='0.5')

    async def test_channel_update_across_accounts(self):
        account2 = await self.daemon.jsonrpc_account_create('second account')
        channel = await self.out(self.channel_create('@spam', '1.0', account_id=account2.id))
        # channel not in account1
        with self.assertRaisesRegex(Exception, "Can't find the channel"):
            await self.channel_update(self.get_claim_id(channel), bid='2.0', account_id=self.account.id)
        # channel is in account2
        await self.channel_update(self.get_claim_id(channel), bid='2.0', account_id=account2.id)
        result = (await self.out(self.daemon.jsonrpc_channel_list()))['items']
        self.assertEqual(result[0]['amount'], '2.0')
        # check all accounts for channel
        await self.channel_update(self.get_claim_id(channel), bid='3.0')
        result = (await self.out(self.daemon.jsonrpc_channel_list()))['items']
        self.assertEqual(result[0]['amount'], '3.0')
        await self.channel_abandon(self.get_claim_id(channel))

    async def test_tag_normalization(self):
        tx1 = await self.channel_create('@abc', '1.0', tags=['aBc', ' ABC ', 'xYZ ', 'xyz'])
        claim_id = self.get_claim_id(tx1)
        self.assertCountEqual(tx1['outputs'][0]['value']['tags'], ['abc', 'xyz'])

        tx2 = await self.channel_update(claim_id, tags=[' pqr', 'PQr '])
        self.assertCountEqual(tx2['outputs'][0]['value']['tags'], ['abc', 'xyz', 'pqr'])

        tx3 = await self.channel_update(claim_id, tags=' pqr')
        self.assertCountEqual(tx3['outputs'][0]['value']['tags'], ['abc', 'xyz', 'pqr'])

        tx4 = await self.channel_update(claim_id, tags=[' pqr', 'PQr '], clear_tags=True)
        self.assertEqual(tx4['outputs'][0]['value']['tags'], ['pqr'])


class StreamCommands(ClaimTestCase):

    async def test_create_stream_names(self):
        # claim new name
        await self.stream_create('foo')
        self.assertItemCount(await self.daemon.jsonrpc_claim_list(), 1)
        await self.assertBalance(self.account, '8.993893')

        # fail to claim duplicate
        with self.assertRaisesRegex(
                Exception, "You already have a stream claim published under the name 'foo'."):
            await self.stream_create('foo')

        # fail claim starting with @
        with self.assertRaisesRegex(
                Exception, "Stream names cannot start with '@' symbol."):
            await self.stream_create('@foo')

        self.assertItemCount(await self.daemon.jsonrpc_claim_list(), 1)
        await self.assertBalance(self.account, '8.993893')

        # succeed overriding duplicate restriction
        await self.stream_create('foo', allow_duplicate_name=True)
        self.assertItemCount(await self.daemon.jsonrpc_claim_list(), 2)
        await self.assertBalance(self.account, '7.987786')

    async def test_stream_bids(self):
        # enough funds
        tx = await self.stream_create('foo', '2.0')
        claim_id = self.get_claim_id(tx)
        self.assertItemCount(await self.daemon.jsonrpc_claim_list(), 1)
        await self.assertBalance(self.account, '7.993893')

        # bid preserved on update
        tx = await self.stream_update(claim_id)
        self.assertEqual(tx['outputs'][0]['amount'], '2.0')

        # bid changed on update
        tx = await self.stream_update(claim_id, bid='3.0')
        self.assertEqual(tx['outputs'][0]['amount'], '3.0')

        await self.assertBalance(self.account, '6.993319')

        # not enough funds
        with self.assertRaisesRegex(
                InsufficientFundsError, "Not enough funds to cover this transaction."):
            await self.stream_create('foo2', '9.0')
        self.assertItemCount(await self.daemon.jsonrpc_claim_list(), 1)
        await self.assertBalance(self.account, '6.993319')

        # spend exactly amount available, no change
        tx = await self.stream_create('foo3', '6.98523')
        await self.assertBalance(self.account, '0.0')
        self.assertEqual(len(tx['outputs']), 1)  # no change
        self.assertItemCount(await self.daemon.jsonrpc_claim_list(), 2)

    async def test_stream_update_and_abandon_across_accounts(self):
        account2 = await self.daemon.jsonrpc_account_create('second account')
        stream = await self.out(self.stream_create('spam', '1.0', account_id=account2.id))
        # stream not in account1
        with self.assertRaisesRegex(Exception, "Can't find the stream"):
            await self.stream_update(self.get_claim_id(stream), bid='2.0', account_id=self.account.id)
        # stream is in account2
        await self.stream_update(self.get_claim_id(stream), bid='2.0', account_id=account2.id)
        result = (await self.out(self.daemon.jsonrpc_stream_list()))['items']
        self.assertEqual(result[0]['amount'], '2.0')
        # check all accounts for stream
        await self.stream_update(self.get_claim_id(stream), bid='3.0')
        result = (await self.out(self.daemon.jsonrpc_stream_list()))['items']
        self.assertEqual(result[0]['amount'], '3.0')
        await self.stream_abandon(self.get_claim_id(stream))

    async def test_publishing_checks_all_accounts_for_channel(self):
        account1_id, account1 = self.account.id, self.account
        new_account = await self.out(self.daemon.jsonrpc_account_create('second account'))
        account2_id, account2 = new_account['id'], self.wallet.get_account_or_error(new_account['id'])

        await self.out(self.channel_create('@spam', '1.0'))
        self.assertEqual('8.989893', (await self.daemon.jsonrpc_account_balance())['available'])

        result = await self.out(self.daemon.jsonrpc_account_send(
            '5.0', await self.daemon.jsonrpc_address_unused(account2_id)
        ))
        await self.confirm_tx(result['txid'])

        self.assertEqual('3.989769', (await self.daemon.jsonrpc_account_balance())['available'])
        self.assertEqual('5.0', (await self.daemon.jsonrpc_account_balance(account2_id))['available'])

        baz_tx = await self.out(self.channel_create('@baz', '1.0', account_id=account2_id))
        baz_id = self.get_claim_id(baz_tx)

        channels = await self.out(self.daemon.jsonrpc_channel_list(account1_id))
        self.assertItemCount(channels, 1)
        self.assertEqual(channels['items'][0]['name'], '@spam')
        self.assertEqual(channels, await self.out(self.daemon.jsonrpc_channel_list(account1_id)))

        channels = await self.out(self.daemon.jsonrpc_channel_list(account2_id))
        self.assertItemCount(channels, 1)
        self.assertEqual(channels['items'][0]['name'], '@baz')

        channels = await self.out(self.daemon.jsonrpc_channel_list())
        self.assertItemCount(channels, 2)
        self.assertEqual(channels['items'][0]['name'], '@baz')
        self.assertEqual(channels['items'][1]['name'], '@spam')

        # defaults to using all accounts to lookup channel
        await self.stream_create('hovercraft1', '0.1', channel_id=baz_id)
        self.assertEqual((await self.claim_search(name='hovercraft1'))[0]['signing_channel']['name'], '@baz')
        # lookup by channel_name in all accounts
        await self.stream_create('hovercraft2', '0.1', channel_name='@baz')
        self.assertEqual((await self.claim_search(name='hovercraft2'))[0]['signing_channel']['name'], '@baz')
        # uses only the specific accounts which contains the channel
        await self.stream_create('hovercraft3', '0.1', channel_id=baz_id, channel_account_id=[account2_id])
        self.assertEqual((await self.claim_search(name='hovercraft3'))[0]['signing_channel']['name'], '@baz')
        # lookup by channel_name in specific account
        await self.stream_create('hovercraft4', '0.1', channel_name='@baz', channel_account_id=[account2_id])
        self.assertEqual((await self.claim_search(name='hovercraft4'))[0]['signing_channel']['name'], '@baz')
        # fails when specifying account which does not contain channel
        with self.assertRaisesRegex(ValueError, "Couldn't find channel with channel_id"):
            await self.stream_create(
                'hovercraft5', '0.1', channel_id=baz_id, channel_account_id=[account1_id]
            )
        # fail with channel_name
        with self.assertRaisesRegex(ValueError, "Couldn't find channel with channel_name '@baz'"):
            await self.stream_create(
                'hovercraft5', '0.1', channel_name='@baz', channel_account_id=[account1_id]
            )

        # signing with channel works even if channel and certificate are in different accounts
        await self.channel_update(
            baz_id, account_id=account2_id,
            claim_address=await self.daemon.jsonrpc_address_unused(account1_id)
        )
        await self.stream_create(
            'hovercraft5', '0.1', channel_id=baz_id
        )

    async def test_preview_works_with_signed_streams(self):
        await self.out(self.channel_create('@spam', '1.0'))
        signed = await self.out(self.stream_create('bar', '1.0', channel_name='@spam', preview=True, confirm=False))
        self.assertTrue(signed['outputs'][0]['is_channel_signature_valid'])

    async def test_publish_updates_file_list(self):
        tx = await self.out(self.stream_create(title='created'))
        txo = tx['outputs'][0]
        claim_id, expected = txo['claim_id'], txo['value']
        files = await self.file_list()
        self.assertEqual(1, len(files))
        self.assertEqual(tx['txid'], files[0]['txid'])
        self.assertEqual(expected, files[0]['metadata'])

        # update with metadata-only changes
        tx = await self.out(self.stream_update(claim_id, title='update 1'))
        files = await self.file_list()
        expected['title'] = 'update 1'
        self.assertEqual(1, len(files))
        self.assertEqual(tx['txid'], files[0]['txid'])
        self.assertEqual(expected, files[0]['metadata'])

        # update with new data
        tx = await self.out(self.stream_update(claim_id, title='update 2', data=b'updated data'))
        expected = tx['outputs'][0]['value']
        files = await self.file_list()
        self.assertEqual(1, len(files))
        self.assertEqual(tx['txid'], files[0]['txid'])
        self.assertEqual(expected, files[0]['metadata'])

    async def test_setting_stream_fields(self):
        values = {
            'title': "Cool Content",
            'description': "Best content on LBRY.",
            'thumbnail_url': "https://co.ol/thumbnail.png",
            'tags': ["cool", "awesome"],
            'languages': ["en"],
            'locations': ['US:NH:Manchester:03101:42.990605:-71.460989'],

            'author': "Jules Verne",
            'license': 'Public Domain',
            'license_url': "https://co.ol/license",
            'release_time': 123456,

            'fee_currency': 'usd',
            'fee_amount': '2.99',
            'fee_address': 'mmCsWAiXMUVecFQ3fVzUwvpT9XFMXno2Ca',
        }
        fixed_values = values.copy()
        fixed_values['locations'] = [{
            'country': 'US',
            'state': 'NH',
            'city': 'Manchester',
            'code': '03101',
            'latitude': '42.990605',
            'longitude': '-71.460989'
        }]
        fixed_values['thumbnail'] = {'url': fixed_values.pop('thumbnail_url')}
        fixed_values['release_time'] = str(values['release_time'])
        fixed_values['stream_type'] = 'binary'
        fixed_values['source'] = {
            'hash': '56bf5dbae43f77a63d075b0f2ae9c7c3e3098db93779c7f9840da0f4db9c2f8c8454f4edd1373e2b64ee2e68350d916e',
            'media_type': 'application/octet-stream',
            'size': '3'
        }
        fixed_values['fee'] = {
            'address': fixed_values.pop('fee_address'),
            'amount': fixed_values.pop('fee_amount'),
            'currency': fixed_values.pop('fee_currency').upper()
        }

        # create new stream with all fields set
        tx = await self.out(self.stream_create('big', **values))
        stream = tx['outputs'][0]['value']
        fixed_values['source']['name'] = stream['source']['name']
        fixed_values['source']['sd_hash'] = stream['source']['sd_hash']
        self.assertEqual(stream, fixed_values)

        # create stream with nothing set
        tx = await self.out(self.stream_create('light'))
        stream = tx['outputs'][0]['value']
        self.assertEqual(
            stream, {
                'stream_type': 'binary',
                'source': {
                    'size': '3',
                    'media_type': 'application/octet-stream',
                    'name': stream['source']['name'],
                    'hash': '56bf5dbae43f77a63d075b0f2ae9c7c3e3098db93779c7f9840da0f4db9c2f8c8454f4edd1373e2b64ee2e68350d916e',
                    'sd_hash': stream['source']['sd_hash']
                },
            }
        )

        # create stream with just some tags, langs and locations
        tx = await self.out(self.stream_create('updated', tags='blah', languages='uk', locations='UA::Kyiv'))
        txo = tx['outputs'][0]
        claim_id, stream = txo['claim_id'], txo['value']
        fixed_values['source']['name'] = stream['source']['name']
        fixed_values['source']['sd_hash'] = stream['source']['sd_hash']
        self.assertEqual(
            stream, {
                'stream_type': 'binary',
                'source': {
                    'size': '3',
                    'media_type': 'application/octet-stream',
                    'name': fixed_values['source']['name'],
                    'hash': '56bf5dbae43f77a63d075b0f2ae9c7c3e3098db93779c7f9840da0f4db9c2f8c8454f4edd1373e2b64ee2e68350d916e',
                    'sd_hash': fixed_values['source']['sd_hash'],
                },
                'tags': ['blah'],
                'languages': ['uk'],
                'locations': [{'country': 'UA', 'city': 'Kyiv'}]
            }
        )

        # update stream setting all fields, 'source' doesn't change
        tx = await self.out(self.stream_update(claim_id, **values))
        stream = tx['outputs'][0]['value']
        fixed_values['tags'].insert(0, 'blah')  # existing tag
        fixed_values['languages'].insert(0, 'uk')  # existing language
        fixed_values['locations'].insert(0, {'country': 'UA', 'city': 'Kyiv'})  # existing location
        self.assertEqual(stream, fixed_values)

        # clearing and settings tags, languages and locations
        tx = await self.out(self.stream_update(
            claim_id, tags='single', clear_tags=True,
            languages='pt', clear_languages=True,
            locations='BR', clear_locations=True,
        ))
        txo = tx['outputs'][0]
        fixed_values['tags'] = ['single']
        fixed_values['languages'] = ['pt']
        fixed_values['locations'] = [{'country': 'BR'}]
        self.assertEqual(txo['value'], fixed_values)

        # modifying hash/size/name
        fixed_values['source']['name'] = 'changed_name'
        fixed_values['source']['hash'] = 'cafebeef'
        fixed_values['source']['size'] = '42'
        tx = await self.out(self.stream_update(
            claim_id, file_name='changed_name', file_hash='cafebeef', file_size=42
        ))
        self.assertEqual(tx['outputs'][0]['value'], fixed_values)

        # stream_update re-signs with the same channel
        channel_id = self.get_claim_id(await self.channel_create('@chan'))
        tx = await self.stream_update(claim_id, channel_id=channel_id)
        self.assertEqual(tx['outputs'][0]['signing_channel']['name'], '@chan')
        tx = await self.stream_update(claim_id, title='channel re-signs')
        self.assertEqual(tx['outputs'][0]['value']['title'], 'channel re-signs')
        self.assertEqual(tx['outputs'][0]['signing_channel']['name'], '@chan')

        # send claim to someone else
        new_account = await self.out(self.daemon.jsonrpc_account_create('second account'))
        account2_id, account2 = new_account['id'], self.wallet.get_account_or_error(new_account['id'])

        # before sending
        self.assertItemCount(await self.daemon.jsonrpc_claim_list(), 4)
        self.assertItemCount(await self.daemon.jsonrpc_claim_list(account_id=self.account.id), 4)
        self.assertItemCount(await self.daemon.jsonrpc_claim_list(account_id=account2_id), 0)

        other_address = await account2.receiving.get_or_create_usable_address()
        tx = await self.out(self.stream_update(claim_id, claim_address=other_address))

        # after sending
        self.assertItemCount(await self.daemon.jsonrpc_claim_list(), 4)
        self.assertItemCount(await self.daemon.jsonrpc_claim_list(account_id=self.account.id), 3)
        self.assertItemCount(await self.daemon.jsonrpc_claim_list(account_id=account2_id), 1)

    async def test_setting_fee_fields(self):
        tx = await self.out(self.stream_create('paid-stream'))
        txo = tx['outputs'][0]
        claim_id, stream = txo['claim_id'], txo['value']
        fee_address = 'mmCsWAiXMUVecFQ3fVzUwvpT9XFMXno2Ca'

        self.assertNotIn('fee', stream)

        # --replace=false
        # validation
        with self.assertRaisesRegex(Exception, 'please specify a fee currency'):
            await self.stream_update(claim_id, fee_amount='0.1')
        with self.assertRaisesRegex(Exception, 'unknown currency provided: foo'):
            await self.stream_update(claim_id, fee_amount='0.1', fee_currency="foo")
        with self.assertRaisesRegex(Exception, 'please specify a fee amount'):
            await self.stream_update(claim_id, fee_currency='usd')
        with self.assertRaisesRegex(Exception, 'please specify a fee amount'):
            await self.stream_update(claim_id, fee_address=fee_address)
        # set just amount and currency with default address
        tx = await self.stream_update(
            claim_id, fee_amount='0.99', fee_currency='lbc'
        )
        self.assertEqual(
            tx['outputs'][0]['value']['fee'],
            {'amount': '0.99', 'currency': 'LBC', 'address': txo['address']}
        )
        # set all fee fields
        tx = await self.stream_update(
            claim_id, fee_amount='0.1', fee_currency='usd', fee_address=fee_address
        )
        self.assertEqual(
            tx['outputs'][0]['value']['fee'],
            {'amount': '0.1', 'currency': 'USD', 'address': fee_address}
        )
        # change just address
        tx = await self.stream_update(claim_id, fee_address=txo['address'])
        self.assertEqual(
            tx['outputs'][0]['value']['fee'],
            {'amount': '0.1', 'currency': 'USD', 'address': txo['address']}
        )
        # change just amount (does not reset fee_address)
        tx = await self.stream_update(claim_id, fee_amount='0.2')
        self.assertEqual(
            tx['outputs'][0]['value']['fee'],
            {'amount': '0.2', 'currency': 'USD', 'address': txo['address']}
        )
        # changing currency without an amount is never allowed, even if previous amount exists
        with self.assertRaises(Exception, msg='In order to set a fee currency, please specify a fee amount'):
            await self.stream_update(claim_id, fee_currency='usd')
        # clearing fee
        tx = await self.out(self.stream_update(claim_id, clear_fee=True))
        self.assertNotIn('fee', tx['outputs'][0]['value'])

        # --replace=true
        # set just amount and currency with default address
        tx = await self.stream_update(
            claim_id, fee_amount='0.99', fee_currency='lbc', replace=True
        )
        self.assertEqual(
            tx['outputs'][0]['value']['fee'],
            {'amount': '0.99', 'currency': 'LBC', 'address': txo['address']}
        )
        # set all fee fields
        tx = await self.stream_update(
            claim_id, fee_amount='0.1', fee_currency='usd', fee_address=fee_address, replace=True
        )
        self.assertEqual(
            tx['outputs'][0]['value']['fee'],
            {'amount': '0.1', 'currency': 'USD', 'address': fee_address}
        )
        # validation
        with self.assertRaisesRegex(Exception, 'please specify a fee currency'):
            await self.stream_update(claim_id, fee_amount='0.1', replace=True)
        with self.assertRaisesRegex(Exception, 'unknown currency provided: foo'):
            await self.stream_update(claim_id, fee_amount='0.1', fee_currency="foo", replace=True)
        with self.assertRaisesRegex(Exception, 'please specify a fee amount'):
            await self.stream_update(claim_id, fee_currency='usd', replace=True)
        with self.assertRaisesRegex(Exception, 'please specify a fee amount'):
            await self.stream_update(claim_id, fee_address=fee_address, replace=True)

    async def test_automatic_type_and_metadata_detection_for_image(self):
        txo = (await self.stream_create('blank-image', data=self.image_data, suffix='.png'))['outputs'][0]
        self.assertEqual(
            txo['value'], {
                'source': {
                    'size': '99',
                    'name': txo['value']['source']['name'],
                    'media_type': 'image/png',
                    'hash': '6c7df435d412c603390f593ef658c199817c7830ba3f16b7eadd8f99fa50e85dbd0d2b3dc61eadc33fe096e3872d1545',
                    'sd_hash': txo['value']['source']['sd_hash'],
                },
                'stream_type': 'image',
                'image': {
                    'width': 5,
                    'height': 7
                }
            }
        )

    async def test_automatic_type_and_metadata_detection_for_video(self):
        txo = (await self.stream_create('chrome', file_path=self.video_file_name))['outputs'][0]
        self.assertEqual(
            txo['value'], {
                'source': {
                    'size': '2299653',
                    'name': 'ForBiggerEscapes.mp4',
                    'media_type': 'video/mp4',
                    'hash': '5f6811c83c1616df06f10bf5309ca61edb5ff949a9c1212ce784602d837bfdfc1c3db1e0580ef7bd1dadde41d8acf315',
                    'sd_hash': txo['value']['source']['sd_hash'],
                },
                'stream_type': 'video',
                'video': {
                    'width': 1280,
                    'height': 720,
                    'duration': 15
                }
            }
        )

    async def test_overriding_automatic_metadata_detection(self):
        tx = await self.out(
            self.daemon.jsonrpc_stream_create(
                'chrome', '1.0', file_path=self.video_file_name, width=99, height=88, duration=9
            )
        )
        txo = tx['outputs'][0]
        self.assertEqual(
            txo['value'], {
                'source': {
                    'size': '2299653',
                    'name': 'ForBiggerEscapes.mp4',
                    'media_type': 'video/mp4',
                    'hash': '5f6811c83c1616df06f10bf5309ca61edb5ff949a9c1212ce784602d837bfdfc1c3db1e0580ef7bd1dadde41d8acf315',
                    'sd_hash': txo['value']['source']['sd_hash'],
                },
                'stream_type': 'video',
                'video': {
                    'width': 99,
                    'height': 88,
                    'duration': 9
                }
            }
        )

    async def test_update_file_type(self):
        video_txo = (await self.stream_create('chrome', file_path=self.video_file_name))['outputs'][0]
        self.assertSetEqual(set(video_txo['value']), {'source', 'stream_type', 'video'})
        self.assertEqual(video_txo['value']['stream_type'], 'video')
        self.assertEqual(video_txo['value']['source']['media_type'], 'video/mp4')
        self.assertEqual(
            video_txo['value']['video'], {
                'duration': 15,
                'height': 720,
                'width': 1280
            }
        )
        claim_id = video_txo['claim_id']

        binary_txo = (await self.stream_update(claim_id, data=b'hi!'))['outputs'][0]
        self.assertEqual(binary_txo['value']['stream_type'], 'binary')
        self.assertEqual(binary_txo['value']['source']['media_type'], 'application/octet-stream')
        self.assertSetEqual(set(binary_txo['value']), {'source', 'stream_type'})

        image_txo = (await self.stream_update(claim_id, data=self.image_data, suffix='.png'))['outputs'][0]
        self.assertSetEqual(set(image_txo['value']), {'source', 'stream_type', 'image'})
        self.assertEqual(image_txo['value']['stream_type'], 'image')
        self.assertEqual(image_txo['value']['source']['media_type'], 'image/png')
        self.assertEqual(image_txo['value']['image'], {'height': 7, 'width': 5})

    async def test_replace_mode_preserves_source_and_type(self):
        expected = {
            'tags': ['blah'],
            'languages': ['uk'],
            'locations': [{'country': 'UA', 'city': 'Kyiv'}],
            'source': {
                'size': '2299653',
                'name': 'ForBiggerEscapes.mp4',
                'media_type': 'video/mp4',
                'hash': '5f6811c83c1616df06f10bf5309ca61edb5ff949a9c1212ce784602d837bfdfc1c3db1e0580ef7bd1dadde41d8acf315',
            },
            'stream_type': 'video',
            'video': {
                'width': 1280,
                'height': 720,
                'duration': 15
            }
        }
        channel = await self.channel_create('@chan')
        tx = await self.out(self.daemon.jsonrpc_stream_create(
            'chrome', '1.0', file_path=self.video_file_name,
            tags='blah', languages='uk', locations='UA::Kyiv',
            channel_id=self.get_claim_id(channel)
        ))
        await self.on_transaction_dict(tx)
        txo = tx['outputs'][0]
        expected['source']['sd_hash'] = txo['value']['source']['sd_hash']
        self.assertEqual(txo['value'], expected)
        self.assertEqual(txo['signing_channel']['name'], '@chan')
        tx = await self.out(self.daemon.jsonrpc_stream_update(
            txo['claim_id'], title='new title', replace=True
        ))
        txo = tx['outputs'][0]
        expected['title'] = 'new title'
        del expected['tags']
        del expected['languages']
        del expected['locations']
        self.assertEqual(txo['value'], expected)
        self.assertNotIn('signing_channel', txo)

    async def test_create_update_and_abandon_stream(self):
        await self.assertBalance(self.account, '10.0')

        tx = await self.stream_create(bid='2.5')  # creates new claim
        claim_id = self.get_claim_id(tx)
        txs = (await self.out(self.daemon.jsonrpc_transaction_list()))['items']
        self.assertEqual(len(txs[0]['claim_info']), 1)
        self.assertEqual(txs[0]['confirmations'], 1)
        self.assertEqual(txs[0]['claim_info'][0]['balance_delta'], '-2.5')
        self.assertEqual(txs[0]['claim_info'][0]['claim_id'], claim_id)
        self.assertEqual(txs[0]['value'], '0.0')
        self.assertEqual(txs[0]['fee'], '-0.020107')
        await self.assertBalance(self.account, '7.479893')
        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 1)

        await self.daemon.jsonrpc_file_delete(delete_all=True)
        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 0)

        await self.stream_update(claim_id, bid='1.0')  # updates previous claim
        txs = (await self.out(self.daemon.jsonrpc_transaction_list()))['items']
        self.assertEqual(len(txs[0]['update_info']), 1)
        self.assertEqual(txs[0]['update_info'][0]['balance_delta'], '1.5')
        self.assertEqual(txs[0]['update_info'][0]['claim_id'], claim_id)
        self.assertEqual(txs[0]['value'], '0.0')
        self.assertEqual(txs[0]['fee'], '-0.0002165')
        await self.assertBalance(self.account, '8.9796765')

        await self.stream_abandon(claim_id)
        txs = (await self.out(self.daemon.jsonrpc_transaction_list()))['items']
        self.assertEqual(len(txs[0]['abandon_info']), 1)
        self.assertEqual(txs[0]['abandon_info'][0]['balance_delta'], '1.0')
        self.assertEqual(txs[0]['abandon_info'][0]['claim_id'], claim_id)
        self.assertEqual(txs[0]['value'], '0.0')
        self.assertEqual(txs[0]['fee'], '-0.000107')
        await self.assertBalance(self.account, '9.9795695')

    async def test_abandoning_stream_at_loss(self):
        await self.assertBalance(self.account, '10.0')
        tx = await self.stream_create(bid='0.0001')
        await self.assertBalance(self.account, '9.979793')
        await self.stream_abandon(self.get_claim_id(tx))
        await self.assertBalance(self.account, '9.97968399')

    async def test_publish(self):

        # errors on missing arguments to create a stream
        with self.assertRaisesRegex(Exception, "'bid' is a required argument for new publishes."):
            await self.daemon.jsonrpc_publish('foo')

        with self.assertRaisesRegex(Exception, "'file_path' is a required argument for new publishes."):
            await self.daemon.jsonrpc_publish('foo', bid='1.0')

        # successfully create stream
        with tempfile.NamedTemporaryFile() as file:
            file.write(b'hi')
            file.flush()
            tx1 = await self.publish('foo', bid='1.0', file_path=file.name)

        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 1)

        # doesn't error on missing arguments when doing an update stream
        tx2 = await self.publish('foo', tags='updated')

        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 1)
        self.assertEqual(self.get_claim_id(tx1), self.get_claim_id(tx2))

        # update conflict with two claims of the same name
        tx3 = await self.stream_create('foo', allow_duplicate_name=True)
        with self.assertRaisesRegex(Exception, "There are 2 claims for 'foo'"):
            await self.daemon.jsonrpc_publish('foo')

        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 2)
        # abandon duplicate stream
        await self.stream_abandon(self.get_claim_id(tx3))

        # publish to a channel
        await self.channel_create('@abc')
        tx3 = await self.publish('foo', channel_name='@abc')
        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 2)
        r = await self.resolve('lbry://@abc/foo')
        self.assertEqual(
            r['lbry://@abc/foo']['claim_id'],
            self.get_claim_id(tx3)
        )

        # publishing again clears channel
        tx4 = await self.publish('foo', languages='uk-UA', tags=['Anime', 'anime '])
        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 2)
        r = await self.resolve('lbry://foo')
        claim = r['lbry://foo']
        self.assertEqual(claim['txid'], tx4['outputs'][0]['txid'])
        self.assertNotIn('signing_channel', claim)
        self.assertEqual(claim['value']['languages'], ['uk-UA'])
        self.assertEqual(claim['value']['tags'], ['anime'])


class SupportCommands(CommandTestCase):

    async def test_regular_supports_and_tip_supports(self):
        wallet2 = await self.daemon.jsonrpc_wallet_create('wallet2', create_account=True)
        account2 = wallet2.accounts[0]

        # send account2 5 LBC out of the 10 LBC in account1
        result = await self.out(self.daemon.jsonrpc_account_send(
            '5.0', await self.daemon.jsonrpc_address_unused(wallet_id='wallet2')
        ))
        await self.on_transaction_dict(result)

        # account1 and account2 balances:
        await self.assertBalance(self.account, '4.999876')
        await self.assertBalance(account2,     '5.0')

        # create the claim we'll be tipping and supporting
        claim_id = self.get_claim_id(await self.stream_create())

        # account1 and account2 balances:
        await self.assertBalance(self.account, '3.979769')
        await self.assertBalance(account2,     '5.0')

        # send a tip to the claim using account2
        tip = await self.out(
            self.daemon.jsonrpc_support_create(
                claim_id, '1.0', True, account2.id, 'wallet2', funding_account_ids=[account2.id])
        )
        await self.confirm_tx(tip['txid'])

        # tips don't affect balance so account1 balance is same but account2 balance went down
        await self.assertBalance(self.account, '3.979769')
        await self.assertBalance(account2,     '3.9998585')

        # verify that the incoming tip is marked correctly as is_tip=True in account1
        txs = (await self.out(self.daemon.jsonrpc_transaction_list(self.account.id)))['items']
        self.assertEqual(len(txs[0]['support_info']), 1)
        self.assertEqual(txs[0]['support_info'][0]['balance_delta'], '1.0')
        self.assertEqual(txs[0]['support_info'][0]['claim_id'], claim_id)
        self.assertTrue(txs[0]['support_info'][0]['is_tip'])
        self.assertEqual(txs[0]['value'], '1.0')
        self.assertEqual(txs[0]['fee'], '0.0')

        # verify that the outgoing tip is marked correctly as is_tip=True in account2
        txs2 = (await self.out(
            self.daemon.jsonrpc_transaction_list(wallet_id='wallet2', account_id=account2.id)
        ))['items']
        self.assertEqual(len(txs2[0]['support_info']), 1)
        self.assertEqual(txs2[0]['support_info'][0]['balance_delta'], '-1.0')
        self.assertEqual(txs2[0]['support_info'][0]['claim_id'], claim_id)
        self.assertTrue(txs2[0]['support_info'][0]['is_tip'])
        self.assertEqual(txs2[0]['value'], '-1.0')
        self.assertEqual(txs2[0]['fee'], '-0.0001415')

        # send a support to the claim using account2
        support = await self.out(
            self.daemon.jsonrpc_support_create(
                claim_id, '2.0', False, account2.id, 'wallet2', funding_account_ids=[account2.id])
        )
        await self.confirm_tx(support['txid'])

        # account2 balance went down ~2
        await self.assertBalance(self.account, '3.979769')
        await self.assertBalance(account2,     '1.999717')

        # verify that the outgoing support is marked correctly as is_tip=False in account2
        txs2 = (await self.out(self.daemon.jsonrpc_transaction_list(wallet_id='wallet2')))['items']
        self.assertEqual(len(txs2[0]['support_info']), 1)
        self.assertEqual(txs2[0]['support_info'][0]['balance_delta'], '-2.0')
        self.assertEqual(txs2[0]['support_info'][0]['claim_id'], claim_id)
        self.assertFalse(txs2[0]['support_info'][0]['is_tip'])
        self.assertEqual(txs2[0]['value'], '0.0')
        self.assertEqual(txs2[0]['fee'], '-0.0001415')
