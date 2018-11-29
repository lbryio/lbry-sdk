import os
import binascii
import json
import asyncio
import logging
import typing
from asyncio import StreamReader, StreamWriter, StreamReaderProtocol
from asyncio.base_events import Server
from lbrynet.peer import Peer
from lbrynet.blob.blob_file import BlobFile
from lbrynet.extras.daemon.blob_manager import DiskBlobManager
from lbrynet.blob_exchange.serialization import decode_request, blob_response_types, blob_request_types, BlobDownloadResponse
from lbrynet.blob_exchange.serialization import BlobPriceResponse, BlobAvailabilityResponse, BlobErrorResponse
from lbrynet.blob_exchange.serialization import BlobPriceRequest, BlobAvailabilityRequest, BlobDownloadRequest

log = logging.getLogger(__name__)


async def create_server(loop: asyncio.BaseEventLoop, blob_manager: DiskBlobManager, host: typing.Optional[str] = None,
                        port: typing.Optional[int] = 3333, peer_timeout: typing.Optional[int] = 3) -> Server:

    async def client_connected(reader: StreamReader, writer: StreamWriter):
        # address = writer.get_extra_info('peername')

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

        def send_response(response: blob_response_types):
            writer.write(json.dumps(response.to_dict()).encode())
            await writer.drain()

        availability_request = await get_request()
        assert isinstance(availability_request, BlobAvailabilityRequest)
        available = await blob_manager.completed_blobs(availability_request.requested_blobs).asFuture(loop)
        await send_response(BlobAvailabilityResponse(available_blobs=available))

        price_request = await get_request()
        assert isinstance(price_request, BlobPriceRequest)
        await send_response(BlobPriceResponse(blob_data_payment_rate='RATE_ACCEPTED'))

        while True:
            download_request = await get_request()
            assert isinstance(download_request, BlobDownloadRequest)
            if download_request.requested_blob not in available:
                break
            blob = await blob_manager.get_blob(download_request.requested_blob).asFuture(loop)
            incoming_blob = {'blob_hash': blob.blob_hash, 'length': blob.length}
            await send_response(BlobDownloadResponse(incoming_blob=incoming_blob))
            with open(os.path.join(blob_manager.blob_dir, blob.blob_hash), "rb") as f:
                await loop.sendfile(writer.transport, f)

    return await loop.create_server(
        lambda: StreamReaderProtocol(StreamReader(limit=2**16, loop=loop), client_connected, loop=loop), host, port
    )
