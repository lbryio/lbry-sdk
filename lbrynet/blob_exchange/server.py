import os
import json
import asyncio
import logging
import typing
from asyncio import StreamReader, StreamWriter, StreamReaderProtocol
from asyncio.base_events import Server
from lbrynet.blob.blob_manager import BlobFileManager
from lbrynet.blob_exchange.serialization import decode_request, blob_response_types, BlobDownloadResponse
from lbrynet.blob_exchange.serialization import BlobPriceResponse, BlobAvailabilityResponse
from lbrynet.blob_exchange.serialization import BlobPriceRequest, BlobAvailabilityRequest, BlobDownloadRequest

log = logging.getLogger(__name__)


class BlobServer:
    def __init__(self, loop: asyncio.BaseEventLoop, blob_manager: BlobFileManager):
        self.loop = loop
        self.blob_manager = blob_manager
        self.server_task: asyncio.Task = None

    async def handle_request(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        async def get_request():
            data = b''
            while True:
                new_bytes = await reader.read()
                if not new_bytes:
                    writer.close()
                    await writer.wait_closed()
                data += new_bytes
                try:
                    return decode_request(data)
                except:
                    continue

        async def send_response(response: blob_response_types):
            writer.write(json.dumps(response.to_dict()).encode())
            await writer.drain()

        availability_request = await get_request()
        assert isinstance(availability_request, BlobAvailabilityRequest)
        available = [blob_hash for blob_hash in availability_request.requested_blobs
                     if blob_hash in self.blob_manager.completed_blob_hashes]
        await send_response(BlobAvailabilityResponse(available_blobs=available))
        price_request = await get_request()
        assert isinstance(price_request, BlobPriceRequest)
        await send_response(BlobPriceResponse(blob_data_payment_rate='RATE_ACCEPTED'))

        while True:
            download_request = await get_request()
            assert isinstance(download_request, BlobDownloadRequest)
            if download_request.requested_blob not in available:
                break
            blob = self.blob_manager.get_blob(download_request.requested_blob)
            incoming_blob = {'blob_hash': blob.blob_hash, 'length': blob.length}
            await send_response(BlobDownloadResponse(incoming_blob=incoming_blob))
            with open(blob.file_path, "rb") as f:
                await self.loop.sendfile(writer.transport, f)

    def start_server(self, port: int, interface: typing.Optional[str] = '0.0.0.0'):
        if self.server_task is not None:
            raise Exception("already running")

        async def _start_server():
            server = await asyncio.start_server(self.handle_request, interface, port)
            try:
                await server.wait_closed()
            finally:
                server.close()
            self.server_task = None

        self.server_task = self.loop.create_task(_start_server())
