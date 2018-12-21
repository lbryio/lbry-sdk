import json
import asyncio
import logging
import typing
from lbrynet.blob_exchange.serialization import decode_response, BlobDownloadResponse
from lbrynet.blob_exchange.serialization import BlobPriceResponse, BlobAvailabilityResponse, BlobErrorResponse
from lbrynet.blob_exchange.serialization import BlobPriceRequest, BlobAvailabilityRequest, BlobDownloadRequest
if typing.TYPE_CHECKING:
    from lbrynet.peer import Peer
    from lbrynet.blob.blob_file import BlobFile

log = logging.getLogger(__name__)
blob_request_types = typing.Union[BlobPriceRequest, BlobAvailabilityRequest, BlobDownloadRequest]
blob_response_types = typing.Union[BlobPriceResponse, BlobAvailabilityResponse, BlobDownloadResponse]
max_response_size = (2 * (2 ** 20)) + (64 * 2 ** 10)


class BlobExchangeClientProtocol(asyncio.Protocol):
    def __init__(self, peer: 'Peer', loop: asyncio.BaseEventLoop, peer_timeout: typing.Optional[int] = 3):
        self.loop = loop
        self.peer = peer
        self.peer_timeout = peer_timeout
        self.transport: asyncio.Transport = None
        self.write_blob: typing.Callable[[bytes], None] = None
        self.set_blob_length: typing.Callable[[int], None] = None
        self.get_expected_length: typing.Callable[[int], None] = None
        self.finished_blob: asyncio.Future = None
        self._downloading_blob = False
        self._response_buff = b''
        self._response_fut: asyncio.Future = None

    def parse_datagram(self, response_msg: bytes) -> typing.Tuple[typing.Optional[typing.Dict], bytes]:
        # scenarios:
        #   <json>
        #   <blob bytes>
        #   <json><blob bytes>

        self._response_buff += response_msg

        extra_data = b''
        response = None
        curr_pos = 0
        while 1:
            next_close_paren = response_msg.find(b'}', curr_pos)
            if next_close_paren != -1:
                curr_pos = next_close_paren + 1
                try:
                    response = json.loads(response_msg[:curr_pos])
                except ValueError:
                    pass
                else:
                    extra_data = response_msg[curr_pos:]
                    break
            else:
                break
        if response is None and not extra_data:
            extra_data = response_msg
        self._response_buff = extra_data
        return response, extra_data

    def data_received(self, data):
        if len(self._response_buff) > max_response_size:
            log.warning("Response is too large from %s. Size %s",
                        self.peer, len(self._response_buff))
            self.transport.close()
            return
        response, extra_data = self.parse_datagram(data)
        log.debug("decoded response: %s extra: %i", response is not None, len(extra_data))
        if response:
            log.info("%s %i", response, len(extra_data))
            decoded = decode_response(response)
            if self._downloading_blob and len(extra_data):
                assert self.write_blob and self.set_blob_length and isinstance(decoded, BlobDownloadResponse)
                self.set_blob_length(decoded.length)
                log.info("set length %i", decoded.length)
                self._response_fut.add_done_callback(lambda _: self.write_blob(extra_data))

            if isinstance(decoded, BlobErrorResponse):
                self._response_fut.set_exception(Exception(decoded.error))
            else:
                self._response_fut.set_result(decoded)
        else:
            if self._downloading_blob and extra_data:
                assert self.write_blob and self.set_blob_length
                self.write_blob(extra_data)

    async def send_request(self, msg: blob_request_types) -> blob_response_types:
        if self._response_fut:
            await self._response_fut

        self._response_fut = asyncio.Future(loop=self.loop)
        msg_str = json.dumps(msg.to_dict())
        log.info("send %s", json.dumps(msg.to_dict(), indent=2))
        self.transport.write(msg_str.encode())
        result = await asyncio.wait_for(self._response_fut, self.peer_timeout, loop=self.loop)
        self._response_fut = None
        if isinstance(msg, BlobPriceRequest) and not isinstance(result, BlobPriceResponse):
            raise ValueError("invalid response for price request")
        elif isinstance(msg, BlobAvailabilityRequest) and not isinstance(result, BlobAvailabilityResponse):
            raise ValueError("invalid response for availability request")
        elif isinstance(msg, BlobDownloadRequest) and not isinstance(result, BlobDownloadResponse):
            raise ValueError("invalid response for download request")
        return result

    async def request_availability(self, blob_hashes: typing.List[str]) -> typing.List[str]:
        response = await self.send_request(BlobAvailabilityRequest(blob_hashes))
        assert isinstance(response, BlobAvailabilityResponse)
        return response.available_blobs

    async def request_price(self, rate: float) -> typing.List[str]:
        response = await self.send_request(BlobPriceRequest(rate))
        assert isinstance(response, BlobPriceResponse)
        return response.blob_data_payment_rate == 'RATE_ACCEPTED'

    async def request_blob(self, blob: 'BlobFile') -> bool:
        writer = blob.open_for_writing(self.peer)
        self.write_blob = writer.write
        self.set_blob_length = blob.set_length
        self.get_expected_length = blob.get_length
        self._downloading_blob = True
        try:
            await self.send_request(BlobDownloadRequest(blob.blob_hash))
            await asyncio.wait_for(writer.finished, self.peer_timeout, loop=self.loop)
            log.info(f"downloaded {blob.blob_hash[:8]} from {self.peer.address}!")
            return True
        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            log.info(f"download {blob.blob_hash[:8]} from {self.peer.address} timed out")
        except Exception as err:
            log.error(f"download {blob.blob_hash[:8]} from {self.peer.address} error: {str(err)}")
        finally:
            self._downloading_blob = False
            self.write_blob = None
            self.set_blob_length = None
        return False

    def connection_made(self, transport: asyncio.Transport):
        log.info("connection made to %s: %s", self.peer, transport)
        self.transport = transport
        self.transport.set_write_buffer_limits((2**20)+(64*20**10))

    def connection_lost(self, reason):
        log.info("connection lost to %s" % self.peer)
        self.transport = None

    @classmethod
    async def download_blobs(cls, peer: 'Peer', loop: asyncio.BaseEventLoop, blobs: typing.List['BlobFile'],
                 peer_timeout: typing.Optional[int] = 3,
                             peer_connect_timeout: typing.Optional[int] = 1) -> typing.List['BlobFile']:
        p = BlobExchangeClientProtocol(peer, loop, peer_timeout)
        try:
            log.info("connect")
            await asyncio.wait_for(
                asyncio.ensure_future(loop.create_connection(lambda: p, peer.address, peer.tcp_port), loop=loop),
                peer_connect_timeout, loop=loop
            )
            log.info("request availability")
            available = await p.request_availability([b.blob_hash for b in blobs])
            log.info("requested availability: %s", available)
            to_request = [blob for blob in blobs if blob.blob_hash in available]
            if not to_request:
                return []
            accepted = await p.request_price(0.0)
            if not accepted:
                return []
            downloaded = []
            for blob in to_request:
                log.info("download blob from %s", peer.address)
                downloaded_blob = await p.request_blob(blob)
                if downloaded_blob:
                    downloaded.append(blob)
            p.transport.close()
            return downloaded
        except ConnectionRefusedError:
            peer.report_tcp_down()
            return []
        except asyncio.TimeoutError:
            return []
        finally:
            if p.transport:
                p.transport.abort()
