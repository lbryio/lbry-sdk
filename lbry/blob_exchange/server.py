import asyncio
import binascii
import logging
import socket
import typing
from json.decoder import JSONDecodeError
from lbry.blob_exchange.serialization import BlobResponse, BlobRequest, blob_response_types
from lbry.blob_exchange.serialization import BlobAvailabilityResponse, BlobPriceResponse, BlobDownloadResponse, \
    BlobPaymentAddressResponse

if typing.TYPE_CHECKING:
    from lbry.blob.blob_manager import BlobManager

log = logging.getLogger(__name__)

# a standard request will be 295 bytes
MAX_REQUEST_SIZE = 1200


class BlobServerProtocol(asyncio.Protocol):
    def __init__(self, loop: asyncio.AbstractEventLoop, blob_manager: 'BlobManager', lbrycrd_address: str,
                 idle_timeout: float = 30.0, transfer_timeout: float = 60.0):
        self.loop = loop
        self.blob_manager = blob_manager
        self.idle_timeout = idle_timeout
        self.transfer_timeout = transfer_timeout
        self.server_task: typing.Optional[asyncio.Task] = None
        self.started_listening = asyncio.Event()
        self.buf = b''
        self.transport: typing.Optional[asyncio.Transport] = None
        self.lbrycrd_address = lbrycrd_address
        self.peer_address_and_port: typing.Optional[str] = None
        self.started_transfer = asyncio.Event()
        self.transfer_finished = asyncio.Event()
        self.close_on_idle_task: typing.Optional[asyncio.Task] = None

    async def close_on_idle(self):
        while self.transport:
            try:
                await asyncio.wait_for(self.started_transfer.wait(), self.idle_timeout)
            except asyncio.TimeoutError:
                log.debug("closing idle connection from %s", self.peer_address_and_port)
                return self.close()
            self.started_transfer.clear()
            await self.transfer_finished.wait()
            self.transfer_finished.clear()

    def close(self):
        if self.transport:
            self.transport.close()

    def connection_made(self, transport):
        self.transport = transport
        self.close_on_idle_task = self.loop.create_task(self.close_on_idle())
        self.peer_address_and_port = "%s:%i" % self.transport.get_extra_info('peername')
        self.blob_manager.connection_manager.connection_received(self.peer_address_and_port)
        log.debug("received connection from %s", self.peer_address_and_port)

    def connection_lost(self, exc: typing.Optional[Exception]) -> None:
        log.debug("lost connection from %s", self.peer_address_and_port)
        self.blob_manager.connection_manager.incoming_connection_lost(self.peer_address_and_port)
        self.transport = None
        if self.close_on_idle_task and not self.close_on_idle_task.done():
            self.close_on_idle_task.cancel()
        self.close_on_idle_task = None

    def send_response(self, responses: typing.List[blob_response_types]):
        to_send = []
        while responses:
            to_send.append(responses.pop())
        serialized = BlobResponse(to_send).serialize()
        self.transport.write(serialized)
        self.blob_manager.connection_manager.sent_data(self.peer_address_and_port, len(serialized))

    async def handle_request(self, request: BlobRequest):
        addr = self.transport.get_extra_info('peername')
        peer_address, peer_port = addr

        responses = []
        address_request = request.get_address_request()
        if address_request:
            responses.append(BlobPaymentAddressResponse(lbrycrd_address=self.lbrycrd_address))
        availability_request = request.get_availability_request()
        if availability_request:
            responses.append(BlobAvailabilityResponse(available_blobs=list(set(
                filter(lambda blob_hash: blob_hash in self.blob_manager.completed_blob_hashes,
                       availability_request.requested_blobs)
            ))))
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
                blob_hash = blob.blob_hash[:8]
                log.debug("send %s to %s:%i", blob_hash, peer_address, peer_port)
                self.started_transfer.set()
                try:
                    sent = await asyncio.wait_for(blob.sendfile(self), self.transfer_timeout)
                    if sent and sent > 0:
                        self.blob_manager.connection_manager.sent_data(self.peer_address_and_port, sent)
                        log.info("sent %s (%i bytes) to %s:%i", blob_hash, sent, peer_address, peer_port)
                    else:
                        self.close()
                        log.debug("stopped sending %s to %s:%i", blob_hash, peer_address, peer_port)
                        return
                except (OSError, ValueError, asyncio.TimeoutError) as err:
                    if isinstance(err, asyncio.TimeoutError):
                        log.debug("timed out sending blob %s to %s", blob_hash, peer_address)
                    else:
                        log.warning("could not read blob %s to send %s:%i", blob_hash, peer_address, peer_port)
                    self.close()
                    return
                finally:
                    self.transfer_finished.set()
            else:
                log.info("don't have %s to send %s:%i", blob.blob_hash[:8], peer_address, peer_port)
        if responses and not self.transport.is_closing():
            self.send_response(responses)

    def data_received(self, data):
        request = None
        if len(self.buf) + len(data or b'') >= MAX_REQUEST_SIZE:
            log.warning("request from %s is too large", self.peer_address_and_port)
            self.close()
            return
        if data:
            self.blob_manager.connection_manager.received_data(self.peer_address_and_port, len(data))
            _, separator, remainder = data.rpartition(b'}')
            if not separator:
                self.buf += data
                return
            try:
                request = BlobRequest.deserialize(self.buf + data)
                self.buf = remainder
            except (UnicodeDecodeError, JSONDecodeError):
                log.error("request from %s is not valid json (%i bytes): %s", self.peer_address_and_port,
                          len(self.buf + data), '' if not data else binascii.hexlify(self.buf + data).decode())
                self.close()
                return
        if not request.requests:
            log.error("failed to decode request from %s (%i bytes): %s", self.peer_address_and_port,
                      len(self.buf + data), '' if not data else binascii.hexlify(self.buf + data).decode())
            self.close()
            return
        self.loop.create_task(self.handle_request(request))


class BlobServer:
    def __init__(self, loop: asyncio.AbstractEventLoop, blob_manager: 'BlobManager', lbrycrd_address: str,
                 idle_timeout: float = 30.0, transfer_timeout: float = 60.0):
        self.loop = loop
        self.blob_manager = blob_manager
        self.server_task: typing.Optional[asyncio.Task] = None
        self.started_listening = asyncio.Event()
        self.lbrycrd_address = lbrycrd_address
        self.idle_timeout = idle_timeout
        self.transfer_timeout = transfer_timeout
        self.server_protocol_class = BlobServerProtocol

    def start_server(self, port: int, interface: typing.Optional[str] = '0.0.0.0'):
        if self.server_task is not None:
            raise Exception("already running")

        async def _start_server():
            # checking if the port is in use
            # thx https://stackoverflow.com/a/52872579
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(('localhost', port)) == 0:
                    # the port is already in use!
                    log.error("Failed to bind TCP %s:%d", interface, port)

            server = await self.loop.create_server(
                lambda: self.server_protocol_class(self.loop, self.blob_manager, self.lbrycrd_address,
                                                   self.idle_timeout, self.transfer_timeout),
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
