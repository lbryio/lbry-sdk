import json
import signal
import asyncio
import logging
from weakref import WeakSet
from asyncio.runners import _cancel_all_tasks
from typing import Type

from aiohttp.web import Application, AppRunner, WebSocketResponse, TCPSite, Response
from aiohttp.http_websocket import WSMsgType, WSCloseCode

from lbry.conf import Config
from lbry.console import Console, console_class_from_name
from lbry.service import API, Service
from lbry.service.json_encoder import JSONResponseEncoder
from lbry.blockchain.ledger import ledger_class_from_name


log = logging.getLogger(__name__)


def jsonrpc_dumps_pretty(obj, **kwargs):
    #if not isinstance(obj, dict):
    #    data = {"jsonrpc": "2.0", "error": obj.to_dict()}
    #else:
    data = {"jsonrpc": "2.0", "result": obj}
    return json.dumps(data, cls=JSONResponseEncoder, sort_keys=True, indent=2, **kwargs) + "\n"


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


class WebSocketManager(WebSocketResponse):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def subscribe(self, requested: list, subscriptions):
        for request in requested:
            if request == '*':
                for _, component in subscriptions.items():
                    for _, sockets in component.items():
                        sockets.add(self)
            elif '.' not in request:
                for _, sockets in subscriptions[request].items():
                    sockets.add(self)
            elif request.count('.') == 1:
                component, stream = request.split('.')
                subscriptions[component][stream].add(self)

    def unsubscribe(self, subscriptions):
        for _, component in subscriptions.items():
            for _, sockets in component.items():
                sockets.discard(self)


class Daemon:
    """
    Mostly connects API to aiohttp stuff.
    Handles starting and stopping API
    """
    def __init__(self, service: Service, console: Console):
        self._loop = asyncio.get_running_loop()
        self.service = service
        self.conf = service.conf
        self.console = console
        self.api = API(service)
        self.app = Application()
        self.app['websockets'] = WeakSet()
        self.app['subscriptions'] = {}
        self.components = {}
        #for component in components:
        #    streams = self.app['subscriptions'][component.name] = {}
        #    for event_name, event_stream in component.event_streams.items():
        #        streams[event_name] = WeakSet()
        #        event_stream.listen(partial(self.broadcast_event, component.name, event_name))
        self.app.router.add_get('/ws', self.on_connect)
        self.app.router.add_post('/api', self.on_rpc)
        self.app.on_shutdown.append(self.on_shutdown)
        self.runner = AppRunner(self.app)

    @classmethod
    def from_config(cls, service_class: Type[Service], conf: Config, ) -> 'Daemon':

        async def setup():
            ledger_class = ledger_class_from_name(conf.blockchain)
            ledger = ledger_class(conf)
            service = service_class(ledger)
            console_class = console_class_from_name(conf.console)
            console = console_class(service)
            return cls(service, console)

        return asyncio.new_event_loop().run_until_complete(setup())

    def run(self):
        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            self._loop.add_signal_handler(sig, self._loop.stop)
        try:
            self._loop.run_until_complete(self.start())
            self._loop.run_forever()
        finally:
            try:
                self._loop.run_until_complete(self.stop())
            finally:
                try:
                    _cancel_all_tasks(self._loop)
                    self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                finally:
                    self._loop.close()

    async def start(self):
        self.console.starting()
        await self.runner.setup()
        site = TCPSite(self.runner, self.conf.api_host, self.conf.api_port)
        await site.start()
        await self.service.start()

    async def stop(self):
        await self.service.stop()
        await self.runner.cleanup()

    async def on_rpc(self, request):
        data = await request.json()
        params = data.get('params', {})
        method = getattr(self.api, data['method'])
        result = await method(**params)
        encoded_result = jsonrpc_dumps_pretty(result, service=self.service)
        return Response(
            text=encoded_result,
            content_type='application/json'
        )

    async def on_connect(self, request):
        web_socket = WebSocketManager()
        await web_socket.prepare(request)
        self.app['websockets'].add(web_socket)
        try:
            async for msg in web_socket:
                if msg.type == WSMsgType.TEXT:
                    asyncio.create_task(self.on_message(web_socket, msg.json()))
                elif msg.type == WSMsgType.ERROR:
                    print('web socket connection closed with exception %s' %
                          web_socket.exception())
        finally:
            web_socket.unsubscribe(self.app['subscriptions'])
            self.app['websockets'].discard(web_socket)
        return web_socket

    async def on_message(self, web_socket: WebSocketManager, msg: dict):
        if msg['method'] == 'subscribe':
            streams = msg['streams']
            if isinstance(streams, str):
                streams = [streams]
            web_socket.subscribe(streams, self.app['subscriptions'])
        else:
            params = msg.get('params', {})
            method = getattr(self.api, msg['method'])
            try:
                result = await method(**params)
                encoded_result = jsonrpc_dumps_pretty(result, service=self.service)
                await web_socket.send_json({
                    'id': msg.get('id', ''),
                    'result': encoded_result
                })
            except Exception as e:
                log.exception("RPC error")
                await web_socket.send_json({'id': msg.get('id', ''), 'result': "unexpected error: " + str(e)})
                raise e

    @staticmethod
    async def on_shutdown(app):
        for web_socket in set(app['websockets']):
            await web_socket.close(code=WSCloseCode.GOING_AWAY, message='Server shutdown')

    def broadcast_event(self, module, stream, payload):
        for web_socket in self.app['subscriptions'][module][stream]:
            asyncio.create_task(web_socket.send_json({
                'module': module,
                'stream': stream,
                'payload': payload
            }))

    def broadcast_message(self, msg):
        for web_socket in self.app['websockets']:
            asyncio.create_task(web_socket.send_json({
                'module': 'blockchain_sync',
                'payload': msg
            }))
