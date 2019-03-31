import asyncio
import logging
import typing
import binascii
from lbrynet.error import InvalidBlobHashError, InvalidDataError
from lbrynet.blob_exchange.serialization import BlobResponse, BlobRequest
if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_file import AbstractBlob
    from lbrynet.blob.writer import HashBlobWriter

log = logging.getLogger(__name__)


class BlobExchangeClientProtocol(asyncio.Protocol):
    def __init__(self, loop: asyncio.BaseEventLoop, peer_timeout: typing.Optional[float] = 10):
        self.loop = loop
        self.peer_port: typing.Optional[int] = None
        self.peer_address: typing.Optional[str] = None
        self.peer_timeout = peer_timeout
        self.transport: typing.Optional[asyncio.Transport] = None

        self.writer: typing.Optional['HashBlobWriter'] = None
        self.blob: typing.Optional['AbstractBlob'] = None

        self._blob_bytes_received = 0
        self._response_fut: asyncio.Future = None
        self.buf = b''

    def data_received(self, data: bytes):
        log.debug("%s:%d -- got %s bytes -- %s bytes on buffer -- %s blob bytes received",
                  self.peer_address, self.peer_port, len(data), len(self.buf), self._blob_bytes_received)
        if not self.transport or self.transport.is_closing():
            log.warning("transport closing, but got more bytes from %s:%i\n%s", self.peer_address, self.peer_port,
                        binascii.hexlify(data))
            if self._response_fut and not self._response_fut.done():
                self._response_fut.cancel()
            return
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
                log.warning("mismatch with self.blob %s", self.blob.blob_hash)
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
        else:
            data = data
        self._blob_bytes_received += len(data)
        try:
            self.writer.write(data)
        except IOError as err:
            log.error("error downloading blob from %s:%i: %s", self.peer_address, self.peer_port, err)
            if self._response_fut and not self._response_fut.done():
                self._response_fut.set_exception(err)
        except (asyncio.TimeoutError) as err:  # TODO: is this needed?
            log.error("%s downloading blob from %s:%i", str(err), self.peer_address, self.peer_port)
            if self._response_fut and not self._response_fut.done():
                self._response_fut.set_exception(err)

    async def _download_blob(self) -> typing.Tuple[int, typing.Optional[asyncio.Transport]]:
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
                log.warning("%s not in availability response from %s:%i", self.blob.blob_hash, self.peer_address,
                            self.peer_port)
                log.warning(response.to_dict())
                return self._blob_bytes_received, self.close()
            elif availability_response.available_blobs and \
                    availability_response.available_blobs != [self.blob.blob_hash]:
                log.warning("blob availability response doesn't match our request from %s:%i",
                            self.peer_address, self.peer_port)
                return self._blob_bytes_received, self.close()
            if not price_response or price_response.blob_data_payment_rate != 'RATE_ACCEPTED':
                log.warning("data rate rejected by %s:%i", self.peer_address, self.peer_port)
                return self._blob_bytes_received, self.close()
            if not blob_response or blob_response.error:
                log.warning("blob cant be downloaded from %s:%i", self.peer_address, self.peer_port)
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
            await asyncio.wait_for(self.writer.finished, self.peer_timeout, loop=self.loop)
            log.info(msg)
            # await self.blob.finished_writing.wait()  not necessary, but a dangerous change. TODO: is it needed?
            return self._blob_bytes_received, self.transport
        except asyncio.TimeoutError:
            return self._blob_bytes_received, self.close()
        except (InvalidBlobHashError, InvalidDataError):
            log.warning("invalid blob from %s:%i", self.peer_address, self.peer_port)
            return self._blob_bytes_received, self.close()

    def close(self):
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

    async def download_blob(self, blob: 'AbstractBlob') -> typing.Tuple[int, typing.Optional[asyncio.Transport]]:
        if blob.get_is_verified() or not blob.is_writeable():
            return 0, self.transport
        try:
            blob.get_blob_writer()
            self.blob, self.writer, self._blob_bytes_received = blob, blob.get_blob_writer(), 0
            self._response_fut = asyncio.Future(loop=self.loop)
            return await self._download_blob()
        except OSError as e:
            log.error("race happened downloading from %s:%i", self.peer_address, self.peer_port)
            # i'm not sure how to fix this race condition - jack
            log.exception(e)
            return self._blob_bytes_received, self.transport
        except asyncio.TimeoutError:
            if self._response_fut and not self._response_fut.done():
                self._response_fut.cancel()
            self.close()
            return self._blob_bytes_received, None
        except asyncio.CancelledError:
            self.close()
            raise

    def connection_made(self, transport: asyncio.Transport):
        self.transport = transport
        self.peer_address, self.peer_port = self.transport.get_extra_info('peername')
        log.debug("connection made to %s:%i", self.peer_address, self.peer_port)

    def connection_lost(self, reason):
        log.debug("connection lost to %s:%i (reason: %s, %s)", self.peer_address, self.peer_port, str(reason),
                  str(type(reason)))
        self.close()


async def request_blob(loop: asyncio.BaseEventLoop, blob: 'AbstractBlob', address: str, tcp_port: int,
                       peer_connect_timeout: float, blob_download_timeout: float,
                       connected_transport: asyncio.Transport = None)\
        -> typing.Tuple[int, typing.Optional[asyncio.Transport]]:
    """
    Returns [<downloaded blob>, <keep connection>]
    """

    protocol = BlobExchangeClientProtocol(loop, blob_download_timeout)
    if connected_transport and not connected_transport.is_closing():
        connected_transport.set_protocol(protocol)
        protocol.connection_made(connected_transport)
        log.debug("reusing connection for %s:%d", address, tcp_port)
    else:
        connected_transport = None
    try:
        if not connected_transport:
            await asyncio.wait_for(loop.create_connection(lambda: protocol, address, tcp_port),
                                   peer_connect_timeout, loop=loop)
        if blob.get_is_verified() or not blob.is_writeable():
            # file exists but not verified means someone is writing right now, give it time, come back later
            return 0, connected_transport
        return await protocol.download_blob(blob)
    except (asyncio.TimeoutError, ConnectionRefusedError, ConnectionAbortedError, OSError):
        return 0, None
