import asyncio
import logging
from aiohttp.web import Application, WebSocketResponse, json_response
from aiohttp.http_websocket import WSMsgType, WSCloseCode

from torba.client.util import satoshis_to_coins
from .node import Conductor, set_logging


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
        set_logging(
            self.stack.ledger_module, logging.DEBUG, WebSocketLogHandler(self.send_message)
        )
        self.stack.blockchain_started or await self.stack.start_blockchain()
        self.send_message({'type': 'service', 'name': 'blockchain', 'port': self.stack.blockchain_node.port})
        self.stack.spv_started or await self.stack.start_spv()
        self.send_message({'type': 'service', 'name': 'spv', 'port': self.stack.spv_node.port})
        self.stack.wallet_started or await self.stack.start_wallet()
        self.send_message({'type': 'service', 'name': 'wallet', 'port': self.stack.wallet_node.port})
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
        if not address and self.stack.wallet_started:
            address = await self.stack.wallet_node.account.receiving.get_or_create_usable_address()
        if not address:
            raise ValueError("No address was provided.")
        amount = data.get('amount', 1)
        txid = await self.stack.blockchain_node.send_to_address(address, amount)
        if self.stack.wallet_started:
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
            'balance': satoshis_to_coins(await self.stack.wallet_node.account.get_balance()),
            'miner': await self.stack.blockchain_node.get_balance()
        })

    def send_message(self, msg):
        for web_socket in self.app['websockets']:
            self.loop.create_task(web_socket.send_json(msg))
