import asyncio
import json
import logging
import typing

if typing.TYPE_CHECKING:
    from lbry.blob.blob_manager import BlobManager
    from lbry.stream.descriptor import StreamDescriptor

REFLECTOR_V1 = 0
REFLECTOR_V2 = 1

MAX_RESPONSE_SIZE = 2000000

log = logging.getLogger(__name__)


class StreamReflectorClient(asyncio.Protocol):
    def __init__(self, blob_manager: 'BlobManager', descriptor: 'StreamDescriptor'):
        self.loop = asyncio.get_event_loop()
        self.transport: typing.Optional[asyncio.WriteTransport] = None
        self.blob_manager = blob_manager
        self.descriptor = descriptor
        self.response_buff = b''
        self.reflected_blobs = []
        self.connected = asyncio.Event()
        self.response_queue = asyncio.Queue(maxsize=1)
        self.pending_request: typing.Optional[asyncio.Task] = None

    def connection_made(self, transport):
        self.transport = transport
        log.debug("Connected to reflector")
        self.connected.set()

    def connection_lost(self, exc: typing.Optional[Exception]):
        self.transport = None
        self.connected.clear()
        if self.pending_request:
            self.pending_request.cancel()
        if self.reflected_blobs:
            log.info("Finished sending reflector %i blobs", len(self.reflected_blobs))

    def data_received(self, data):
        if len(self.response_buff + (data or b'')) > MAX_RESPONSE_SIZE:
            log.warning("response message to large from reflector server: %i bytes",
                        len(self.response_buff + (data or b'')))
            self.response_buff = b''
            self.transport.close()
            return
        self.response_buff += (data or b'')
        try:
            response = json.loads(self.response_buff.decode())
            self.response_buff = b''
            self.response_queue.put_nowait(response)
        except ValueError:
            if not data:
                log.warning("got undecodable response from reflector server")
                self.response_buff = b''
            return

    async def send_request(self, request_dict: typing.Dict, timeout: int = 180):
        msg = json.dumps(request_dict, sort_keys=True)
        try:
            self.transport.write(msg.encode())
            self.pending_request = self.loop.create_task(asyncio.wait_for(self.response_queue.get(), timeout))
            return await self.pending_request
        except (AttributeError, asyncio.CancelledError) as err:
            # attribute error happens when we transport.write after disconnect
            # cancelled error happens when the pending_request task is cancelled by a disconnect
            if self.transport:
                self.transport.close()
            raise err if isinstance(err, asyncio.CancelledError) else asyncio.CancelledError()
        finally:
            self.pending_request = None

    async def send_handshake(self) -> None:
        response_dict = await self.send_request({'version': REFLECTOR_V2})
        if 'version' not in response_dict:
            raise ValueError("Need protocol version number!")
        server_version = int(response_dict['version'])
        if server_version != REFLECTOR_V2:
            raise ValueError(f"I can't handle protocol version {server_version}!")
        return

    async def send_descriptor(self) -> typing.Tuple[bool, typing.List[str]]:  # returns a list of needed blob hashes
        sd_blob = self.blob_manager.get_blob(self.descriptor.sd_hash)
        assert self.blob_manager.is_blob_verified(self.descriptor.sd_hash), "need to have sd blob to send at this point"
        response = await self.send_request({
            'sd_blob_hash': sd_blob.blob_hash,
            'sd_blob_size': sd_blob.length
        })
        if 'send_sd_blob' not in response:
            raise ValueError("I don't know whether to send the sd blob or not!")
        needed = response.get('needed_blobs', [])
        sent_sd = False
        if response['send_sd_blob']:
            try:
                sent = await sd_blob.sendfile(self)
                if sent == -1:
                    log.warning("failed to send sd blob")
                    raise asyncio.CancelledError()
                received = await asyncio.wait_for(self.response_queue.get(), 30)
            except asyncio.CancelledError as err:
                if self.transport:
                    self.transport.close()
                raise err
            if received.get('received_sd_blob'):
                sent_sd = True
                if not needed:
                    for blob in self.descriptor.blobs[:-1]:
                        if self.blob_manager.is_blob_verified(blob.blob_hash, blob.length):
                            needed.append(blob.blob_hash)
                log.info("Sent reflector descriptor %s", sd_blob.blob_hash[:8])
                self.reflected_blobs.append(sd_blob.blob_hash)
            else:
                log.warning("Reflector failed to receive descriptor %s", sd_blob.blob_hash[:8])
        return sent_sd, needed

    async def send_blob(self, blob_hash: str):
        assert self.blob_manager.is_blob_verified(blob_hash), "need to have a blob to send at this point"
        blob = self.blob_manager.get_blob(blob_hash)
        response = await self.send_request({
            'blob_hash': blob.blob_hash,
            'blob_size': blob.length
        })
        if 'send_blob' not in response:
            raise ValueError("I don't know whether to send the blob or not!")
        if response['send_blob']:
            try:
                sent = await blob.sendfile(self)
                if sent == -1:
                    log.warning("failed to send blob")
                    raise asyncio.CancelledError()
                received = await asyncio.wait_for(self.response_queue.get(), 30)
            except asyncio.CancelledError as err:
                if self.transport:
                    self.transport.close()
                raise err
            if received.get('received_blob'):
                self.reflected_blobs.append(blob.blob_hash)
                log.info("Sent reflector blob %s", blob.blob_hash[:8])
            else:
                log.warning("Reflector failed to receive blob %s", blob.blob_hash[:8])
