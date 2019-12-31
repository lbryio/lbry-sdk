import asyncio
from weakref import WeakSet

from aiohttp.web import Application, AppRunner, WebSocketResponse, TCPSite
from aiohttp.http_websocket import WSMsgType, WSCloseCode


class AdminWebSocket:

    def __init__(self, manager):
        self.manager = manager
        self.app = Application()
        self.app['websockets'] = WeakSet()
        self.app.router.add_get('/', self.on_connect)
        self.app.on_shutdown.append(self.on_shutdown)
        self.runner = AppRunner(self.app)

    async def on_status(self, _):
        if not self.app['websockets']:
            return
        self.send_message({
            'type': 'status',
            'height': self.manager.daemon.cached_height(),
        })

    def send_message(self, msg):
        for web_socket in self.app['websockets']:
            asyncio.create_task(web_socket.send_json(msg))

    async def start(self):
        await self.runner.setup()
        await TCPSite(self.runner, self.manager.env.websocket_host, self.manager.env.websocket_port).start()

    async def stop(self):
        await self.runner.cleanup()

    async def on_connect(self, request):
        web_socket = WebSocketResponse()
        await web_socket.prepare(request)
        self.app['websockets'].add(web_socket)
        try:
            async for msg in web_socket:
                if msg.type == WSMsgType.TEXT:
                    await self.on_status(None)
                elif msg.type == WSMsgType.ERROR:
                    print('web socket connection closed with exception %s' %
                          web_socket.exception())
        finally:
            self.app['websockets'].discard(web_socket)
        return web_socket

    @staticmethod
    async def on_shutdown(app):
        for web_socket in set(app['websockets']):
            await web_socket.close(code=WSCloseCode.GOING_AWAY, message='Server shutdown')
