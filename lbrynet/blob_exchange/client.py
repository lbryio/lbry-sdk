import asyncio
import logging
import typing
import binascii
from lbrynet.blob_exchange.serialization import BlobResponse, BlobRequest
if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_file import BlobFile
    from lbrynet.blob.writer import HashBlobWriter

log = logging.getLogger(__name__)


class BlobExchangeClientProtocol(asyncio.Protocol):
    def __init__(self, loop: asyncio.BaseEventLoop, peer_timeout: typing.Optional[float] = 10):
        self.loop = loop
        self.peer_port: typing.Optional[int] = None
        self.peer_address: typing.Optional[str] = None
        self.peer_timeout = peer_timeout
        self.transport: asyncio.Transport = None

        self.writer: 'HashBlobWriter' = None
        self.blob: 'BlobFile' = None

        self._blob_bytes_received = 0
        self._response_fut: asyncio.Future = None
        self._request_lock = asyncio.Lock(loop=self.loop)

    def data_received(self, data: bytes):
        if not self.transport or self.transport.is_closing():
            log.warning("transport closing, but got more bytes from %s:%i\n%s", self.peer_address, self.peer_port,
                        binascii.hexlify(data))
            if self._response_fut and not self._response_fut.done():
                self._response_fut.cancel()
            return

        response = BlobResponse.deserialize(data)

        if response.responses and self.blob:
            blob_response = response.get_blob_response()
            if blob_response and not blob_response.error and blob_response.blob_hash == self.blob.blob_hash:
                # set the expected length for the incoming blob if we didn't know it
                self.blob.set_length(blob_response.length)
            elif blob_response and not blob_response.error and self.blob.blob_hash != blob_response.blob_hash:
                # the server started sending a blob we didn't request
                log.warning("mismatch with self.blob %s", self.blob.blob_hash)
                return
        if response.responses:
            log.debug("got response from %s:%i <- %s", self.peer_address, self.peer_port, response.to_dict())
            # fire the Future with the response to our request
            self._response_fut.set_result(response)
        if response.blob_data and self.writer and not self.writer.closed():
            log.debug("got %i blob bytes from %s:%i", len(response.blob_data), self.peer_address, self.peer_port)
            # write blob bytes if we're writing a blob and have blob bytes to write
            self._blob_bytes_received += len(response.blob_data)
            try:
                self.writer.write(response.blob_data)
                return
            except IOError as err:
                log.error("error downloading blob from %s:%i: %s", self.peer_address, self.peer_port, err)
                if self._response_fut and not self._response_fut.done():
                    self._response_fut.set_exception(err)
            except (asyncio.CancelledError, asyncio.TimeoutError) as err:  # TODO: is this needed?
                log.error("%s downloading blob from %s:%i", str(err), self.peer_address, self.peer_port)
                if self._response_fut and not self._response_fut.done():
                    self._response_fut.set_exception(err)

    async def _download_blob(self) -> typing.Tuple[bool, bool]:
        """
        :return: download success (bool), keep connection (bool)
        """
        request = BlobRequest.make_request_for_blob_hash(self.blob.blob_hash)
        try:
            msg = request.serialize()
            log.debug("send request to %s:%i -> %s", self.peer_address, self.peer_port, msg.decode())
            self.transport.write(msg)
            response: BlobResponse = await asyncio.wait_for(self._response_fut, self.peer_timeout, loop=self.loop)
            availability_response = response.get_availability_response()
            price_response = response.get_price_response()
            blob_response = response.get_blob_response()
            if (not blob_response or blob_response.error) and\
                    (not availability_response or not availability_response.available_blobs):
                log.warning("blob not in availability response from %s:%i", self.peer_address, self.peer_port)
                return False, True
            elif availability_response.available_blobs and \
                    availability_response.available_blobs != [self.blob.blob_hash]:
                log.warning("blob availability response doesn't match our request from %s:%i",
                            self.peer_address, self.peer_port)
                return False, False
            if not price_response or price_response.blob_data_payment_rate != 'RATE_ACCEPTED':
                log.warning("data rate rejected by %s:%i", self.peer_address, self.peer_port)
                return False, False
            if not blob_response or blob_response.error:
                log.warning("blob cant be downloaded from %s:%i", self.peer_address, self.peer_port)
                return False, True
            if not blob_response.error and blob_response.blob_hash != self.blob.blob_hash:
                log.warning("incoming blob hash mismatch from %s:%i", self.peer_address, self.peer_port)
                return False, False
            if self.blob.length is not None and self.blob.length != blob_response.length:
                log.warning("incoming blob unexpected length from %s:%i", self.peer_address, self.peer_port)
                return False, False
            msg = f"downloading {self.blob.blob_hash[:8]} from {self.peer_address}:{self.peer_port}," \
                f" timeout in {self.peer_timeout}"
            log.debug(msg)
            msg = f"downloaded {self.blob.blob_hash[:8]} from {self.peer_address}:{self.peer_port}"
            await asyncio.wait_for(self.writer.finished, self.peer_timeout, loop=self.loop)
            await self.blob.finished_writing.wait()
            log.info(msg)
            return True, True
        except asyncio.CancelledError:
            return False, True
        except asyncio.TimeoutError:
            return False, False
        finally:
            await self.close()

    async def close(self):
        if self._response_fut and not self._response_fut.done():
            self._response_fut.cancel()
        if self.writer and not self.writer.closed():
            self.writer.close_handle()
        if self.blob:
            await self.blob.close()
        self._response_fut = None
        self.writer = None
        self.blob = None
        if self.transport:
            self.transport.close()
        self.transport = None

    async def download_blob(self, blob: 'BlobFile') -> typing.Tuple[bool, bool]:
        if blob.get_is_verified():
            return False, True
        async with self._request_lock:
            try:
                self.blob, self.writer, self._blob_bytes_received = blob, blob.open_for_writing(), 0
                self._response_fut = asyncio.Future(loop=self.loop)
                return await self._download_blob()
            except OSError:
                log.error("race happened downloading from %s:%i", self.peer_address, self.peer_port)
                # i'm not sure how to fix this race condition - jack
                return False, True
            except asyncio.TimeoutError:
                if self._response_fut and not self._response_fut.done():
                    self._response_fut.cancel()
                return False, False
            except asyncio.CancelledError:
                if self._response_fut and not self._response_fut.done():
                    self._response_fut.cancel()
                return False, True

    def connection_made(self, transport: asyncio.Transport):
        self.transport = transport
        self.peer_address, self.peer_port = self.transport.get_extra_info('peername')
        log.debug("connection made to %s:%i", self.peer_address, self.peer_port)

    def connection_lost(self, reason):
        log.debug("connection lost to %s:%i (reason: %s, %s)", self.peer_address, self.peer_port, str(reason),
                  str(type(reason)))
        self.transport = None
        self.loop.create_task(self.close())


async def request_blob(loop: asyncio.BaseEventLoop, blob: 'BlobFile', protocol: 'BlobExchangeClientProtocol',
                       address: str, tcp_port: int, peer_connect_timeout: float) -> typing.Tuple[bool, bool]:
    """
    Returns [<downloaded blob>, <keep connection>]
    """
    if blob.get_is_verified():
        return False, True
    try:
        await asyncio.wait_for(loop.create_connection(lambda: protocol, address, tcp_port),
                               peer_connect_timeout, loop=loop)
        return await protocol.download_blob(blob)
    except (asyncio.TimeoutError, asyncio.CancelledError, ConnectionRefusedError, ConnectionAbortedError, OSError):
        return False, False
