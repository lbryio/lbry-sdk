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
        return {k: v for k, v in d.items() if v}

    def create_comment(self, channel_name=None, channel_id=None, **kwargs):
        self.comment_id += 1
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
        return self.clean(comment)

    def delete_comment(self, comment_id: int, channel_id: str, **kwargs):
        deleted = False
        try:
            if 0 <= comment_id <= len(self.comments) and self.comments[comment_id - 1]['channel_id'] == channel_id:
                self.comments.pop(comment_id - 1)
                deleted = True
        finally:
            return {
                str(comment_id): {
                    'deleted': deleted
                }
            }

    def get_claim_comments(self, page=1, page_size=50, **kwargs):
        return {
            'page': page,
            'page_size': page_size,
            'total_pages': ceil(len(self.comments)/page_size),
            'total_items': len(self.comments),
            'items': [self.clean(c) for c in (self.comments[::-1])[(page - 1) * page_size: page * page_size]]
        }

    def get_comment_channel_by_id(self, comment_id: int, **kwargs):
        comment = self.comments[comment_id - 1]
        return {
            'channel_id': comment.get('channel_id'),
            'channel_name': comment.get('channel_name')
        }

    methods = {
        'get_claim_comments': get_claim_comments,
        'create_comment': create_comment,
        'delete_comment': delete_comment,
        'get_channel_from_comment_id': get_comment_channel_by_id,
    }

    def process_json(self, body) -> dict:
        response = {'jsonrpc': '2.0', 'id': body['id']}
        try:
            if body['method'] in self.methods:
                params = body.get('params', {})
                if 'comment_id' in params and type(params['comment_id']) is str:
                    params['comment_id'] = int(params['comment_id'])
                result = self.methods[body['method']](self, **params)
                response['result'] = result
            else:
                response['error'] = self.ERRORS['INVALID_METHOD']
        except Exception:
            response['error'] = self.ERRORS['UNKNOWN']
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
        for i in range(28):
            comment = await self.daemon.jsonrpc_comment_create(
                comment=f'{i}',
                claim_id=stream['claim_id'],
            )
            self.assertIn('comment_id', comment)
            comments.append(comment)

        comment_list = await self.daemon.jsonrpc_comment_list(
            claim_id=stream['claim_id']
        )
        self.assertIs(comment_list['page_size'], 50)
        self.assertIs(comment_list['page'], 1)
        self.assertIs(comment_list['total_items'], 28)
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

        comment_list = await self.daemon.jsonrpc_comment_list(
            claim_id=stream['claim_id']
        )
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
        deleted = await self.daemon.jsonrpc_comment_abandon(comment['comment_id'])
        self.assertIn(comment['comment_id'], deleted)
        self.assertTrue(deleted[comment['comment_id']]['deleted'])

        deleted = await self.daemon.jsonrpc_comment_abandon(comment['comment_id'])
        self.assertIn(comment['comment_id'], deleted)
        self.assertFalse(deleted[comment['comment_id']]['deleted'])
