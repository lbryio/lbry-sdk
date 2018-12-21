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


async def create_server(loop: asyncio.BaseEventLoop, blob_manager: BlobFileManager, host: typing.Optional[str] = None,
                        port: typing.Optional[int] = 3333, peer_timeout: typing.Optional[int] = 3) -> Server:

    async def client_connected(reader: StreamReader, writer: StreamWriter):
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
                     if blob_hash in blob_manager.completed_blob_hashes]
        await send_response(BlobAvailabilityResponse(available_blobs=available))
        price_request = await get_request()
        assert isinstance(price_request, BlobPriceRequest)
        await send_response(BlobPriceResponse(blob_data_payment_rate='RATE_ACCEPTED'))

        while True:
            download_request = await get_request()
            assert isinstance(download_request, BlobDownloadRequest)
            if download_request.requested_blob not in available:
                break
            blob = blob_manager.get_blob(download_request.requested_blob)
            incoming_blob = {'blob_hash': blob.blob_hash, 'length': blob.length}
            await send_response(BlobDownloadResponse(incoming_blob=incoming_blob))
            with open(os.path.join(blob_manager.blob_dir, blob.blob_hash), "rb") as f:
                await loop.sendfile(writer.transport, f)

    return await loop.create_server(
        lambda: StreamReaderProtocol(StreamReader(limit=2**16, loop=loop), client_connected, loop=loop), host, port
    )
