import asyncio
import binascii
import logging
import typing
from json.decoder import JSONDecodeError
from lbrynet.blob_exchange.serialization import BlobResponse, BlobRequest, blob_response_types
from lbrynet.blob_exchange.serialization import BlobAvailabilityResponse, BlobPriceResponse, BlobDownloadResponse, \
    BlobPaymentAddressResponse

if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_manager import BlobManager

log = logging.getLogger(__name__)


class BlobServerProtocol(asyncio.Protocol):
    def __init__(self, loop: asyncio.BaseEventLoop, blob_manager: 'BlobManager', lbrycrd_address: str):
        self.loop = loop
        self.blob_manager = blob_manager
        self.server_task: asyncio.Task = None
        self.started_listening = asyncio.Event(loop=self.loop)
        self.buf = b''
        self.transport = None
        self.lbrycrd_address = lbrycrd_address

    def connection_made(self, transport):
        self.transport = transport

    def send_response(self, responses: typing.List[blob_response_types]):
        to_send = []
        while responses:
            to_send.append(responses.pop())
        self.transport.write(BlobResponse(to_send).serialize())

    async def handle_request(self, request: BlobRequest):
        addr = self.transport.get_extra_info('peername')
        peer_address, peer_port = addr

        responses = []
        address_request = request.get_address_request()
        if address_request:
            responses.append(BlobPaymentAddressResponse(lbrycrd_address=self.lbrycrd_address))
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
                self.send_response(responses)
                log.debug("send %s to %s:%i", blob.blob_hash[:8], peer_address, peer_port)
                try:
                    sent = await blob.sendfile(self)
                except (ConnectionResetError, BrokenPipeError, RuntimeError, OSError):
                    if self.transport:
                        self.transport.close()
                    return
                log.info("sent %s (%i bytes) to %s:%i", blob.blob_hash[:8], sent, peer_address, peer_port)
        if responses:
            self.send_response(responses)
        # self.transport.close()

    def data_received(self, data):
        request = None
        if data:
            message, separator, remainder = data.rpartition(b'}')
            if not separator:
                self.buf += data
                return
            try:
                request = BlobRequest.deserialize(self.buf + data)
                self.buf = remainder
            except JSONDecodeError:
                addr = self.transport.get_extra_info('peername')
                peer_address, peer_port = addr
                log.error("failed to decode blob request from %s:%i (%i bytes): %s", peer_address, peer_port,
                          len(data), '' if not data else binascii.hexlify(data).decode())
        if not request:
            addr = self.transport.get_extra_info('peername')
            peer_address, peer_port = addr
            log.warning("failed to decode blob request from %s:%i", peer_address, peer_port)
            self.transport.close()
            return
        self.loop.create_task(self.handle_request(request))


class BlobServer:
    def __init__(self, loop: asyncio.BaseEventLoop, blob_manager: 'BlobManager', lbrycrd_address: str):
        self.loop = loop
        self.blob_manager = blob_manager
        self.server_task: asyncio.Task = None
        self.started_listening = asyncio.Event(loop=self.loop)
        self.lbrycrd_address = lbrycrd_address
        self.server_protocol_class = BlobServerProtocol

    def start_server(self, port: int, interface: typing.Optional[str] = '0.0.0.0'):
        if self.server_task is not None:
            raise Exception("already running")

        async def _start_server():
            server = await self.loop.create_server(
                lambda: self.server_protocol_class(self.loop, self.blob_manager, self.lbrycrd_address),
                interface, port
            )
            self.started_listening.set()
            log.info("Blob server listening on TCP %s:%i", interface, port)
            async with server:
                await server.serve_forever()

        self.server_task = self.loop.create_task(_start_server())

    def stop_server(self):
        if self.server_task:
            self.server_task.cancel()
            self.server_task = None
            log.info("Stopped blob server")
