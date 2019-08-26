import time
from math import ceil

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
    }

    def __init__(self, port=2903):
        self.port = port
        self.app = web.Application(debug=True)
        self.app.add_routes([web.post('/api', self.api)])
        self.runner = None
        self.server = None
        self.comments = []
        self.comment_id = 0

    @classmethod
    def _create_comment(cls, **kwargs):
        schema = cls.COMMENT_SCHEMA.copy()
        schema.update(**kwargs)
        return schema

    @staticmethod
    def clean(d: dict):
        return {k: v for k, v in d.items() if v or isinstance(v, bool)}

    def create_comment(self, channel_name=None, channel_id=None, **kwargs):
        comment_id = self.comment_id
        channel_url = 'lbry://' + channel_name + '#' + channel_id if channel_id else None
        comment = self._create_comment(
            comment_id=str(comment_id),
            channel_name=channel_name,
            channel_id=channel_id,
            channel_url=channel_url,
            timestamp=str(int(time.time())),
            **kwargs
        )
        self.comments.append(comment)
        self.comment_id += 1
        return self.clean(comment)

    def abandon_comment(self, comment_id: int, channel_id: str, **kwargs):
        deleted = False
        try:
            if 0 <= comment_id < len(self.comments) and self.comments[comment_id]['channel_id'] == channel_id:
                self.comments.pop(comment_id)
                deleted = True
        finally:
            return {
                str(comment_id): {
                    'abandoned': deleted
                }
            }

    def hide_comment(self, comment_id, signing_ts, signature):
        comment_id = int(comment_id) if not isinstance(comment_id, int) else comment_id
        if 0 <= comment_id < len(self.comments) and len(signature) == 128 and signing_ts.isalnum():
            self.comments[comment_id]['is_hidden'] = True
            return True
        return False

    def hide_comments(self, pieces: list):
        comments_hidden = []
        for p in pieces:
            if self.hide_comment(**p):
                comments_hidden.append(p['comment_id'])
        return {'hidden': comments_hidden}

    def get_claim_comments(self, claim_id, page=1, page_size=50,**kwargs):
        comments = list(filter(lambda c: c['claim_id'] == claim_id, self.comments))
        return {
            'page': page,
            'page_size': page_size,
            'total_pages': ceil(len(comments)/page_size),
            'total_items': len(comments),
            'items': [self.clean(c) for c in (comments[::-1])[(page - 1) * page_size: page * page_size]],
            'has_hidden_comments': bool(list(filter(lambda x: x['is_hidden'], comments)))
        }

    def get_claim_hidden_comments(self, claim_id, hidden=True, page=1, page_size=50):
        comments = list(filter(lambda c: c['claim_id'] == claim_id, self.comments))
        select_comments = list(filter(lambda c: c['is_hidden'] == hidden, comments))
        return {
            'page': page,
            'page_size': page_size,
            'total_pages': ceil(len(select_comments) / page_size),
            'total_items': len(select_comments),
            'items': [self.clean(c) for c in (select_comments[::-1])[(page - 1) * page_size: page * page_size]],
            'has_hidden_comments': bool(list(filter(lambda c: c['is_hidden'], comments)))
        }

    def get_comment_channel_by_id(self, comment_id: int, **kwargs):
        comment = self.comments[comment_id]
        return {
            'channel_id': comment.get('channel_id'),
            'channel_name': comment.get('channel_name')
        }

    def get_comments_by_id(self, comment_ids: list):
        comment_ids = [int(c) if not isinstance(c, int) else c for c in comment_ids]
        comments = [self.comments[cmnt_id] for cmnt_id in comment_ids if 0 <= cmnt_id < len(self.comments)]
        return comments

    methods = {
        'get_claim_comments': get_claim_comments,
        'get_comments_by_id': get_comments_by_id,
        'create_comment': create_comment,
        'abandon_comment': abandon_comment,
        'get_channel_from_comment_id': get_comment_channel_by_id,
        'get_claim_hidden_comments': get_claim_hidden_comments,
        'hide_comments': hide_comments,
    }

    def process_json(self, body) -> dict:
        response = {'jsonrpc': '2.0', 'id': body['id']}
        try:
            if body['method'] in self.methods:
                params: dict = body.get('params', {})
                comment_id = params.get('comment_id')
                if comment_id and not isinstance(comment_id, int):
                    params['comment_id'] = int(comment_id)

                result = self.methods[body['method']](self, **params)
                response['result'] = result
            else:
                response['error'] = self.ERRORS['INVALID_METHOD']
        except Exception as err:
            response['error'] = self.ERRORS['UNKNOWN']
            response['error'].update({'exception': f'{type(err).__name__}: {err}'})
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

        self.assertEqual(0, len((await self.daemon.jsonrpc_comment_list(stream['claim_id']))['items']))
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
        await self.daemon.jsonrpc_comment_create(
            claim_id=stream['claim_id'],
            channel_name=channel2['name'],
            comment='Let\'s all go to Margaritaville',
            parent_id=comments[0]['comment_id']
        )
        comments = (await self.daemon.jsonrpc_comment_list(stream['claim_id']))['items']
        self.assertEqual(2, len(comments))
        self.assertEqual(comments[0]['channel_id'], channel2['claim_id'])
        self.assertEqual(comments[0]['parent_id'], comments[1]['comment_id'])

        comment = await self.daemon.jsonrpc_comment_create(
            claim_id=stream['claim_id'],
            comment='Anonymous comment'
        )
        comments = (await self.daemon.jsonrpc_comment_list(stream['claim_id']))['items']
        self.assertEqual(comment['comment_id'], comments[0]['comment_id'])

    async def test02_unsigned_comment_list(self):
        stream = (await self.stream_create())['outputs'][0]
        comments = []
        num_items = 28
        for i in range(num_items):
            comment = await self.daemon.jsonrpc_comment_create(
                comment=f'{i}',
                claim_id=stream['claim_id'],
            )
            self.assertIn('comment_id', comment)
            comments.append(comment)
        list_fields = ['items', 'page', 'page_size', 'has_hidden_comments', 'total_items', 'total_pages']
        comment_list = await self.daemon.jsonrpc_comment_list(stream['claim_id'])
        for field in list_fields:
            self.assertIn(field, comment_list)
        self.assertEqual(comment_list['total_items'], num_items)
        for comment in comment_list['items']:
            self.assertEqual(comment['comment'], comments.pop()['comment'])

        signed_comment_list = await self.daemon.jsonrpc_comment_list(
            claim_id=stream['claim_id'],
            is_channel_signature_valid=True
        )
        self.assertIs(len(signed_comment_list['items']), 0)

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
            self.assertIn('comment_id', comment)
            comments.append(comment)
        list_fields = ['items', 'page', 'page_size', 'has_hidden_comments', 'total_items', 'total_pages']
        comment_list = await self.daemon.jsonrpc_comment_list(
            claim_id=stream['claim_id']
        )
        for field in list_fields:
            self.assertIn(field, comment_list)
        self.assertIs(comment_list['page_size'], 50)
        self.assertIs(comment_list['page'], 1)
        self.assertIs(comment_list['total_items'], 28)
        for comment in comment_list['items']:
            self.assertEqual(comment['comment'], comments.pop()['comment'])

        signed_comment_list = await self.daemon.jsonrpc_comment_list(
            claim_id=stream['claim_id'],
            is_channel_signature_valid=True
        )
        self.assertIs(len(signed_comment_list['items']), 28)

    async def test04_comment_abandons(self):
        rswanson = (await self.channel_create('@RonSwanson'))['outputs'][0]
        stream = (await self.stream_create('Pawnee Town Hall of Fame by Leslie Knope'))['outputs'][0]
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
        stream = await self.stream_create('Cool Lamps to Sit On', channel_id=moth_id)
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
        self.assertTrue(len(hidden_cmts1) == 1)
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

    async def test06_comment_list_test(self):
        moth = (await self.channel_create('@InconspicuousMoth'))['outputs'][0]
        bee = (await self.channel_create('@LazyBumblebee'))['outputs'][0]
        moth_id = moth['claim_id']
        stream = await self.stream_create('Cool Lamps to Sit On', channel_id=moth_id)
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
            channel_id=moth_id,
        )
        other_comment = await self.daemon.jsonrpc_comment_create(
            comment='I got my swim trunks and my flippy-floppies',
            claim_id=claim_id,
            channel_id=bee['claim_id']
        )
        anon_comment = await self.daemon.jsonrpc_comment_create(
            claim_id=claim_id,
            comment='Anonymous comment'
        )
        all_comments = [anon_comment, other_comment, owner_comment, hidden_comment]
        list_fields = ['items', 'page', 'page_size', 'has_hidden_comments', 'total_items', 'total_pages']
        normal_list = await self.daemon.jsonrpc_comment_list(claim_id)
        for field in list_fields:
            self.assertIn(field, normal_list)
        self.assertEqual(normal_list['total_items'], 4)
        self.assertTrue(normal_list['has_hidden_comments'])
        for i, cmnt in enumerate(all_comments):
            self.assertEqual(cmnt['comment_id'], normal_list['items'][i]['comment_id'])

        hidden = await self.daemon.jsonrpc_comment_list(claim_id, hidden=True)
        self.assertTrue(hidden['has_hidden_comments'])
        for field in list_fields:
            self.assertIn(field, hidden)
        self.assertEqual(hidden['total_items'], 1)

        visible = await self.daemon.jsonrpc_comment_list(claim_id, visible=True)
        for field in list_fields:
            self.assertIn(field, visible)
        self.assertTrue(visible['has_hidden_comments'])
        self.assertEqual(visible['total_items'], normal_list['total_items'] - hidden['total_items'])

        valid_list = await self.daemon.jsonrpc_comment_list(claim_id, is_channel_signature_valid=True)
        for field in list_fields:
            self.assertIn(field, valid_list)
        self.assertTrue(visible['has_hidden_comments'])
        self.assertEqual(len(valid_list['items']), len(normal_list['items']) - 1)
