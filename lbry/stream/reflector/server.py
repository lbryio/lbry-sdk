import asyncio
import logging
import typing
import json
from json.decoder import JSONDecodeError
from lbry.stream.descriptor import StreamDescriptor

if typing.TYPE_CHECKING:
    from lbry.blob.blob_file import BlobFile
    from lbry.blob.blob_manager import BlobManager
    from lbry.blob.writer import HashBlobWriter


log = logging.getLogger(__name__)


class ReflectorServerProtocol(asyncio.Protocol):
    def __init__(self, blob_manager: 'BlobManager', response_chunk_size: int = 10000,
                 stop_event: asyncio.Event = None, incoming_event: asyncio.Event = None,
                 not_incoming_event: asyncio.Event = None, partial_needs=False):
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
        self.incoming = incoming_event or asyncio.Event(loop=self.loop)
        self.not_incoming = not_incoming_event or asyncio.Event(loop=self.loop)
        self.stop_event = stop_event or asyncio.Event(loop=self.loop)
        self.chunk_size = response_chunk_size
        self.wait_for_stop_task: typing.Optional[asyncio.Task] = None
        self.partial_needs = partial_needs

    async def wait_for_stop(self):
        await self.stop_event.wait()
        if self.transport:
            self.transport.close()

    def connection_made(self, transport):
        self.transport = transport
        self.wait_for_stop_task = self.loop.create_task(self.wait_for_stop())

    def connection_lost(self, exc):
        if self.wait_for_stop_task:
            self.wait_for_stop_task.cancel()
            self.wait_for_stop_task = None

    def data_received(self, data: bytes):
        if self.incoming.is_set():
            try:
                self.writer.write(data)
            except OSError as err:
                log.error("error receiving blob: %s", err)
                self.transport.close()
            return
        try:
            request = json.loads(data.decode())
        except (ValueError, JSONDecodeError):
            return
        self.loop.create_task(self.handle_request(request))

    def send_response(self, response: typing.Dict):
        def chunk_response(remaining: bytes):
            f = self.loop.create_future()
            f.add_done_callback(lambda _: self.transport.write(remaining[:self.chunk_size]))
            if len(remaining) > self.chunk_size:
                f.add_done_callback(lambda _: self.loop.call_soon(chunk_response, remaining[self.chunk_size:]))
            self.loop.call_soon(f.set_result, None)

        response_bytes = json.dumps(response).encode()
        chunk_response(response_bytes)

    async def handle_request(self, request: typing.Dict):  # pylint: disable=too-many-return-statements
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
                self.writer = self.sd_blob.get_blob_writer(self.transport.get_extra_info('peername'))
                self.not_incoming.clear()
                self.incoming.set()
                self.send_response({"send_sd_blob": True})
                try:
                    await asyncio.wait_for(self.sd_blob.verified.wait(), 30, loop=self.loop)
                    self.descriptor = await StreamDescriptor.from_stream_descriptor_blob(
                        self.loop, self.blob_manager.blob_dir, self.sd_blob
                    )
                    self.send_response({"received_sd_blob": True})
                except asyncio.TimeoutError:
                    self.send_response({"received_sd_blob": False})
                    self.transport.close()
                finally:
                    self.incoming.clear()
                    self.not_incoming.set()
                    self.writer.close_handle()
                    self.writer = None
            else:
                self.descriptor = await StreamDescriptor.from_stream_descriptor_blob(
                    self.loop, self.blob_manager.blob_dir, self.sd_blob
                )
                self.incoming.clear()
                self.not_incoming.set()
                if self.writer:
                    self.writer.close_handle()
                    self.writer = None

                needs = [blob.blob_hash
                         for blob in self.descriptor.blobs[:-1]
                         if not self.blob_manager.get_blob(blob.blob_hash).get_is_verified()]
                print(self.partial_needs, needs)
                if needs and self.partial_needs:
                    needs = needs[:3]
                    self.partial_needs = False
                print(self.partial_needs, needs)
                self.send_response({"send_sd_blob": False, 'needed_blobs': needs})
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
                self.writer = blob.get_blob_writer(self.transport.get_extra_info('peername'))
                self.not_incoming.clear()
                self.incoming.set()
                self.send_response({"send_blob": True})
                try:
                    await asyncio.wait_for(blob.verified.wait(), 30, loop=self.loop)
                    self.send_response({"received_blob": True})
                except asyncio.TimeoutError:
                    self.send_response({"received_blob": False})
                self.incoming.clear()
                self.not_incoming.set()
                self.writer.close_handle()
                self.writer = None
            else:
                self.send_response({"send_blob": False})
            return
        else:
            self.transport.close()


class ReflectorServer:
    def __init__(self, blob_manager: 'BlobManager', response_chunk_size: int = 10000,
                 stop_event: asyncio.Event = None, incoming_event: asyncio.Event = None,
                 not_incoming_event: asyncio.Event = None, partial_needs=False):
        self.loop = asyncio.get_event_loop()
        self.blob_manager = blob_manager
        self.server_task: typing.Optional[asyncio.Task] = None
        self.started_listening = asyncio.Event(loop=self.loop)
        self.stopped_listening = asyncio.Event(loop=self.loop)
        self.incoming_event = incoming_event or asyncio.Event(loop=self.loop)
        self.not_incoming_event = not_incoming_event or asyncio.Event(loop=self.loop)
        self.response_chunk_size = response_chunk_size
        self.stop_event = stop_event
        self.partial_needs = partial_needs  # for testing cases where it doesn't know what it wants

    def start_server(self, port: int, interface: typing.Optional[str] = '0.0.0.0'):
        if self.server_task is not None:
            raise Exception("already running")

        async def _start_server():
            proto = ReflectorServerProtocol(
                self.blob_manager, self.response_chunk_size, self.stop_event, self.incoming_event,
                self.not_incoming_event, self.partial_needs
            )
            server = await self.loop.create_server(lambda: proto, interface, port)
            self.started_listening.set()
            self.stopped_listening.clear()
            log.info("Reflector server listening on TCP %s:%i", interface, port)
            try:
                async with server:
                    await server.serve_forever()
            finally:
                self.stopped_listening.set()

        self.server_task = self.loop.create_task(_start_server())

    def stop_server(self):
        if self.server_task:
            self.server_task.cancel()
            self.server_task = None
            log.info("Stopped reflector server")
