import re
import time
import typing
from math import ceil
import secrets

from aiohttp import web

from lbry.testcase import CommandTestCase


class MockedCommentServer:

    ERRORS = {
        'INVALID_PARAMS': {'code': -32602, 'message': 'Invalid parameters'},
        'INTERNAL': {'code': -32603, 'message': 'An internal error'},
        'UNKNOWN': {'code': -1, 'message': 'An unknown or very miscellaneous error'},
        'INVALID_METHOD': {'code': -32604, 'message': 'The Requested method does not exist'}
    }

    COMMENT_SCHEMA = {
        'comment': None,
        'comment_id': None,
        'claim_id': None,
        'parent_id': None,
        'channel_name': None,
        'channel_id': None,
        'signature': None,
        'signing_ts': None,
        'timestamp': None,
        'channel_url': None,
        'is_hidden': False,
        'is_pinned': False,
    }

    REACT_SCHEMA = {
        'react_id': None,
        'comment_id': None,
        'reaction_type': None,
        'timestamp': None,
        'signature': None,
        'channel_id': None,
        'channel_name': None
    }

    def __init__(self, port=2903):
        self.port = port
        self.app = web.Application(debug=True)
        self.app.add_routes([web.post('/api', self.api)])
        self.runner = None
        self.server = None
        self.comments = []
        self.reacts = {}
        self.index = 0
        self.react_id = 0

    @classmethod
    def _create_comment(cls, **kwargs):
        schema = cls.COMMENT_SCHEMA.copy()
        schema.update(**kwargs)
        return schema

    @classmethod
    def _react(cls, **kwargs):
        schema = cls.REACT_SCHEMA.copy()
        schema.update(**kwargs)
        return schema

    def create_comment(self, claim_id=None, parent_id=None, channel_name=None, channel_id=None, **kwargs):
        comment_id = secrets.token_hex(64)
        channel_url = 'lbry://' + channel_name + '#' + channel_id if channel_id else None

        if parent_id:
            parent_comment = list(filter(lambda c: c['comment_id'] == parent_id, self.comments))[0]
            claim_id = parent_comment['claim_id']

        comment = self._create_comment(
            comment_id=comment_id,
            channel_name=channel_name,
            channel_id=channel_id,
            channel_url=channel_url,
            timestamp=str(int(time.time())),
            claim_id=claim_id,
            parent_id=parent_id,
            **kwargs
        )
        self.comments.append(comment)
        return self.clean(comment)

    def abandon_comment(self, comment_id: str, channel_id: str, **kwargs):
        deleted = False
        index = self.get_index_for_comment_id(comment_id)
        try:
            if index >= 0:
                self.comments.pop(index)
                deleted = True
        finally:
            return {
                str(comment_id): {
                    'abandoned': deleted
                }
            }

    def edit_comment(self, comment_id: str, comment: str, channel_id: str,
                       channel_name: str, signature: str, signing_ts: str) -> dict:
        edited = False
        if self.credentials_are_valid(channel_id, channel_name, signature, signing_ts) \
                and self.is_valid_body(comment):
            index = self.get_index_for_comment_id(comment_id)
            if self.comments[index]['channel_id'] == channel_id:
                self.comments[index].update({
                    'comment': comment,
                    'signature': signature,
                    'signing_ts': signing_ts
                })
                edited = True

        return self.comments[index] if edited else None

    def hide_comment(self, comment_id: str, signing_ts: str, signature: str):
        if self.is_signable(signature, signing_ts):
            self.comments[self.get_index_for_comment_id(comment_id)]['is_hidden'] = True
            return True
        return False

    def pin_comment(
            self,
            comment_id: str,
            channel_name: str, channel_id: str, remove: bool,
            signing_ts: str, signature: str
    ):
        index = self.get_index_for_comment_id(comment_id)
        if self.is_signable(signature, signing_ts):
            if remove:
                self.comments[index]['is_pinned'] = False
            else:
                self.comments[index]['is_pinned'] = True
            return self.comments[index]
        return False

    def hide_comments(self, pieces: list):
        hidden = []
        for p in pieces:
            if self.hide_comment(**p):
                hidden.append(p['comment_id'])

        comment_ids = {c['comment_id'] for c in pieces}
        return {
            'hidden': hidden,
            'visible': list(comment_ids - set(hidden))
        }

    def get_claim_comments(self, claim_id, hidden=False, visible=False, page=1, page_size=50,**kwargs):
        comments = list(filter(lambda c: c['claim_id'] == claim_id, self.comments))
        if hidden ^ visible:
            comments = list(filter(lambda c: c['is_hidden'] == hidden, comments))

        return {
            'page': page,
            'page_size': page_size,
            'total_pages': ceil(len(comments)/page_size),
            'total_items': len(comments),
            'items': [self.clean(c) for c in (comments[::-1])[(page - 1) * page_size: page * page_size]],
            'has_hidden_comments': bool(list(filter(lambda x: x['is_hidden'], self.comments)))
        }

    def get_comment_channel_by_id(self, comment_id: str, **kwargs):
        comment = self.comments[self.get_index_for_comment_id(comment_id)]
        return {
            'channel_id': comment['channel_id'],
            'channel_name': comment['channel_name'],
        }

    def get_comments_by_id(self, comment_ids: list):
        comments = [self.comments[self.get_index_for_comment_id(cid)] for cid in comment_ids]
        return {
            'page': 1,
            'page_size': len(comment_ids),
            'total_pages': 1,
            'items': comments,
            'has_hidden_comments': bool({c for c in comments if c['is_hidden']})
        }

    def react(
            self,
            comment_ids=None,
            channel_name=None,
            channel_id=None,
            remove=None,
            clear_types=None,
            type=None,
            signing_ts=None,
            **kwargs
    ):
        comment_batch = comment_ids.split(',')
        for item in comment_batch:
            react_id = self.react_id
            c_id = item.strip()
            reacts_for_comment_id = [r for r in list(self.reacts.values()) if r['comment_id'] == c_id]
            channels_reacts_for_comment_id = [r for r in reacts_for_comment_id if r['channel_id'] == channel_id]
            if remove:
                matching_react = None
                for reaction in channels_reacts_for_comment_id:
                    if reaction['reaction_type'] == type:
                        matching_react = reaction
                        break
                if matching_react:
                    self.reacts.pop(int(matching_react['react_id']), None)
            else:
                if clear_types:
                    for r_type in clear_types.split(','):
                        for reaction in channels_reacts_for_comment_id:
                            if reaction['reaction_type'] == r_type:
                                x = self.reacts.pop(int(reaction['react_id']), None)
                react = self._react(
                    react_id=str(react_id),
                    comment_id=str(c_id),
                    channel_name=channel_name,
                    channel_id=channel_id,
                    reaction_type=type,
                    timestamp=str(int(time.time())),
                    **kwargs
                )
                self.reacts[self.react_id] = react
                self.react_id += 1
                self.clean(react)
        return True

    def list_reacts(self, comment_ids, channel_id, channel_name, types=None, **kwargs):
        all_types = list(set([r['reaction_type'] for r in list(self.reacts.values())]))
        comment_id_list = comment_ids.split(',')
        # _reacts: {'a1': {'like': 0, 'dislike': 0}, 'a2': {'like': 0, 'dislike': 0}}
        own_reacts = {}
        other_reacts = {}

        # for each comment_id
            # add comment_id: {} to own_reacts and other_reacts
            # for each react in own_reacts
            # for each react in other_reacts
        for cid in comment_id_list:
            own_reacts[cid] = {}
            other_reacts[cid] = {}

            for r_type in all_types:
                own_reacts[cid][r_type] = 0
                other_reacts[cid][r_type] = 0
            # process that comment ids reactions for own and other categories
            reacts_for_comment = list(filter(lambda c: c['comment_id'] == cid, list(self.reacts.values())))
            if types:
                reacts_for_comment = list(filter(lambda c: c['reaction_type'] in types.split(','), reacts_for_comment))
            own_reacts_for_comment = list(filter(lambda c: c['channel_id'] == channel_id, reacts_for_comment))
            other_reacts_for_comment = list(filter(lambda c: c['channel_id'] != channel_id, reacts_for_comment))

            if own_reacts_for_comment:
                for react in own_reacts_for_comment:
                    own_reacts[cid][react['reaction_type']] += 1
            if other_reacts_for_comment:
                for react in other_reacts_for_comment:
                    other_reacts[cid][react['reaction_type']] += 1

        return {
            'my_reactions': own_reacts,
            'others_reactions': other_reacts,
        }

    methods = {
        'comment.List': get_claim_comments,
        'get_comments_by_id': get_comments_by_id,
        'comment.Create': create_comment,
        'comment.Abandon': abandon_comment,
        'comment.GetChannelFromCommentID': get_comment_channel_by_id,
        'comment.Hide': hide_comments,
        'comment.Pin': pin_comment,
        'comment.Edit': edit_comment,
        'reaction.React': react,
        'reaction.List': list_reacts,
    }

    def process_json(self, body) -> dict:
        response = {'jsonrpc': '2.0', 'id': body['id']}
        error = None
        try:
            if body['method'] in self.methods:
                params: dict = body.get('params', {})
                result = self.methods[body['method']](self, **params)
                response['result'] = result
            else:
                response['error'] = self.ERRORS['INVALID_METHOD']

        except (ValueError, TypeError) as err:
            error = err
            response['error'] = self.ERRORS['INVALID_PARAMS']

        except Exception as err:
            error = err
            response['error'] = self.ERRORS['UNKNOWN']

        finally:
            if 'error' in response:
                response['error'].update({'exception': f'{type(error).__name__}: {error}'})

        return response

    async def start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.server = web.TCPSite(self.runner, 'localhost', self.port)
        await self.server.start()

    async def stop(self):
        await self.runner.shutdown()
        await self.runner.cleanup()

    async def api(self, request):
        body = await request.json()
        if type(body) is list or type(body) is dict:
            if type(body) is list:
                response = [self.process_json(part) for part in body]
            else:
                response = self.process_json(body)
            return web.json_response(response)
        else:
            raise TypeError('invalid type passed')

    @staticmethod
    def clean(d: dict):
        return {k: v for k, v in d.items() if v or isinstance(v, bool)}

    @staticmethod
    def is_valid_body(comment) -> bool:
        return 0 < len(comment) <= 2000

    def is_valid_comment_id(self, comment_id: typing.Union[int, str]) -> bool:
        if isinstance(comment_id, str):
            return True
        return False

    def get_comment_for_id(self, cid: str) -> dict:
        return list(filter(lambda c: c['comment_id'] == cid, self.comments))[0]

    def get_index_for_comment_id(self, value: str):
        for i, dic in enumerate(self.comments):
            if dic['comment_id'] == value:
                return i
        return -1

    @staticmethod
    def claim_id_is_valid(claim_id: str) -> bool:
        return re.fullmatch('([a-z0-9]{40}|[A-Z0-9]{40})', claim_id) is not None

    @staticmethod
    def channel_name_is_valid(channel_name: str) -> bool:
        return re.fullmatch(
            '@(?:(?![\x00-\x08\x0b\x0c\x0e-\x1f\x23-\x26'
            '\x2f\x3a\x3d\x3f-\x40\uFFFE-\U0000FFFF]).){1,255}',
            channel_name
        ) is not None

    @staticmethod
    def is_valid_channel(channel_id: str, channel_name: str) -> bool:
        return channel_id and MockedCommentServer.claim_id_is_valid(channel_id) and \
               channel_name and MockedCommentServer.channel_name_is_valid(channel_name)

    @staticmethod
    def is_signable(signature: str, signing_ts: str) -> bool:
        return signing_ts and signing_ts.isalnum() and \
               signature and len(signature) == 128

    @staticmethod
    def credentials_are_valid(channel_id: str = None, channel_name: str = None,
                              signature: str = None, signing_ts: str = None) -> bool:
        if channel_id or channel_name or signature or signing_ts:
            try:
                assert channel_id and channel_name and signature and signing_ts
                assert MockedCommentServer.is_valid_channel(channel_id, channel_name)
                assert MockedCommentServer.is_signable(signature, signing_ts)

            except Exception:
                return False
        return True

    def is_valid_base_comment(self, comment: str, claim_id: str, parent_id: int = None, **kwargs) -> bool:
        return comment is not None and self.is_valid_body(comment) and \
               claim_id is not None and self.claim_id_is_valid(claim_id) and \
               (parent_id is None or self.is_valid_comment_id(parent_id))


class CommentCommands(CommandTestCase):

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.daemon.conf.comment_server = 'http://localhost:2903/api'
        self.comment_server = MockedCommentServer(2903)
        await self.comment_server.start()
        self.addCleanup(self.comment_server.stop)

    async def test01_comment_create(self):
        channel = (await self.channel_create('@JimmyBuffett'))['outputs'][0]
        stream = (await self.stream_create())['outputs'][0]

        empty_list = await self.daemon.jsonrpc_comment_list(stream['claim_id'])
        self.assertEqual(0, len(empty_list['items']))

        comment = await self.daemon.jsonrpc_comment_create(
            claim_id=stream['claim_id'],
            channel_id=channel['claim_id'],
            comment="It's 5 O'Clock Somewhere"
        )
        comments = (await self.daemon.jsonrpc_comment_list(stream['claim_id']))['items']
        self.assertEqual(1, len(comments))
        self.assertEqual(comment['comment_id'], comments[0]['comment_id'])
        self.assertEqual(stream['claim_id'], comments[0]['claim_id'])

        channel2 = (await self.channel_create('@BuffettJimmy'))['outputs'][0]
        comment2 = await self.daemon.jsonrpc_comment_create(
            claim_id=stream['claim_id'],
            channel_name=channel2['name'],
            comment='Let\'s all go to Margaritaville',
            parent_id=comments[0]['comment_id']
        )

        comments = (await self.daemon.jsonrpc_comment_list(stream['claim_id']))['items']
        self.assertEqual(2, len(comments))
        self.assertEqual(comments[0]['channel_id'], channel2['claim_id'])
        self.assertEqual(comments[0]['parent_id'], comments[1]['comment_id'])

    async def test03_signed_comments_list(self):
        channel = (await self.channel_create('@JimmyBuffett'))['outputs'][0]
        stream = (await self.stream_create())['outputs'][0]
        comments = []

        for i in range(28):
            comment = await self.daemon.jsonrpc_comment_create(
                comment=f'{i}',
                claim_id=stream['claim_id'],
                channel_id=channel['claim_id'],
            )
            comments.append(comment)
            self.assertIn('comment_id', comment)

        comment_list = await self.daemon.jsonrpc_comment_list(
            claim_id=stream['claim_id']
        )

        self.assertEqual(
            {'items', 'page', 'page_size', 'has_hidden_comments', 'total_items', 'total_pages'},
            set(comment_list)
        )

        self.assertIs(comment_list['page_size'], 50)
        self.assertIs(comment_list['page'], 1)
        self.assertIs(comment_list['total_items'], 28)
        for comment in comment_list['items']:
            comment_temp = comments.pop()
            self.assertEqual(comment['comment'], comment_temp['comment'])

        signed_comment_list = await self.daemon.jsonrpc_comment_list(
            claim_id=stream['claim_id'],
            is_channel_signature_valid=True
        )
        self.assertIs(len(signed_comment_list['items']), 28)

    async def test04_comment_abandons(self):
        rswanson = (await self.channel_create('@RonSwanson'))['outputs'][0]
        stream = (await self.stream_create('Pawnee_Tow_Hall_of_Fame_by_Leslie_Knope'))['outputs'][0]

        comment = await self.daemon.jsonrpc_comment_create(
            comment='KNOPE! WHAT DID I TELL YOU ABOUT PUTTING MY INFORMATION UP LIKE THAT',
            claim_id=stream['claim_id'],
            channel_id=rswanson['claim_id']
        )
        self.assertIn('signature', comment)

        abandoned = await self.daemon.jsonrpc_comment_abandon(comment['comment_id'])
        self.assertIn(comment['comment_id'], abandoned)
        self.assertTrue(abandoned[comment['comment_id']]['abandoned'])

        abandoned = await self.daemon.jsonrpc_comment_abandon(comment['comment_id'])
        self.assertFalse(abandoned[comment['comment_id']]['abandoned'])

    async def test05_comment_hide(self):
        moth = (await self.channel_create('@InconspicuousMoth'))['outputs'][0]
        bee = (await self.channel_create('@LazyBumblebee'))['outputs'][0]
        moth_id = moth['claim_id']
        stream = await self.stream_create('Cool_Lamps_to_Sit_On', channel_id=moth_id)
        claim_id = stream['outputs'][0]['claim_id']

        comment1 = await self.daemon.jsonrpc_comment_create(
            comment='Who on earth would want to sit around on a lamp all day',
            claim_id=claim_id,
            channel_id=bee['claim_id']
        )
        self.assertFalse(comment1['is_hidden'])

        comment2 = await self.daemon.jsonrpc_comment_create(
            comment='silence mortal',
            claim_id=claim_id,
            channel_id=moth_id,
        )
        self.assertFalse(comment2['is_hidden'])

        comments = await self.daemon.jsonrpc_comment_list(claim_id)
        self.assertIn('has_hidden_comments', comments)
        self.assertFalse(comments['has_hidden_comments'])

        hidden = await self.daemon.jsonrpc_comment_hide([comment1['comment_id']])
        self.assertIn('hidden', hidden)
        hidden = hidden['hidden']
        self.assertIn(comment1['comment_id'], hidden)

        comments = await self.daemon.jsonrpc_comment_list(claim_id)
        self.assertIn('has_hidden_comments', comments)
        self.assertTrue(comments['has_hidden_comments'])
        hidden_cmts1 = list(filter(lambda c: c['is_hidden'], comments['items']))
        self.assertEqual(len(hidden_cmts1), 1)
        hidden_comment = hidden_cmts1[0]
        self.assertEqual(hidden_comment['comment_id'], hidden[0])

        hidden_comments = await self.daemon.jsonrpc_comment_list(claim_id, hidden=True)
        self.assertIn('has_hidden_comments', hidden_comments)
        self.assertTrue(hidden_comments['has_hidden_comments'])
        self.assertLess(hidden_comments['total_items'], comments['total_items'])
        self.assertListEqual(hidden_comments['items'], hidden_cmts1)

        visible_comments = await self.daemon.jsonrpc_comment_list(claim_id, visible=True)
        self.assertIn('has_hidden_comments', visible_comments)
        self.assertTrue(visible_comments['has_hidden_comments'])
        self.assertLess(visible_comments['total_items'], comments['total_items'])
        total_hidden = hidden_comments['total_items']
        total_visible = visible_comments['total_items']
        self.assertEqual(total_hidden + total_visible, comments['total_items'])

        items_hidden = hidden_comments['items']
        items_visible = visible_comments['items']
        for item in items_visible + items_hidden:
            self.assertIn(item, comments['items'])

    async def test05_comment_pin(self):
        # wherein a bee makes a sick burn on moth's channel and moth pins it
        moth = (await self.channel_create('@InconspicuousMoth'))['outputs'][0]
        bee = (await self.channel_create('@LazyBumblebee'))['outputs'][0]
        moth_id = moth['claim_id']
        moth_stream = await self.stream_create('Cool_Lamps_to_Sit_On', channel_id=moth_id)
        moth_claim_id = moth_stream['outputs'][0]['claim_id']

        comment1 = await self.daemon.jsonrpc_comment_create(
            comment='Who on earth would want to sit around on a lamp all day',
            claim_id=moth_claim_id,
            channel_id=bee['claim_id']
        )
        self.assertFalse(comment1['is_pinned'])

        comment2 = await self.daemon.jsonrpc_comment_create(
            comment='sick burn, brah',
            claim_id=moth_claim_id,
            channel_id=moth_id,
        )
        self.assertFalse(comment2['is_pinned'])

        comments = await self.daemon.jsonrpc_comment_list(moth_claim_id)
        comments_items = comments['items']
        self.assertIn('is_pinned', comments_items[0])
        self.assertFalse(comments_items[0]['is_pinned'])

        pinned = await self.daemon.jsonrpc_comment_pin(
            comment_id=comment1['comment_id'],
            channel_id=moth['claim_id'],
            channel_name=moth['name']
        )
        self.assertTrue(pinned['is_pinned'])

        comments_after_pinning = await self.daemon.jsonrpc_comment_list(moth_claim_id)
        items_after_pin = comments_after_pinning['items']
        self.assertTrue(items_after_pin[1]['is_pinned'])

        unpinned = await self.daemon.jsonrpc_comment_pin(
            comment_id=comment1['comment_id'],
            channel_id=moth['claim_id'],
            channel_name=moth['name'],
            remove=True
        )
        self.assertFalse(unpinned['is_pinned'])

        comments_after_unpinning = await self.daemon.jsonrpc_comment_list(moth_claim_id)
        items_after_unpin = comments_after_unpinning['items']
        self.assertFalse(items_after_unpin[1]['is_pinned'])

    async def test06_comment_list(self):
        moth = (await self.channel_create('@InconspicuousMoth'))['outputs'][0]
        bee = (await self.channel_create('@LazyBumblebee'))['outputs'][0]
        stream = await self.stream_create('Cool_Lamps_to_Sit_On', channel_id=moth['claim_id'])
        claim_id = stream['outputs'][0]['claim_id']

        hidden_comment = await self.daemon.jsonrpc_comment_create(
            comment='Who on earth would want to sit around on a lamp all day',
            claim_id=claim_id,
            channel_id=bee['claim_id']
        )
        await self.daemon.jsonrpc_comment_hide([hidden_comment['comment_id']])
        owner_comment = await self.daemon.jsonrpc_comment_create(
            comment='Go away you yellow freak',
            claim_id=claim_id,
            channel_id=moth['claim_id'],
        )
        other_comment = await self.daemon.jsonrpc_comment_create(
            comment='I got my swim trunks and my flippy-floppies',
            claim_id=claim_id,
            channel_id=bee['claim_id']
        )
        all_comments = [other_comment, owner_comment, hidden_comment]
        normal_list = await self.daemon.jsonrpc_comment_list(claim_id)
        self.assertEqual(
            {'items', 'page', 'page_size', 'has_hidden_comments', 'total_items', 'total_pages'},
            set(normal_list)
        )
        self.assertEqual(normal_list['total_items'], 3)
        self.assertTrue(normal_list['has_hidden_comments'])
        for i, cmnt in enumerate(all_comments):
            self.assertEqual(cmnt['comment_id'], normal_list['items'][i]['comment_id'])

        hidden = await self.daemon.jsonrpc_comment_list(claim_id, hidden=True)
        self.assertEqual(
            {'items', 'page', 'page_size', 'has_hidden_comments', 'total_items', 'total_pages'},
            set(hidden)
        )
        self.assertTrue(hidden['has_hidden_comments'])
        self.assertEqual(hidden['total_items'], 1)

        visible = await self.daemon.jsonrpc_comment_list(claim_id, visible=True)
        self.assertEqual(
            {'items', 'page', 'page_size', 'has_hidden_comments', 'total_items', 'total_pages'},
            set(visible)
        )
        self.assertTrue(visible['has_hidden_comments'])
        self.assertEqual(visible['total_items'], normal_list['total_items'] - hidden['total_items'])

        valid_list = await self.daemon.jsonrpc_comment_list(claim_id, is_channel_signature_valid=True)
        self.assertEqual(
            {'items', 'page', 'page_size', 'has_hidden_comments', 'total_items', 'total_pages'},
            set(valid_list)
        )
        self.assertTrue(visible['has_hidden_comments'])
        self.assertEqual(len(valid_list['items']), len(normal_list['items']))

    async def test07_edit_comments(self):
        luda = (await self.channel_create('@Ludacris'))['outputs'][0]
        juicy = (await self.channel_create('@JuicyJ'))['outputs'][0]
        stream = await self.stream_create('Chicken-n-beer', channel_id=luda['claim_id'])
        claim_id = stream['outputs'][0]['claim_id']

        # Editing a comment made by a channel you own
        og_comment = await self.daemon.jsonrpc_comment_create(
            comment='This is a masterp[iece',
            claim_id=claim_id,
            channel_id=juicy['claim_id']
        )
        original_cid = og_comment.get('comment_id')
        original_sig = og_comment.get('signature')
        self.assertIsNotNone(original_cid, 'comment wasnt properly made')
        self.assertIsNotNone(original_sig, 'comment should have a signature')

        edited = await self.daemon.jsonrpc_comment_update(
            comment='This is a masterpiece, need more like it!',
            comment_id=original_cid
        )
        edited_cid = edited.get('comment_id')
        edited_sig = edited.get('signature')
        self.assertIsNotNone(edited_sig, 'comment wasnt properly edited!')
        self.assertIsNotNone(edited_sig, 'edited comment should have a signature!')

        self.assertEqual(original_cid, edited_cid, 'Comment ID should not change!')
        self.assertNotEqual(original_sig, edited_sig, 'New signature should not be the same as the old!')

        # editing a comment made by a channel you don't own
        og_comment = await self.daemon.jsonrpc_comment_create(
            comment='I wonder if you know, how they live in tokyo',
            claim_id=claim_id,
            channel_id=juicy['claim_id']
        )
        original_cid = og_comment.get('comment_id')
        self.assertIsNotNone(original_cid, 'Comment should be able to be made')

        # Now abandon the channel
        await self.daemon.jsonrpc_channel_abandon(juicy['claim_id'])

        # this should error out
        with self.assertRaises(ValueError):
            await self.daemon.jsonrpc_comment_update(
                comment='If you see it and you mean then you know you have to go',
                comment_id=original_cid
            )

    async def test06_reactions(self):
        # wherein a bee insulted by a rude moth accidentally
        # 1) likes an insult
        # 2) clicks dislike instead, testing "clear_types"
        # 3) then clicks dislike again, testing "remove"
        # calls from the point of view of the moth

        moth = (await self.channel_create('@InconspicuousMoth'))['outputs'][0]
        bee = (await self.channel_create('@LazyBumblebee'))['outputs'][0]
        stream = await self.stream_create('Cool_Lamps_to_Sit_On', channel_id=moth['claim_id'])
        claim_id = stream['outputs'][0]['claim_id']

        first_comment = await self.daemon.jsonrpc_comment_create(
            comment='Go away you yellow freak',
            claim_id=claim_id,
            channel_id=moth['claim_id'],
        )
        second_comment = await self.daemon.jsonrpc_comment_create(
            comment='I got my swim trunks and my flippy-floppies',
            claim_id=claim_id,
            channel_id=bee['claim_id']
        )
        first_comment_id = first_comment['comment_id']
        second_comment_id = second_comment['comment_id']
        comment_list = await self.daemon.jsonrpc_comment_list(claim_id)
        self.assertEqual(
            {'items', 'page', 'page_size', 'has_hidden_comments', 'total_items', 'total_pages'},
            set(comment_list)
        )
        self.assertEqual(comment_list['total_items'], 2)

        bee_like_reaction = await self.daemon.jsonrpc_comment_react(
            comment_ids=first_comment_id,
            channel_id=bee['claim_id'],
            channel_name=bee['name'],
            react_type='like',
        )

        moth_like_reaction = await self.daemon.jsonrpc_comment_react(
            comment_ids=first_comment_id,
            channel_id=moth['claim_id'],
            channel_name=moth['name'],
            react_type='like',
        )
        reactions = await self.daemon.jsonrpc_comment_react_list(
            comment_ids=first_comment_id,
            channel_id=moth['claim_id'],
            channel_name=moth['name'],
        )
        # {'my_reactions': {'0': {'like': 1}}, 'others_reactions': {'0': {'like': 1}}}
        self.assertEqual(reactions['my_reactions'][first_comment_id]['like'], 1)
        self.assertEqual(reactions['others_reactions'][first_comment_id]['like'], 1)

        bee_dislike_reaction = await self.daemon.jsonrpc_comment_react(
            comment_ids=first_comment_id,
            channel_id=bee['claim_id'],
            channel_name=bee['name'],
            react_type='dislike',
            clear_types='like',
        )

        reactions_after_bee_dislikes = await self.daemon.jsonrpc_comment_react_list(
            comment_ids=first_comment_id,
            channel_id=moth['claim_id'],
            channel_name=moth['name'],
        )
        # {'my_reactions': {'0': {'like': 1, 'dislike', 0}}, 'others_reactions': {'0': {'like': 0, 'dislike': 1}}}
        self.assertEqual(reactions_after_bee_dislikes['my_reactions'][first_comment_id]['like'], 1)
        self.assertEqual(reactions_after_bee_dislikes['my_reactions'][first_comment_id]['dislike'], 0)
        self.assertEqual(reactions_after_bee_dislikes['others_reactions'][first_comment_id]['dislike'], 1)
        self.assertEqual(reactions_after_bee_dislikes['others_reactions'][first_comment_id]['like'], 0)

        only_likes_after_bee_dislikes = await self.daemon.jsonrpc_comment_react_list(
            comment_ids=first_comment_id,
            channel_id=moth['claim_id'],
            channel_name=moth['name'],
            react_types='like',
        )

        self.assertEqual(only_likes_after_bee_dislikes['my_reactions'][first_comment_id]['like'], 1)
        self.assertEqual(only_likes_after_bee_dislikes['my_reactions'][first_comment_id]['dislike'], 0)
        self.assertEqual(only_likes_after_bee_dislikes['others_reactions'][first_comment_id]['dislike'], 0)
        self.assertEqual(only_likes_after_bee_dislikes['others_reactions'][first_comment_id]['like'], 0)

        bee_un_dislike_reaction = await self.daemon.jsonrpc_comment_react(
            comment_ids=first_comment_id,
            channel_id=bee['claim_id'],
            channel_name=bee['name'],
            remove=True,
            react_type='dislike',
        )

        reactions_after_bee_absconds = await self.daemon.jsonrpc_comment_react_list(
            comment_ids=first_comment_id,
            channel_id=moth['claim_id'],
            channel_name=moth['name'],
        )

        self.assertEqual(reactions_after_bee_absconds['my_reactions'][first_comment_id]['like'], 1)
        self.assertNotIn('dislike', reactions_after_bee_absconds['my_reactions'][first_comment_id])
        self.assertEqual(reactions_after_bee_absconds['others_reactions'][first_comment_id]['like'], 0)
        self.assertNotIn('dislike', reactions_after_bee_absconds['others_reactions'][first_comment_id])

        bee_reacts_to_both_comments = await self.daemon.jsonrpc_comment_react(
            comment_ids=first_comment_id + ',' + second_comment_id,
            channel_id=bee['claim_id'],
            channel_name=bee['name'],
            react_type='frozen_tom',
        )

        reactions_after_double_frozen_tom = await self.daemon.jsonrpc_comment_react_list(
            comment_ids=first_comment_id + ',' + second_comment_id,
            channel_id=moth['claim_id'],
            channel_name=moth['name'],
        )

        self.assertEqual(reactions_after_double_frozen_tom['my_reactions'][first_comment_id]['like'], 1)
        self.assertNotIn('dislike', reactions_after_double_frozen_tom['my_reactions'][first_comment_id])
        self.assertEqual(reactions_after_double_frozen_tom['others_reactions'][first_comment_id]['frozen_tom'], 1)
        self.assertEqual(reactions_after_double_frozen_tom['others_reactions'][second_comment_id]['frozen_tom'], 1)
