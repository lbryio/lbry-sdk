import asyncio
import logging
import typing
import json
from json.decoder import JSONDecodeError
from lbrynet.stream.descriptor import StreamDescriptor

if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_file import BlobFile
    from lbrynet.blob.blob_manager import BlobManager
    from lbrynet.blob.writer import HashBlobWriter


log = logging.getLogger(__name__)


class ReflectorServerProtocol(asyncio.Protocol):
    def __init__(self, blob_manager: 'BlobManager'):
        self.loop = asyncio.get_event_loop()
        self.blob_manager = blob_manager
        self.server_task: asyncio.Task = None
        self.started_listening = asyncio.Event(loop=self.loop)
        self.buf = b''
        self.transport: asyncio.StreamWriter = None
        self.writer: typing.Optional['HashBlobWriter'] = None
        self.client_version: typing.Optional[int] = None
        self.descriptor: typing.Optional['StreamDescriptor'] = None
        self.sd_blob: typing.Optional['BlobFile'] = None
        self.received = []
        self.incoming = asyncio.Event(loop=self.loop)

    def connection_made(self, transport):
        self.transport = transport

    def data_received(self, data: bytes):
        if self.incoming.is_set():
            try:
                self.writer.write(data)
            except IOError as err:
                log.error("error receiving blob: %s", err)
                self.transport.close()
            return
        try:
            request = json.loads(data.decode())
        except (ValueError, JSONDecodeError):
            return
        self.loop.create_task(self.handle_request(request))

    def send_response(self, response: typing.Dict):
        self.transport.write(json.dumps(response).encode())

    async def handle_request(self, request: typing.Dict):
        if self.client_version is None:
            if 'version' not in request:
                self.transport.close()
                return
            self.client_version = request['version']
            self.send_response({'version': 1})
            return
        if not self.sd_blob:
            if 'sd_blob_hash' not in request:
                self.transport.close()
                return
            self.sd_blob = self.blob_manager.get_blob(request['sd_blob_hash'], request['sd_blob_size'])
            if not self.sd_blob.get_is_verified():
                self.writer = self.sd_blob.open_for_writing()
                self.incoming.set()
                self.send_response({"send_sd_blob": True})
                try:
                    await asyncio.wait_for(self.sd_blob.finished_writing.wait(), 30, loop=self.loop)
                    self.descriptor = await StreamDescriptor.from_stream_descriptor_blob(
                        self.loop, self.blob_manager.blob_dir, self.sd_blob
                    )
                    self.send_response({"received_sd_blob": True})
                except asyncio.TimeoutError:
                    self.send_response({"received_sd_blob": False})
                    self.transport.close()
                finally:
                    self.incoming.clear()
                    self.writer.close_handle()
                    self.writer = None
            else:
                self.descriptor = await StreamDescriptor.from_stream_descriptor_blob(
                    self.loop, self.blob_manager.blob_dir, self.sd_blob
                )
                self.incoming.clear()
                if self.writer:
                    self.writer.close_handle()
                    self.writer = None
                self.send_response({"send_sd_blob": False, 'needed': [
                    blob.blob_hash for blob in self.descriptor.blobs[:-1]
                    if not self.blob_manager.get_blob(blob.blob_hash).get_is_verified()
                ]})
                return
            return
        elif self.descriptor:
            if 'blob_hash' not in request:
                self.transport.close()
                return
            if request['blob_hash'] not in map(lambda b: b.blob_hash, self.descriptor.blobs[:-1]):
                self.send_response({"send_blob": False})
                return
            blob = self.blob_manager.get_blob(request['blob_hash'], request['blob_size'])
            if not blob.get_is_verified():
                self.writer = blob.open_for_writing()
                self.incoming.set()
                self.send_response({"send_blob": True})
                try:
                    await asyncio.wait_for(blob.finished_writing.wait(), 30, loop=self.loop)
                    self.send_response({"received_blob": True})
                except asyncio.TimeoutError:
                    self.send_response({"received_blob": False})
                self.incoming.clear()
                self.writer.close_handle()
                self.writer = None
            else:
                self.send_response({"send_blob": False})
            return
        else:
            self.transport.close()


class ReflectorServer:
    def __init__(self, blob_manager: 'BlobManager'):
        self.loop = asyncio.get_event_loop()
        self.blob_manager = blob_manager
        self.server_task: asyncio.Task = None
        self.started_listening = asyncio.Event(loop=self.loop)

    def start_server(self, port: int, interface: typing.Optional[str] = '0.0.0.0'):
        if self.server_task is not None:
            raise Exception("already running")

        async def _start_server():
            server = await self.loop.create_server(
                lambda: ReflectorServerProtocol(self.blob_manager),
                interface, port
            )
            self.started_listening.set()
            log.info("Reflector server listening on TCP %s:%i", interface, port)
            async with server:
                await server.serve_forever()

        self.server_task = self.loop.create_task(_start_server())

    def stop_server(self):
        if self.server_task:
            self.server_task.cancel()
            self.server_task = None
            log.info("Stopped reflector server")
