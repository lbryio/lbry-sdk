import asyncio
import logging
import typing
from lbrynet.error import BlobDownloadError
from lbrynet.blob_exchange.serialization import BlobResponse, BlobRequest
if typing.TYPE_CHECKING:
    from lbrynet.peer import Peer
    from lbrynet.blob.blob_file import BlobFile

log = logging.getLogger(__name__)

max_response_size = (2 * (2 ** 20)) + (64 * 2 ** 10)


class BlobExchangeClientProtocol(asyncio.Protocol):
    def __init__(self, peer: 'Peer', loop: asyncio.BaseEventLoop, peer_timeout: typing.Optional[float] = 10):
        self.loop = loop
        self.peer = peer
        self.peer_timeout = peer_timeout
        self.transport: asyncio.Transport = None
        self.write_blob: typing.Callable[[int], None] = None
        self.set_length: typing.Callable[[int], None] = None
        self.get_expected_length: typing.Callable[[], int] = None
        self.finished_blob: asyncio.Future = None
        self._downloading_blob = False
        self._blob_bytes_received = 0
        self._response_fut: asyncio.Future = None
        self._request_lock = asyncio.Lock(loop=self.loop)

    def handle_data_received(self, data: bytes):
        if not self._downloading_blob:
            response = BlobResponse.deserialize(data)
        else:
            response = BlobResponse([], data)
        if not response.responses and response.blob_data and self.write_blob:
                self._blob_bytes_received += len(response.blob_data)
                self.write_blob(response.blob_data)
                self._downloading_blob = True
        elif response.responses and self._response_fut:
            blob_response = response.get_blob_response()
            if blob_response:
                self.set_length(blob_response.length)
            if response.blob_data:
                self._blob_bytes_received += len(response.blob_data)
                self.write_blob(response.blob_data)
            self._response_fut.set_result(response)
        else:
            pass

    def data_received(self, data):
        total = len(data) + self._blob_bytes_received
        if self.get_expected_length and self.get_expected_length() is not None and total > self.get_expected_length():
            self.handle_data_received(data[:len(data) + self._blob_bytes_received - self.get_expected_length()])
            return self.data_received(data[len(data) + self._blob_bytes_received - self.get_expected_length():])
        try:
            return self.handle_data_received(data)
        except BlobDownloadError as err:
            if self._response_fut and not self._response_fut.done():
                self._response_fut.set_exception(err)

    async def _download_blob(self, blob: 'BlobFile') -> bool:
        try:
            writer = blob.open_for_writing(self.peer)
        except OSError:
            # i'm not sure how to fix this race condition - jack
            return False
        self._blob_bytes_received = 0
        self.get_expected_length = blob.get_length
        self.set_length = blob.set_length
        self.write_blob = writer.write
        self._response_fut = asyncio.Future(loop=self.loop)
        self._write_wait = asyncio.Event(loop=self.loop)

        request = BlobRequest.make_request_for_blob_hash(blob.blob_hash)
        downloaded_blob = False
        log.debug("send download request")
        try:
            self.transport.write(request.serialize())
            try:
                response = await asyncio.wait_for(self._response_fut, self.peer_timeout, loop=self.loop)
            except BlobDownloadError:
                return False
            availability_response = response.get_availability_response()
            price_response = response.get_price_response()
            blob_response = response.get_blob_response()
            self._response_fut = None
            if not availability_response or not availability_response.available_blobs:
                return False
            elif availability_response.available_blobs != [blob.blob_hash]:
                return False
            if not price_response or price_response.blob_data_payment_rate != 'RATE_ACCEPTED':
                return False
            if not blob_response:
                return False
            if blob_response.blob_hash != blob.blob_hash:
                return False
            elif blob.length is not None and blob.length != blob_response.length:
                raise Exception("unexpected")
            log.info("downloading %s from %s:%i", blob.blob_hash[:8], self.peer.address, self.peer.tcp_port)
            await asyncio.wait_for(writer.finished, self.peer_timeout, loop=self.loop)
            log.info("await finished writing %s from %s:%i", blob.blob_hash[:8], self.peer.address, self.peer.tcp_port)
            await blob.finished_writing.wait()

            downloaded_blob = True
            log.info(f"downloaded {blob.blob_hash[:8]} from {self.peer.address}")
            return True
        except asyncio.CancelledError:
            log.info(f"download {blob.blob_hash[:8]} from {self.peer.address} cancelled")
        except asyncio.TimeoutError:
            log.info(f"download {blob.blob_hash[:8]} from {self.peer.address} timed out")
        except Exception as err:
            log.error(f"download {blob.blob_hash[:8]} from {self.peer.address} error: {str(err)}")
        finally:
            if not downloaded_blob:
                writer.close_handle()
            self._downloading_blob = False
            self._response_fut = None
            self.write_blob = None
            self.set_length = None
            self._write_wait = None
        return False

    async def download_blob(self, blob: 'BlobFile') -> bool:
        async with self._request_lock:
            return await self._download_blob(blob)

    def connection_made(self, transport: asyncio.Transport):
        log.info("connection made to %s: %s", self.peer, transport)
        self.transport = transport
        self.transport.set_write_buffer_limits((2**20)+(64*20**10))

    def connection_lost(self, reason):
        log.info("connection lost to %s" % self.peer)
        if self._response_fut and not self._response_fut.done():
            self._response_fut.cancel()
        self.transport = None
        self._downloading_blob = False
        self._response_fut = None
        self.write_blob = None
        self.set_length = None
        self._write_wait = None
