import asyncio
import time
import logging
import typing
import binascii
from typing import Optional
from lbry.error import InvalidBlobHashError, InvalidDataError
from lbry.blob_exchange.serialization import BlobResponse, BlobRequest
from lbry.utils import cache_concurrent
if typing.TYPE_CHECKING:
    from lbry.blob.blob_file import AbstractBlob
    from lbry.blob.writer import HashBlobWriter
    from lbry.connection_manager import ConnectionManager

log = logging.getLogger(__name__)


class BlobExchangeClientProtocol(asyncio.Protocol):
    def __init__(self, loop: asyncio.AbstractEventLoop, peer_timeout: typing.Optional[float] = 10,
                 connection_manager: typing.Optional['ConnectionManager'] = None):
        self.loop = loop
        self.peer_port: typing.Optional[int] = None
        self.peer_address: typing.Optional[str] = None
        self.transport: typing.Optional[asyncio.Transport] = None
        self.peer_timeout = peer_timeout
        self.connection_manager = connection_manager
        self.writer: typing.Optional['HashBlobWriter'] = None
        self.blob: typing.Optional['AbstractBlob'] = None

        self._blob_bytes_received = 0
        self._response_fut: typing.Optional[asyncio.Future] = None
        self.buf = b''

        # this is here to handle the race when the downloader is closed right as response_fut gets a result
        self.closed = asyncio.Event()

    def data_received(self, data: bytes):
        if self.connection_manager:
            if not self.peer_address:
                addr_info = self.transport.get_extra_info('peername')
                self.peer_address, self.peer_port = addr_info
            # assert self.peer_address is not None
            self.connection_manager.received_data(f"{self.peer_address}:{self.peer_port}", len(data))
        if not self.transport or self.transport.is_closing():
            log.warning("transport closing, but got more bytes from %s:%i\n%s", self.peer_address, self.peer_port,
                        binascii.hexlify(data))
            if self._response_fut and not self._response_fut.done():
                self._response_fut.cancel()
            return
        if not self._response_fut:
            log.warning("Protocol received data before expected, probable race on keep alive. Closing transport.")
            return self.close()
        if self._blob_bytes_received and not self.writer.closed():
            return self._write(data)

        response = BlobResponse.deserialize(self.buf + data)
        if not response.responses and not self._response_fut.done():
            self.buf += data
            return
        else:
            self.buf = b''

        if response.responses and self.blob:
            blob_response = response.get_blob_response()
            if blob_response and not blob_response.error and blob_response.blob_hash == self.blob.blob_hash:
                # set the expected length for the incoming blob if we didn't know it
                self.blob.set_length(blob_response.length)
            elif blob_response and not blob_response.error and self.blob.blob_hash != blob_response.blob_hash:
                # the server started sending a blob we didn't request
                log.warning("%s started sending blob we didn't request %s instead of %s", self.peer_address,
                            blob_response.blob_hash, self.blob.blob_hash)
                return
        if response.responses:
            log.debug("got response from %s:%i <- %s", self.peer_address, self.peer_port, response.to_dict())
            # fire the Future with the response to our request
            self._response_fut.set_result(response)
        if response.blob_data and self.writer and not self.writer.closed():
            # log.debug("got %i blob bytes from %s:%i", len(response.blob_data), self.peer_address, self.peer_port)
            # write blob bytes if we're writing a blob and have blob bytes to write
            self._write(response.blob_data)

    def _write(self, data: bytes):
        if len(data) > (self.blob.get_length() - self._blob_bytes_received):
            data = data[:(self.blob.get_length() - self._blob_bytes_received)]
            log.warning("got more than asked from %s:%d, probable sendfile bug", self.peer_address, self.peer_port)
        self._blob_bytes_received += len(data)
        try:
            self.writer.write(data)
        except OSError as err:
            log.error("error downloading blob from %s:%i: %s", self.peer_address, self.peer_port, err)
            if self._response_fut and not self._response_fut.done():
                self._response_fut.set_exception(err)
        except asyncio.TimeoutError as err:
            log.error("%s downloading blob from %s:%i", str(err), self.peer_address, self.peer_port)
            if self._response_fut and not self._response_fut.done():
                self._response_fut.set_exception(err)

    async def _download_blob(self) -> typing.Tuple[int, Optional['BlobExchangeClientProtocol']]:  # pylint: disable=too-many-return-statements
        """
        :return: download success (bool), connected protocol (BlobExchangeClientProtocol)
        """
        start_time = time.perf_counter()
        request = BlobRequest.make_request_for_blob_hash(self.blob.blob_hash)
        blob_hash = self.blob.blob_hash
        if not self.peer_address:
            addr_info = self.transport.get_extra_info('peername')
            self.peer_address, self.peer_port = addr_info
        try:
            msg = request.serialize()
            log.debug("send request to %s:%i -> %s", self.peer_address, self.peer_port, msg.decode())
            self.transport.write(msg)
            if self.connection_manager:
                self.connection_manager.sent_data(f"{self.peer_address}:{self.peer_port}", len(msg))
            response: BlobResponse = await asyncio.wait_for(self._response_fut, self.peer_timeout)
            availability_response = response.get_availability_response()
            price_response = response.get_price_response()
            blob_response = response.get_blob_response()
            if self.closed.is_set():
                msg = f"cancelled blob request for {blob_hash} immediately after we got a response"
                log.warning(msg)
                raise asyncio.CancelledError(msg)
            if (not blob_response or blob_response.error) and\
                    (not availability_response or not availability_response.available_blobs):
                log.warning("%s not in availability response from %s:%i", self.blob.blob_hash, self.peer_address,
                            self.peer_port)
                log.warning(response.to_dict())
                return self._blob_bytes_received, self.close()
            elif availability_response and availability_response.available_blobs and \
                    availability_response.available_blobs != [self.blob.blob_hash]:
                log.warning("blob availability response doesn't match our request from %s:%i",
                            self.peer_address, self.peer_port)
                return self._blob_bytes_received, self.close()
            elif not availability_response:
                log.warning("response from %s:%i did not include an availability response (we requested %s)",
                            self.peer_address, self.peer_port, blob_hash)
                return self._blob_bytes_received, self.close()

            if not price_response or price_response.blob_data_payment_rate != 'RATE_ACCEPTED':
                log.warning("data rate rejected by %s:%i", self.peer_address, self.peer_port)
                return self._blob_bytes_received, self.close()
            if not blob_response or blob_response.error:
                log.warning("blob can't be downloaded from %s:%i", self.peer_address, self.peer_port)
                return self._blob_bytes_received, self.close()
            if not blob_response.error and blob_response.blob_hash != self.blob.blob_hash:
                log.warning("incoming blob hash mismatch from %s:%i", self.peer_address, self.peer_port)
                return self._blob_bytes_received, self.close()
            if self.blob.length is not None and self.blob.length != blob_response.length:
                log.warning("incoming blob unexpected length from %s:%i", self.peer_address, self.peer_port)
                return self._blob_bytes_received, self.close()
            msg = f"downloading {self.blob.blob_hash[:8]} from {self.peer_address}:{self.peer_port}," \
                f" timeout in {self.peer_timeout}"
            log.debug(msg)
            msg = f"downloaded {self.blob.blob_hash[:8]} from {self.peer_address}:{self.peer_port}"
            await asyncio.wait_for(self.writer.finished, self.peer_timeout)
            # wait for the io to finish
            await self.blob.verified.wait()
            log.info("%s at %fMB/s", msg,
                     round((float(self._blob_bytes_received) /
                            float(time.perf_counter() - start_time)) / 1000000.0, 2))
            # await self.blob.finished_writing.wait()  not necessary, but a dangerous change. TODO: is it needed?
            return self._blob_bytes_received, self
        except asyncio.TimeoutError:
            return self._blob_bytes_received, self.close()
        except (InvalidBlobHashError, InvalidDataError):
            log.warning("invalid blob from %s:%i", self.peer_address, self.peer_port)
            return self._blob_bytes_received, self.close()

    def close(self):
        self.closed.set()
        if self._response_fut and not self._response_fut.done():
            self._response_fut.cancel()
        if self.writer and not self.writer.closed():
            self.writer.close_handle()
        self._response_fut = None
        self.writer = None
        self.blob = None
        if self.transport:
            self.transport.close()
        self.transport = None
        self.buf = b''

    async def download_blob(self, blob: 'AbstractBlob') -> typing.Tuple[int, Optional['BlobExchangeClientProtocol']]:
        self.closed.clear()
        blob_hash = blob.blob_hash
        if blob.get_is_verified() or not blob.is_writeable():
            return 0, self
        try:
            self._blob_bytes_received = 0
            self.blob, self.writer = blob, blob.get_blob_writer(self.peer_address, self.peer_port)
            self._response_fut = asyncio.Future()
            return await self._download_blob()
        except OSError:
            # i'm not sure how to fix this race condition - jack
            log.warning("race happened downloading %s from %s:%s", blob_hash, self.peer_address, self.peer_port)
            # return self._blob_bytes_received, self.transport
            raise
        except asyncio.TimeoutError:
            if self._response_fut and not self._response_fut.done():
                self._response_fut.cancel()
            self.close()
            return self._blob_bytes_received, None
        except asyncio.CancelledError:
            self.close()
            raise
        finally:
            if self.writer and not self.writer.closed():
                self.writer.close_handle()
                self.writer = None

    def connection_made(self, transport: asyncio.Transport):
        addr = transport.get_extra_info('peername')
        self.peer_address, self.peer_port = addr[0], addr[1]
        self.transport = transport
        if self.connection_manager:
            self.connection_manager.connection_made(f"{self.peer_address}:{self.peer_port}")
        log.debug("connection made to %s:%i", self.peer_address, self.peer_port)

    def connection_lost(self, exc):
        if self.connection_manager:
            self.connection_manager.outgoing_connection_lost(f"{self.peer_address}:{self.peer_port}")
        log.debug("connection lost to %s:%i (reason: %s, %s)", self.peer_address, self.peer_port, str(exc),
                  str(type(exc)))
        self.close()


@cache_concurrent
async def request_blob(loop: asyncio.AbstractEventLoop, blob: Optional['AbstractBlob'], address: str,
                       tcp_port: int, peer_connect_timeout: float, blob_download_timeout: float,
                       connected_protocol: Optional['BlobExchangeClientProtocol'] = None,
                       connection_id: int = 0, connection_manager: Optional['ConnectionManager'] = None)\
        -> typing.Tuple[int, Optional['BlobExchangeClientProtocol']]:
    """
    Returns [<amount of bytes received>, <client protocol if connected>]
    """

    protocol = connected_protocol
    if not connected_protocol or not connected_protocol.transport or connected_protocol.transport.is_closing():
        connected_protocol = None
        protocol = BlobExchangeClientProtocol(
            loop, blob_download_timeout, connection_manager
        )
    else:
        log.debug("reusing connection for %s:%d", address, tcp_port)
    try:
        if not connected_protocol:
            await asyncio.wait_for(loop.create_connection(lambda: protocol, address, tcp_port),
                                   peer_connect_timeout)
            connected_protocol = protocol
        if blob is None or blob.get_is_verified() or not blob.is_writeable():
            # blob is None happens when we are just opening a connection
            # file exists but not verified means someone is writing right now, give it time, come back later
            return 0, connected_protocol
        return await connected_protocol.download_blob(blob)
    except (asyncio.TimeoutError, ConnectionRefusedError, ConnectionAbortedError, OSError):
        return 0, None
