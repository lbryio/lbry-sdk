import logging

import typing
import random
import asyncio
from aiohttp import web

from lbrynet.testcase import CommandTestCase

import lbrynet.schema
lbrynet.schema.BLOCKCHAIN_NAME = 'lbrycrd_regtest'


class FakedCommentServer:
    ERRORS = {
        'INVALID_URI': {'code': 1, 'message': 'Invalid claim URI'},
        'INVALID_PARAMS': {'code': -32602, 'message': 'Invalid parameters'},
        'INTERNAL': {'code': -32603, 'message': 'An internal error'},
        'UNKNOWN': {'code': -1, 'message': 'An unknown or very miscellaneous error'},
    }

    def __init__(self, port=2903):
        self.port = port
        self.app = web.Application(debug=True)
        self.app.add_routes([web.post('/api', self.api)])
        self.runner = None
        self.server = None

    def get_claim_comments(self, uri: str, better_keys: bool) -> typing.Union[dict, list, None]:
        if not uri.startswith('lbry://'):  # Very basic error case
            return {'error': self.ERRORS['INVALID_URI']}
        return [self.get_comment(i) for i in range(75)]

    def get_comment(self, comment_id: int, parent_id: int = None) -> dict:
        return {
            'comment_id': comment_id,
            'parent_id': parent_id,
            'author': f'Person{comment_id}',
            'message': f'comment {comment_id}',
            'claim_id': random.randint(1, 2**16),
            'time_posted': random.randint(2**16, 2**32 - 1),
            'upvotes': random.randint(0, 9999), 'downvotes': random.randint(0, 9999)
        }

    def comment(self, uri: str, poster: str, message: str) -> typing.Union[int, dict, None]:
        if not uri.startswith('lbry://'):
            return {'error': self.ERRORS['INVALID_URI']}
        return random.randint(1, 9999)

    def reply(self, parent_id: int, poster: str, message: str) -> dict:
        if 2 <= len(message) <= 2000 and 2 <= len(poster) <= 127 and parent_id > 0:
            return random.randint(parent_id + 1, 2**32 - 1)
        return {'error': self.ERRORS['INVALID_PARAMS']}

    def get_comment_data(self, comm_index: int, better_keys: bool = False) -> typing.Union[dict, None]:
        return self.get_comment(comm_index)

    def get_comment_replies(self, comm_index: int) -> typing.Union[list, None]:
        return [random.randint(comm_index, comm_index+250) for _ in range(75)]

    methods = {
        'get_claim_comments': get_claim_comments,
        'get_comment_data': get_comment_data,
        'get_comment_replies': get_comment_replies,
        'comment': comment,
        'reply': reply
    }

    def process_json(self, body) -> dict:
        response = {'jsonrpc': '2.0', 'id': body['id']}
        if body['method'] in self.methods:
            params = body.get('params', {})
            result = self.methods[body['method']](self, **params)
            if type(result) is dict and 'error' in result:
                response['error'] = result['error']
            else:
                response['result'] = result
        else:
            response['error'] = self.ERRORS['UNKNOWN']
        return response

    async def _start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.server = web.TCPSite(self.runner, 'localhost', self.port)
        await self.server.start()

    async def _stop(self):
        await self.runner.cleanup()

    async def run(self, max_timeout=3600):
        try:
            await self._start()
            await asyncio.sleep(max_timeout)
        except asyncio.CancelledError:
            pass
        finally:
            await self._stop()

    async def api(self, request):
        body = await request.json()
        if type(body) is list or type(body) is dict:
            if type(body) is list:
                response = [self.process_json(part) for part in body]
            else:
                response = self.process_json(body)
            return web.json_response(response)
        else:
            return web.json_response({'error': self.ERRORS['UNKNOWN']})


class CommentCommands(CommandTestCase):

    VERBOSITY = logging.WARN

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.daemon.conf.comment_server = 'http://localhost:2903/api'
        self.server = FakedCommentServer(2903)
        self.server_task = asyncio.create_task(self.server.run(self.timeout))

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.server_task.cancel()
        if not self.server_task.cancelled():
            await self.server_task

    async def test_comment_create(self):
        claim = await self.stream_create(name='doge', bid='0.001', data=b'loool')
        self.assertIn('outputs', claim)
        comment = await self.daemon.jsonrpc_comment_create(
            claim_id=claim['outputs'][0]['claim_id'],
            channel_id='Jimmy Buffett',
            message="It's 5 O'Clock Somewhere"
        )
        self.assertIs(type(comment), dict, msg=f"Response type ({type(comment)})is not dict: {comment}")
        self.assertIn('message', comment, msg=f"Response {comment} doesn't contain message")
        self.assertIn('author', comment)

    async def test_comment_create_reply(self):
        claim = await self.stream_create(name='doge', bid='0.001')
        self.assertIn('outputs', claim)
        reply = await self.daemon.jsonrpc_comment_create(
            claim_id=claim['outputs'][0]['claim_id'],
            channel_id='Jimmy Buffett',
            message='Let\'s all go to Margaritaville',
            parent_comment_id=42
        )
        self.assertIs(type(reply), dict, msg=f'Response {type(reply)} is not dict\nResponse: {reply}')
        self.assertIn('author', reply)

    async def test_comment_list_root_level(self):
        claim = await self.stream_create(name='doge', bid='0.001')
        self.assertIn('outputs', claim)
        claim_id = claim['outputs'][0]['claim_id']
        comments = await self.daemon.jsonrpc_comment_list(claim_id)
        self.assertIsNotNone(type(comments))
        self.assertIs(type(comments), dict)
        self.assertIn('comments', comments, f"'comments' field was not found in returned dict: {comments}")
        self.assertIs(type(comments['comments']), list, msg=f'comment_list: {comments}')
        comments = await self.daemon.jsonrpc_comment_list(claim_id, page_size=50)
        self.assertIsNotNone(comments)
        self.assertIs(type(comments), dict)
        self.assertIn('comments', comments, f"'comments' field was not found in returned dict: {comments}")
        comment_list = comments['comments']
        self.assertEqual(len(comment_list), 50, msg=f'comment_list incorrect size {len(comment_list)}: {comment_list}')
        comments = await self.daemon.jsonrpc_comment_list(claim_id, page_size=50, page=2)
        self.assertEqual(len(comments['comments']), 25, msg=f'comment list page 2: {comments["comments"]}')
        comments = await self.daemon.jsonrpc_comment_list(claim_id, page_size=50, page=3)
        self.assertEqual(len(comments['comments']), 0, msg=f'comment list is non-zero: {comments["comments"]}')

    async def test_comment_list_replies(self):
        claim = await self.stream_create(name='doge', bid='0.001')
        self.assertIn('outputs', claim)
        claim_id = claim['outputs'][0]['claim_id']
        replies = await self.daemon.jsonrpc_comment_list(claim_id, parent_comment_id=23)
        self.assertIsInstance(replies['comments'], list, msg=f'Invalid type: {replies["comments"]} should be list')
        self.assertGreater(len(replies['comments']), 0, msg='Returned replies are empty')
        replies = (await self.daemon.jsonrpc_comment_list(claim_id, parent_comment_id=25, page_size=50))['comments']
        self.assertEqual(len(replies), 50, f'Replies invalid length ({len(replies)})')
        replies = (await self.daemon.jsonrpc_comment_list(claim_id, parent_comment_id=67,
                                                          page_size=23, page=5))['comments']
        self.assertEqual(len(replies), 0, f'replies {replies} not 23: {len(replies)}')
        replies = (await self.daemon.jsonrpc_comment_list(claim_id, parent_comment_id=79,
                                                          page_size=60, page=2))['comments']
        self.assertEqual(len(replies), 15, f'Size of replies is incorrect, should be 15:  {replies}')

    async def test_comment_list_flatness_flatness_LA(self):
        claim = await self.stream_create(name='doge', bid='0.001')
        self.assertIn('outputs', claim)
        claim_id = claim['outputs'][0]['claim_id']
        replies = await self.daemon.jsonrpc_comment_list(claim_id, parent_comment_id=23, flat=True)
        self.assertIsInstance(replies['comments'], list, msg=f'Invalid type: {replies["comments"]} should be list')
        self.assertGreater(len(replies['comments']), 0, msg='Returned replies are empty')
        replies = (await self.daemon.jsonrpc_comment_list(claim_id, parent_comment_id=25, flat=True,
                                                          max_replies_shown=0, page_size=50))['comments']
        self.assertEqual(len(replies), 50, f'Replies invalid length ({len(replies)})')
        replies = (await self.daemon.jsonrpc_comment_list(claim_id, parent_comment_id=67,
                                                          flat=True, page_size=23, page=5))['comments']
        self.assertEqual(len(replies), 0, f'replies {replies} not 23: {len(replies)}')
        replies = (await self.daemon.jsonrpc_comment_list(claim_id, parent_comment_id=79,
                                                          page_size=60, page=2))['comments']
        self.assertGreaterEqual(len(replies), 15, f'Size of replies is incorrect, should be 15:  {replies}')
