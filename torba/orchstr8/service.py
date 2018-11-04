import asyncio
import logging
from aiohttp.web import Application, WebSocketResponse, json_response
from aiohttp.http_websocket import WSMsgType, WSCloseCode
from .node import Conductor


PORT = 7954


class WebSocketLogHandler(logging.Handler):

    def __init__(self, send_message):
        super().__init__()
        self.send_message = send_message

    def emit(self, record):
        try:
            self.send_message({
                'type': 'log',
                'name': record.name,
                'message': self.format(record)
            })
        except Exception:
            self.handleError(record)


class ConductorService:

    def __init__(self, stack: Conductor, loop: asyncio.AbstractEventLoop) -> None:
        self.stack = stack
        self.loop = loop
        self.app = Application()
        self.app.router.add_post('/start', self.start_stack)
        self.app.router.add_post('/generate', self.generate)
        self.app.router.add_post('/transfer', self.transfer)
        self.app.router.add_post('/balance', self.balance)
        self.app.router.add_get('/log', self.log)
        self.app['websockets'] = set()
        self.app.on_shutdown.append(self.on_shutdown)
        self.handler = self.app.make_handler()
        self.server = None

    async def start(self):
        self.server = await self.loop.create_server(
            self.handler, '0.0.0.0', PORT
        )
        print('serving on', self.server.sockets[0].getsockname())

    async def stop(self):
        await self.stack.stop()
        self.server.close()
        await self.server.wait_closed()
        await self.app.shutdown()
        await self.handler.shutdown(60.0)
        await self.app.cleanup()

    async def start_stack(self, _):
        handler = WebSocketLogHandler(self.send_message)
        logging.getLogger('blockchain').setLevel(logging.DEBUG)
        logging.getLogger('blockchain').addHandler(handler)
        logging.getLogger('electrumx').setLevel(logging.DEBUG)
        logging.getLogger('electrumx').addHandler(handler)
        logging.getLogger('Controller').setLevel(logging.DEBUG)
        logging.getLogger('Controller').addHandler(handler)
        logging.getLogger('LBRYBlockProcessor').setLevel(logging.DEBUG)
        logging.getLogger('LBRYBlockProcessor').addHandler(handler)
        logging.getLogger('LBCDaemon').setLevel(logging.DEBUG)
        logging.getLogger('LBCDaemon').addHandler(handler)
        logging.getLogger('torba').setLevel(logging.DEBUG)
        logging.getLogger('torba').addHandler(handler)
        logging.getLogger(self.stack.ledger_module.__name__).setLevel(logging.DEBUG)
        logging.getLogger(self.stack.ledger_module.__name__).addHandler(handler)
        logging.getLogger(self.stack.ledger_module.__electrumx__.split('.')[0]).setLevel(logging.DEBUG)
        logging.getLogger(self.stack.ledger_module.__electrumx__.split('.')[0]).addHandler(handler)
        #await self.stack.start()
        self.stack.blockchain_started or await self.stack.start_blockchain()
        self.send_message({'type': 'service', 'name': 'blockchain'})
        self.stack.spv_started or await self.stack.start_spv()
        self.send_message({'type': 'service', 'name': 'spv'})
        self.stack.wallet_started or await self.stack.start_wallet()
        self.send_message({'type': 'service', 'name': 'wallet'})
        self.stack.wallet_node.ledger.on_header.listen(self.on_status)
        self.stack.wallet_node.ledger.on_transaction.listen(self.on_status)
        return json_response({'started': True})

    async def generate(self, request):
        data = await request.post()
        blocks = data.get('blocks', 1)
        await self.stack.blockchain_node.generate(int(blocks))
        return json_response({'blocks': blocks})

    async def transfer(self, request):
        data = await request.post()
        address = data.get('address')
        if not address:
            address = await self.stack.wallet_node.account.receiving.get_or_create_usable_address()
        amount = data.get('amount', 1)
        txid = await self.stack.blockchain_node.send_to_address(address, amount)
        await self.stack.wallet_node.ledger.on_transaction.where(
            lambda e: e.tx.id == txid and e.address == address
        )
        return json_response({
            'address': address,
            'amount': amount,
            'txid': txid
        })

    async def balance(self, _):
        return json_response({
            'balance': await self.stack.blockchain_node.get_balance()
        })

    async def log(self, request):
        web_socket = WebSocketResponse()
        await web_socket.prepare(request)
        self.app['websockets'].add(web_socket)
        try:
            async for msg in web_socket:
                if msg.type == WSMsgType.TEXT:
                    if msg.data == 'close':
                        await web_socket.close()
                elif msg.type == WSMsgType.ERROR:
                    print('web socket connection closed with exception %s' %
                          web_socket.exception())
        finally:
            self.app['websockets'].remove(web_socket)
        return web_socket

    @staticmethod
    async def on_shutdown(app):
        for web_socket in app['websockets']:
            await web_socket.close(code=WSCloseCode.GOING_AWAY, message='Server shutdown')

    async def on_status(self, _):
        if not self.app['websockets']:
            return
        self.send_message({
            'type': 'status',
            'height': self.stack.wallet_node.ledger.headers.height,
            'balance': await self.stack.wallet_node.account.get_balance(),
            'miner': await self.stack.blockchain_node.get_balance()
        })

    def send_message(self, msg):
        for web_socket in self.app['websockets']:
            asyncio.ensure_future(web_socket.send_json(msg))
