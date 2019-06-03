import asyncio
from aiohttp import web

from lbrynet.testcase import CommandTestCase


class FakedCommentServer:

    ERRORS = {
        'INVALID_PARAMS': {'code': -32602, 'message': 'Invalid parameters'},
        'INTERNAL': {'code': -32603, 'message': 'An internal error'},
        'UNKNOWN': {'code': -1, 'message': 'An unknown or very miscellaneous error'},
        'INVALID_METHOD': {'code': -32604, 'message': 'The Requested method does not exist'}
    }

    def __init__(self, port=2903):
        self.port = port
        self.app = web.Application(debug=True)
        self.app.add_routes([web.post('/api', self.api)])
        self.runner = None
        self.server = None
        self.comments = []
        self.comment_id = 0

    def create_comment(self, **comment):
        self.comment_id += 1
        comment['comment_id'] = self.comment_id
        self.comments.append(comment)
        return comment

    def get_claim_comments(self, page=1, page_size=50, **kwargs):
        return self.comments[:page_size]

    methods = {
        'get_claim_comments': get_claim_comments,
        'create_comment': create_comment,
    }

    def process_json(self, body) -> dict:
        response = {'jsonrpc': '2.0', 'id': body['id']}
        if body['method'] in self.methods:
            params = body.get('params', {})
            result = self.methods[body['method']](self, **params)
            response['result'] = result
        else:
            response['error'] = self.ERRORS['INVALID_METHOD']
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
        self.comment_server = FakedCommentServer(2903)
        await self.comment_server.start()
        self.addCleanup(self.comment_server.stop)

    async def test_comment_create(self):
        channel = (await self.channel_create('@JimmyBuffett'))['outputs'][0]
        stream = (await self.stream_create())['outputs'][0]

        self.assertEqual(0, len(await self.daemon.jsonrpc_comment_list(stream['claim_id'])))
        comment = await self.daemon.jsonrpc_comment_create(
            claim_id=stream['claim_id'],
            channel_id=channel['claim_id'],
            comment="It's 5 O'Clock Somewhere"
        )
        comments = await self.daemon.jsonrpc_comment_list(stream['claim_id'])
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
        comments = await self.daemon.jsonrpc_comment_list(stream['claim_id'])
        self.assertEqual(2, len(comments))
        self.assertEqual(comments[1]['channel_id'], channel2['claim_id'])
        self.assertEqual(comments[0]['comment_id'], comments[1]['parent_id'])
