import asyncio
import logging
import typing
from lbrynet.error import BlobDownloadError
from lbrynet.blob_exchange.serialization import BlobResponse, BlobRequest
if typing.TYPE_CHECKING:
    from lbrynet.peer import Peer
    from lbrynet.blob.blob_file import BlobFile
    from lbrynet.blob.writer import HashBlobWriter

log = logging.getLogger(__name__)

max_response_size = (2 * (2 ** 20)) + (64 * 2 ** 10)


class BlobExchangeClientProtocol(asyncio.Protocol):
    def __init__(self, peer: 'Peer', loop: asyncio.BaseEventLoop, peer_timeout: typing.Optional[float] = 10):
        self.loop = loop
        self.peer = peer
        self.peer_timeout = peer_timeout
        self.transport: asyncio.Transport = None

        self.writer: 'HashBlobWriter' = None
        self.blob: 'BlobFile' = None
        self.download_running = asyncio.Event(loop=self.loop)

        self._blob_bytes_received = 0
        self._response_fut: asyncio.Future = None
        self._request_lock = asyncio.Lock(loop=self.loop)

    def handle_data_received(self, data: bytes):
        if self.transport.is_closing():
            if self._response_fut and not (self._response_fut.done() or self._response_fut.cancelled()):
                self._response_fut.cancel()
            return

        response = BlobResponse.deserialize(data)

        if response.responses and self.blob:
            blob_response = response.get_blob_response()
            if blob_response and blob_response.blob_hash == self.blob.blob_hash:
                self.blob.set_length(blob_response.length)
            elif blob_response and self.blob.blob_hash != blob_response.blob_hash:
                log.warning("mismatch with self.blob %s", self.blob.blob_hash)
                return
        if response.responses:
            self._response_fut.set_result(response)
        if response.blob_data and self.writer and not self.writer.closed():
            # log.info("write blob bytes (%s) from %s:%i", self.blob.blob_hash[:8], self.peer.address, self.peer.tcp_port)
            self._blob_bytes_received += len(response.blob_data)
            self.writer.write(response.blob_data)

    def data_received(self, data):
        total = len(data) + self._blob_bytes_received
        expected_length = self.blob.get_length()

        if expected_length is not None and total > expected_length:
            self.handle_data_received(data[:len(data) + self._blob_bytes_received - expected_length])
            return self.data_received(data[len(data) + self._blob_bytes_received - expected_length:])
        try:
            return self.handle_data_received(data)
        except (asyncio.CancelledError, asyncio.TimeoutError, BlobDownloadError) as err:
            if self._response_fut and not (self._response_fut.done() or self._response_fut.cancelled()):
                self._response_fut.set_exception(err)

    async def _download_blob(self) -> bool:
        request = BlobRequest.make_request_for_blob_hash(self.blob.blob_hash)
        try:
            self.transport.write(request.serialize())
            response: BlobResponse = await asyncio.wait_for(self._response_fut, self.peer_timeout, loop=self.loop)
            availability_response = response.get_availability_response()
            price_response = response.get_price_response()
            blob_response = response.get_blob_response()
            if not availability_response or not availability_response.available_blobs:
                log.warning("blob not in availability response")
                return False
            elif availability_response.available_blobs != [self.blob.blob_hash]:
                log.warning("blob availability response doesn't match our request")
                return False
            if not price_response or price_response.blob_data_payment_rate != 'RATE_ACCEPTED':
                log.warning("data rate rejected")
                return False
            if not blob_response:
                log.warning("blob cant be downloaded from this peer")
                return False
            if blob_response.blob_hash != self.blob.blob_hash:
                log.warning("incoming blob hash mismatch")
                return False
            elif self.blob.length is not None and self.blob.length != blob_response.length:
                log.warning("incoming blob unexpected length")
                raise Exception("unexpected")
            msg = f"downloading {self.blob.blob_hash[:8]} from {self.peer.address}:{self.peer.tcp_port}," \
                f" timeout in {self.peer_timeout}"
            log.info(msg)
            await asyncio.wait_for(self.writer.finished, self.peer_timeout, loop=self.loop)
            log.info("writer finished %s", self.blob.blob_hash[:8])
            await self.blob.finished_writing.wait()
            msg = f"downloaded {self.blob.blob_hash[:8]} from {self.peer.address}"
            log.info(msg)
            return True
        except BlobDownloadError:
            return False
        except asyncio.CancelledError:
            msg = f"download {'None?' if not self.blob else self.blob.blob_hash[:8]} from {self.peer.address} cancelled"
            log.debug(msg)
            if self.transport:
                self.transport.close()
        except asyncio.TimeoutError:
            msg = f"download {'None?' if not self.blob else self.blob.blob_hash[:8]} from {self.peer.address} timed out"
            log.debug(msg)
            if self.transport:
                self.transport.close()
        except Exception:
            msg = f"download {'None?' if not self.blob else self.blob.blob_hash[:8]} from {self.peer.address} failed"
            log.exception(msg)
            if self.transport:
                self.transport.close()
        finally:
            if self.writer and not self.writer.closed():
                self.writer.close_handle()
        return False

    async def download_blob(self, blob: 'BlobFile') -> bool:
        if blob.get_is_verified():
            return False
        async with self._request_lock:
            try:
                if self.download_running.is_set():
                    log.info("wait for download already running")
                    await self.download_running.wait()
                if not self.transport:
                    if self._response_fut and not self._response_fut.done():
                        self._response_fut.cancel()
                    return False
                writer = blob.open_for_writing(self.peer)
                self.download_running.set()
                self.blob = blob
                self.writer = writer
                self._blob_bytes_received = 0
                self._response_fut = asyncio.Future(loop=self.loop)
                return await self._download_blob()
            except OSError:
                log.error("race happened")
                # i'm not sure how to fix this race condition - jack
                return False
            except asyncio.TimeoutError:
                if self._response_fut and not (self._response_fut.done() or self._response_fut.cancelled()):
                    self._response_fut.cancel()
                return False
            except asyncio.CancelledError as error:
                if self._response_fut and not (self._response_fut.done() or self._response_fut.cancelled()):
                    self._response_fut.cancel()
                err = error
        raise err

    def connection_made(self, transport: asyncio.Transport):
        log.info("connection made to %s: %s", self.peer, transport)
        self.transport = transport

    def connection_lost(self, reason):
        log.info("connection lost to %s (reason: %s)", self.peer, reason)
        if self._response_fut and not self._response_fut.done():
            self._response_fut.cancel()
        self.download_running.clear()
        self.transport = None
        self._response_fut = None
        self.writer = None
        self.blob = None
