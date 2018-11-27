import binascii
import json
import asyncio
import logging
import typing
from lbrynet.peer import Peer
from lbrynet.blob.blob_file import BlobFile
from lbrynet.blob_exchange.serialization import decode_response, BlobDownloadResponse
from lbrynet.blob_exchange.serialization import BlobPriceResponse, BlobAvailabilityResponse, BlobErrorResponse
from lbrynet.blob_exchange.serialization import BlobPriceRequest, BlobAvailabilityRequest, BlobDownloadRequest
from lbrynet.dht.node import Node

log = logging.getLogger(__name__)
blob_request_types = typing.Union[BlobPriceRequest, BlobAvailabilityRequest, BlobDownloadRequest]
blob_response_types = typing.Union[BlobPriceResponse, BlobAvailabilityResponse, BlobDownloadResponse]


class BlobExchangeClientProtocol(asyncio.Protocol):
    def __init__(self, peer: Peer, loop: asyncio.BaseEventLoop, peer_timeout: typing.Optional[int] = 3):
        self.loop = loop
        self.peer = peer
        self.peer_timeout = peer_timeout
        self.transport: asyncio.Transport = None
        self.write_blob: typing.Callable[[bytes], None] = None
        self.set_blob_length: typing.Callable[[int], None] = None
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
        # if len(self._response_buff) > conf.settings['MAX_RESPONSE_INFO_SIZE']:
        #     log.warning("Response is too large from %s. Size %s",
        #                 self.peer, len(self._response_buff))
        #     self.transport.close()
        #     return
        response, extra_data = self.parse_datagram(data)
        log.debug("decoded response: %s extra: %i", response is not None, len(extra_data))
        if response is not None:
            decoded = decode_response(response)
            if self._downloading_blob and len(extra_data):
                assert self.write_blob and self.set_blob_length and isinstance(decoded, BlobDownloadResponse)
                self.set_blob_length(decoded.length)
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

        self._response_fut = asyncio.Future()
        self.transport.write(json.dumps(msg.to_dict()).encode())
        result = await asyncio.wait_for(self._response_fut, 2)
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

    async def request_blob(self, blob: BlobFile) -> bool:
        writer, f_d = blob.open_for_writing(self.peer)
        assert f_d is not None
        self.write_blob = writer.write
        self.set_blob_length = blob.set_length
        self._downloading_blob = True

        try:
            await self.send_request(BlobDownloadRequest(blob.blob_hash))
            await f_d.asFuture(self.loop)
            return True
        except asyncio.TimeoutError:
            pass
        finally:
            self._downloading_blob = False
            self.write_blob = None
            self.set_blob_length = None
        return False

    def connection_made(self, transport: asyncio.Transport):
        log.info("connection made to %s: %s", self.peer, transport)
        self.transport = transport

    def connection_lost(self, reason):
        log.info("connection lost to %s" % self.peer)
        self.transport = None

    @classmethod
    async def download_blobs(cls, peer: Peer, loop: asyncio.BaseEventLoop, blobs: typing.List[BlobFile],
                 peer_timeout: typing.Optional[int] = 3,
                             peer_connect_timeout: typing.Optional[int] = 1) -> typing.List[BlobFile]:
        p = BlobExchangeClientProtocol(peer, loop, peer_timeout)
        try:
            await asyncio.wait_for(
                asyncio.ensure_future(loop.create_connection(lambda: p, peer.address, peer.tcp_port)),
                peer_connect_timeout
            )
            available = await p.request_availability([b.blob_hash for b in blobs])
            to_request = [blob for blob in blobs if blob.blob_hash in available]
            if not to_request:
                return []
            accepted = await p.request_price(0.0)
            if not accepted:
                return []
            downloaded = []
            for blob in to_request:
                downloaded_blob = await p.request_blob(blob)
                if downloaded_blob:
                    downloaded.append(blob)
            return downloaded
        except asyncio.TimeoutError:
            return []
        finally:
            if p.transport:
                p.transport.abort()


async def download_single_blob(node: Node, blob: BlobFile, peer_timeout: typing.Optional[int] = 3,
                               peer_connect_timeout: typing.Optional[int] = 1):
    blob_protocols: typing.Dict[Peer, asyncio.Future] = {}

    finished = asyncio.Future()

    def cancel_others(peer: Peer):
        def _cancel_others(f: asyncio.Future):
            nonlocal blob_protocols, finished
            result = f.result()
            if len(result):
                while blob_protocols:
                    other_peer, f = blob_protocols.popitem()
                    if other_peer is not peer and not f.done() and not f.cancelled():
                        f.cancel()
                log.info("downloaded from %s", peer)
                finished.set_result(peer)
            else:
                log.info("failed to download from %s", peer)
        return _cancel_others

    async def download_blob():
        nonlocal blob_protocols
        iterator = node.get_iterative_value_finder(binascii.unhexlify(blob.blob_hash.encode()), bottom_out_limit=5)
        async for peers in iterator:
            for peer in peers:
                print("download from %s" % peer)
                if peer not in blob_protocols:
                    task = asyncio.ensure_future(asyncio.create_task(BlobExchangeClientProtocol.download_blobs(
                        peer, node.loop, [blob], peer_timeout, peer_connect_timeout
                    )))
                    task.add_done_callback(cancel_others(peer))
                    blob_protocols[peer] = task

    download_task = asyncio.create_task(download_blob())

    def cancel_download_task(_):
        nonlocal download_task
        if not download_task.cancelled() and not download_task.done():
            download_task.cancel()
        log.info("finished search!")

    finished.add_done_callback(cancel_download_task)

    return await finished
