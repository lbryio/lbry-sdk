import asyncio
import logging
import typing
from asyncio import StreamReader, StreamWriter
from lbrynet.blob_exchange.serialization import BlobResponse, BlobRequest, blob_response_types
from lbrynet.blob_exchange.serialization import BlobAvailabilityResponse, BlobPriceResponse, BlobDownloadResponse
if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_manager import BlobFileManager


log = logging.getLogger(__name__)


async def read_blob_request(reader: StreamReader) -> typing.Optional[BlobRequest]:
    data = b''
    while True:
        new_bytes = await reader.read()
        if not new_bytes:
            return
        data += new_bytes
        try:
            return BlobRequest.deserialize(data)
        except:
            continue


class BlobServer:
    def __init__(self, loop: asyncio.BaseEventLoop, blob_manager: 'BlobFileManager'):
        self.loop = loop
        self.blob_manager = blob_manager
        self.server_task: asyncio.Task = None

    async def handle_request(self, reader: StreamReader, writer: StreamWriter):
        responses: typing.List[blob_response_types] = []

        async def send_responses():
            to_send = []
            while responses:
                to_send.append(responses.pop())
            writer.write(BlobResponse(to_send).serialize())
            await writer.drain()

        request = await read_blob_request(reader)
        availability_request = request.get_availability_request()
        if availability_request:
            responses.append(BlobAvailabilityResponse(available_blobs=list(set((
                filter(lambda blob_hash: blob_hash in self.blob_manager.completed_blob_hashes,
                        availability_request.requested_blobs)
            )))))
        price_request = request.get_price_request()
        if price_request:
            responses.append(BlobPriceResponse(blob_data_payment_rate='RATE_ACCEPTED'))
        download_request = request.get_blob_request()
        if download_request:
            blob = self.blob_manager.get_blob(download_request.requested_blob)
            if blob.get_is_verified():
                incoming_blob = {'blob_hash': blob.blob_hash, 'length': blob.length}
                responses.append(BlobDownloadResponse(incoming_blob=incoming_blob))
                await send_responses()
                log.info("send %s to %s", blob.blob_hash[:8], writer.get_extra_info('peername'))
                blob_buffer = await blob.read()
                await self.loop.sendfile(writer.transport, blob_buffer)
                log.info("sent %s to %s", blob.blob_hash[:8], writer.get_extra_info('peername'))
        if responses:
            await send_responses()
        writer.close()
        await writer.wait_closed()

    def start_server(self, port: int, interface: typing.Optional[str] = '0.0.0.0'):
        if self.server_task is not None:
            raise Exception("already running")

        async def _start_server():
            server = await asyncio.start_server(self.handle_request, interface, port)
            log.info("Blob server listening on TCP %s:%i", interface, port)
            try:
                await server.wait_closed()
            except asyncio.CancelledError:
                pass
            finally:
                server.close()
            self.server_task = None

        self.server_task = self.loop.create_task(_start_server())

    def stop_server(self):
        if self.server_task:
            self.server_task.cancel()
            self.server_task = None
            log.info("Stopped blob server")
