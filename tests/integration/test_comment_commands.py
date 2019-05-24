import logging
import time

import asyncio
from aiohttp import web

from lbrynet.testcase import CommandTestCase

import lbrynet.schema
lbrynet.schema.BLOCKCHAIN_NAME = 'lbrycrd_regtest'

COMMENT_IDS = [
    "b7de681c412e315bb1a9ada6f485a2e0399400db",
    "0f7e1514f55c7fefba1e714386e05b3d705f6d29",
    "8ae19f686c39f402c80dabf25df23cf72fe426af",
    "a11ad59b54bb937ca1a88329f253b17196bd4dc3",
    "7ee87b3249fa47b296c8347cd63bba679ef629eb",
    "0100e3367f68284f4970736c9351ad90c37dade5",
    "974a5bfcce6bc72605688ba6e2efd34aa934b1dc",
    "97ea100a52aa46ae9f2a4356169307a2505e8d47",
    "2b4d193371c8f0ed45c830cb1ba3188b90bf08f1",
    "db335dc3183ca3552b6ef4a7bce36f26ed37b7eb"
]

CLAIM_IDS = [
    "f6068bdc8cb66fe7eb6c3cf4cf98da93a697df47",
    "44a8c10e36ed8b60da8d5fe590cba61544fb7179",
    "a7d8a1fc90ab806c98743a7f9ca7480e2cebe2a0",
    "81a8cc2fa41eea0ae9d65ab0f8a0440605a23f1b",
    "49117e9a7bb2aab01356e1160871aad5edb09ed5",
    "2b928261918b1f7c65973c8fee9e20d4a1f1b2a4",
    "f9d6eb75d1592a967b1c405208593d30b46446c9",
    "cc70bd497eb1305096fa4e28275645f47c5d809d",
    "2e520f60bd8f79f309d68b291fe574531a7d6656",
    "16b0248c103fb7b3497bd58543f6c5dd6d47d5f2"
]

CHANNEL_IDS = [
    "7b65a9886869a367371ec621abe5bac4e5dd27b9",
    "c3bbde23a8b31dc05490cede3a381080b024f878",
    "c544579ca13ce5d97e9301789620547323da15eb",
    "428e1c075b27bbce1380c16ecb5f0d228318315e",
    "1558b39438f573a47a5e0fcd78ad24d0eb358be0",
    "ac66521e1757d320568a52ab8b01029bd169b1a0",
    "aa89729a08050694ffb62e725356bbaa26481193",
    "23181733dc3b836e4d38e8cc21d79378b855cf36",
    "60efc8ced56a6a02c2d5371310f0130c541a9ded",
    "af1c95f2026d4a254512dd6e6a792a9d92b9fd21"
]


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

    def get_comment(self, **kwargs) -> dict:
        return {
            'comment_id': 'asbdsdasd',
            'parent_id': 'asdsfsfsf',
            'comment': 'asdsdadsdas',
            'timestamp': time.time_ns(),
            'channel_id': 'asdsdsdasdad',
            'channel_name': 'asdsasasfaf',
            'channel_uri': 'asdsdasda',
            'signature': 'aasdasdasda',
        }

    def create_comment(self, comment, claim_id, **kwargs):
        return self.get_comment(**kwargs)

    def get_claim_comments(self, page=1, page_size=50, **kwargs):
        return [self.get_comment(**kwargs) for i in range(page_size)]

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
            raise TypeError('invalid type passed')


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
        comment = await self.daemon.jsonrpc_comment_create(
            claim_id=CLAIM_IDS[0],
            channel_name='@JimmyBuffett',
            channel_id=CHANNEL_IDS[0],
            comment="It's 5 O'Clock Somewhere"
        )
        self.assertIsNotNone(comment)
        self.assertNotIn('error', comment)
        self.assertIn('comment', comment, msg=f"Response {comment} doesn't contain message")
        self.assertIn('channel_name', comment)

    async def test_comment_create_reply(self):
        reply = await self.daemon.jsonrpc_comment_create(
            claim_id=CLAIM_IDS[0],
            channel_name='@JimmyBuffett',
            channel_id=CHANNEL_IDS[0],
            comment='Let\'s all go to Margaritaville',
            parent_id=COMMENT_IDS[0]
        )
        self.assertIsNotNone(reply)
        self.assertNotIn('error', reply)
        self.assertIn('comment_id', reply)
        self.assertIsNotNone(reply['parent_id'])

    async def test_comment_list_root_level(self):
        comments = await self.daemon.jsonrpc_comment_list(CLAIM_IDS[0])
        self.assertIsNotNone(comments)
        self.assertIs(type(comments), list)
        comments = await self.daemon.jsonrpc_comment_list(CLAIM_IDS[1], page_size=50)
        self.assertIsNotNone(comments)
        self.assertLessEqual(len(comments), 50)
        self.assertGreaterEqual(len(comments), 0)

    async def test_comment_list_replies(self):
        replies = await self.daemon.jsonrpc_comment_list(CLAIM_IDS[0], parent_id=23)
        self.assertIsInstance(replies, list)
        self.assertGreater(len(replies), 0)
        replies = await self.daemon.jsonrpc_comment_list(CLAIM_IDS[2], parent_id=COMMENT_IDS[3], page_size=50)
        self.assertEqual(len(replies), 50)
        replies = await self.daemon.jsonrpc_comment_list(CLAIM_IDS[3], parent_id=COMMENT_IDS[5],
                                                         page_size=23, page=5)
        self.assertEqual(len(replies), 23)
        replies = await self.daemon.jsonrpc_comment_list(CLAIM_IDS[5], parent_id=COMMENT_IDS[1],
                                                         page_size=60, page=2)
        self.assertEqual(len(replies), 60)

    async def test_comment_list_flatness_flatness_LA(self):
        replies = await self.daemon.jsonrpc_comment_list(CLAIM_IDS[2], parent_id=23, include_replies=True)
        self.assertGreater(len(replies), 0)
        replies = await self.daemon.jsonrpc_comment_list(CLAIM_IDS[6], parent_id=25,
                                                         page_size=50, include_replies=True)
        self.assertGreaterEqual(len(replies), 0)
        self.assertLessEqual(len(replies), 50)
        replies = await self.daemon.jsonrpc_comment_list(CLAIM_IDS[7], parent_id=67, page_size=23, page=5)
        self.assertGreaterEqual(len(replies), 0)
        self.assertLessEqual(len(replies), 23)
        replies = await self.daemon.jsonrpc_comment_list(CLAIM_IDS[9], parent_id=79, page=2, include_replies=True)
        self.assertGreaterEqual(len(replies), 15)
