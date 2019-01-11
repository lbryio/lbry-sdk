import logging
import json

from asyncio import transports

import lbrynet.extras.reflector.exceptions as err
from lbrynet.extras.reflector import REFLECTOR_V1, REFLECTOR_V2
from lbrynet.extras.reflector.server import ServerProtocol
from typing import Optional, Union, Tuple, Text

from twisted.python import failure
from twisted.internet import error, defer
from twisted.internet.protocol import Protocol, ServerFactory

from lbrynet.blob.blob_file import is_valid_blobhash
from lbrynet.p2p.Error import DownloadCanceledError, InvalidBlobHashError
from lbrynet.p2p.StreamDescriptor import BlobStreamDescriptorReader
from lbrynet.p2p.StreamDescriptor import save_sd_info

log = logging.getLogger(__name__)

MAXIMUM_QUERY_SIZE = 200
SEND_SD_BLOB = 'send_sd_blob'
SEND_BLOB = 'send_blob'
RECEIVED_SD_BLOB = 'received_sd_blob'
RECEIVED_BLOB = 'received_blob'
NEEDED_BLOBS = 'needed_blobs'
VERSION = 'version'
BLOB_SIZE = 'blob_size'
BLOB_HASH = 'blob_hash'
SD_BLOB_SIZE = 'sd_blob_size'
SD_BLOB_HASH = 'sd_blob_hash'


class ReflectorServer(ServerProtocol):
    def __init__(self):
        super().__init__()
        self._transport = None
        self.peer = None
        self.blob_manager = None
        self.storage = None
        self.lbry_file_manager = None
        self.peer_version = None
        self.receiving_blob = None
        self.incoming_blob = None
        self.blob_finished_d = None
        self.request_buff = None
        self.blob_writer = None
        self.response_key = None
        self.descriptor_req = None
        self.descriptor_resp = None
        self.blob_req = None
    
    def connection_made(self, transport: transports.DatagramTransport):
        peer_info = transport.get_extra_info('peerhost')
        log.debug('Connection made to %s', peer_info)
        self._transport = transport
    
    def connection_lost(self, exc: Optional[Exception]):
        log.error(exc.with_traceback(self._transport))
    
    def send_response(self, message):
        self._transport.write(json.dumps(message.encode()))

    # Ingress blob handling
    
    def clean_up_failed_upload(self, exc, blob):
        log.warning('Failed to receive %s', blob)
        # TODO: DownloadCancelledError
        # self.blob_manager.delete_blobs([blob.blob_hash])
        log.exception(exc)

    async def _on_completed_blob(self, blob, response_key):
        await self.blob_manager.blob_completed(blob, should_announce=False)
        if response_key == RECEIVED_SD_BLOB:
            sd_info = await BlobStreamDescriptorReader(blob).get_info()
            await save_sd_info(self.blob_manager, blob.blob_hash, sd_info)
            await self.blob_manager.set_should_announce(blob.blob_hash, True)
        else:
            stream_hash = await self.storage.get_stream_of_blob(blob.blob_hash)
            if stream_hash is not None:
                blob_num = await self.storage.get_blob_num_by_hash(stream_hash, blob.blob_hash)
                if blob_num == 0:
                    await self.blob_manager.set_should_announce(blob.blob_hash, True)
    
        await self.close_blob()
        log.info("Received %s", blob)
        self._transport.write(json.loads({response_key: True}))
        self.response_key = True
    
    async def _on_failed_blob(self, exc, response_key):
        await self.clean_up_failed_upload(exc, self.incoming_blob)
        self._transport.write(json.loads({response_key: False}))
        self.response_key = False
    
    def close_blob(self):
        self.blob_writer.close()
        self.blob_writer = None
        self.blob_finished_d = None
        self.incoming_blob = None
        self.receiving_blob = False
    
    def _get_valid_response(self, response_msg):
        extra_data = None
        response = None
        curr_pos = 0
        while not self.receiving_blob:
            next_close_paren = response_msg.find(b'}', curr_pos)
            if next_close_paren != -1:
                curr_pos = next_close_paren + 1
                try:
                    response = json.loads(response_msg[:curr_pos])
                except ValueError:
                    if curr_pos > MAXIMUM_QUERY_SIZE:
                        raise ValueError("Error decoding response: %s" % str(response_msg))
                    else:
                        pass
                else:
                    extra_data = response_msg[curr_pos:]
                    break
            else:
                break
        return response, extra_data
    
    def handle_incoming_blob(self, message):
        self.response_key = False
        blob = self.incoming_blob
        try:
            self.blob_writer, self.blob_finished_d = blob.open_for_writing(self.peer)
            self._on_completed_blob(blob, message)
        except err.IncompleteResponse:
            self._on_failed_blob(blob, message)
    
    # egress data handling
    
    def datagram_received(self, data: Union[bytes, Text], addr: Tuple[str, int]):
        msg = data.decode()
        message = json.loads(msg)
        if self.receiving_blob:
            self.blob_writer.write(message)
        elif self.response_key:
            self.handle_incoming_blob(message)
        else:
            log.debug('Not yet receiving blob, data needs further processing')
            msg, extra_data = self._get_valid_response(self.request_buff)
            if msg is not None:
                if self.is_descriptor_request(message):
                    sd_blob_hash = message[SD_BLOB_HASH]
                    sd_blob_size = message[SD_BLOB_SIZE]
                    if self.blob_writer is None:
                        sd_blob = await self.blob_manager.get_blob(sd_blob_hash, sd_blob_size)
                        self.get_descriptor_response(sd_blob)
                    else:
                        self.receiving_blob = True
                        await self.blob_finished_d
                if self.is_blob_request(message):
                    blob_hash = message[BLOB_HASH]
                    blob_size = message[BLOB_SIZE]
                    if self.blob_writer is None:
                        log.debug('Received info for blob: %s', blob_hash[:16])
                        blob = await self.blob_manager.get_blob(blob_hash, blob_size)
                        self.get_blob_response(blob)
                    else:
                        log.debug('blob is already open')
                        self.receiving_blob = True
                        await self.blob_finished_d
                raise err.ReflectorRequestError("Invalid request")
            if self.receiving_blob and extra_data:
                log.debug('Writing extra data to blob')
                self.blob_writer.write(extra_data)
    
    def is_descriptor_request(self, message):
        self.descriptor_req = True
        if SD_BLOB_HASH not in message or SD_BLOB_SIZE not in message:
            self.descriptor_req = False
            return
        if not is_valid_blobhash(message[SD_BLOB_HASH]):
            return InvalidBlobHashError(message[SD_BLOB_HASH])
        return

    def is_blob_request(self, message):
        self.blob_req = True
        if BLOB_HASH not in message or BLOB_SIZE not in message:
            self.blob_req = False
            return
        if not is_valid_blobhash(message[BLOB_HASH]):
            return InvalidBlobHashError(message[BLOB_HASH])
        return
    
    def get_blob_response(self, blob):
        if blob.get_is_verified():
            self._transport.write(json.loads({SEND_BLOB: False}))
        else:
            self.incoming_blob = blob
            self.receiving_blob = True
            await self.handle_incoming_blob(RECEIVED_BLOB)
            self._transport.write(json.loads({SEND_BLOB: True}))

    async def get_descriptor_response(self, sd_blob):
        if sd_blob.get_is_verified():
            sd_info = await BlobStreamDescriptorReader(sd_blob).get_info()
            await save_sd_info(self.blob_manager, sd_blob.blob_hash, sd_info)
            await self.storage.verify_will_announce_head_and_sd_blobs(sd_info['stream_hash'])
            self.descriptor_resp = {SEND_SD_BLOB: False}
            await self.request_needed_blobs(sd_info['stream_hash'])
            self.descriptor_resp = None
        else:
            self.incoming_blob = sd_blob
            self.receiving_blob = True
            await self.handle_incoming_blob(RECEIVED_SD_BLOB)
            self.descriptor_resp = {SEND_SD_BLOB: True}
            self._transport.write(json.loads(self.descriptor_resp))
            self.descriptor_resp = None

    async def request_needed_blobs(self, stream_hash):
        needed_blobs = await self.storage.get_pending_blobs_for_stream(stream_hash)
        self._transport.write(json.loads(({NEEDED_BLOBS: needed_blobs})))


class _ReflectorServer(Protocol):
    def connectionMade(self):
        peer_info = self.transport.getPeer()
        log.debug('Connection made to %s', peer_info)
        self.peer = self.factory.peer_manager.get_peer(peer_info.host, peer_info.port)
        self.blob_manager = self.factory.blob_manager
        self.storage = self.factory.blob_manager.storage
        self.lbry_file_manager = self.factory.lbry_file_manager
        self.protocol_version = self.factory.protocol_version
        self.received_handshake = False
        self.peer_version = None
        self.receiving_blob = False
        self.incoming_blob = None
        self.blob_finished_d = None
        self.request_buff = b""
        self.blob_writer = None
    
    def connectionLost(self, reason=failure.Failure(error.ConnectionDone())):
        log.info("Reflector upload from %s finished" % self.peer.host)
    
    def handle_error(self, exc):
        log.error(exc.getTraceback())
        self.transport.loseConnection()

    def send_response(self, response_dict):
        self.transport.write(json.dumps(response_dict).encode())
    
    ############################
    # Incoming blob file stuff #
    ############################

    def clean_up_failed_upload(self, exc, blob):
        log.warning("Failed to receive %s", blob)
        if exc.check(DownloadCanceledError):
            self.blob_manager.delete_blobs([blob.blob_hash])
        else:
            log.exception(exc)

    @defer.inlineCallbacks
    def _on_completed_blob(self, blob, response_key):
        yield self.blob_manager.blob_completed(blob, should_announce=False)
        if response_key == RECEIVED_SD_BLOB:
            sd_info = yield BlobStreamDescriptorReader(blob).get_info()
            yield save_sd_info(self.blob_manager, blob.blob_hash, sd_info)
            yield self.blob_manager.set_should_announce(blob.blob_hash, True)
        else:
            stream_hash = yield self.storage.get_stream_of_blob(blob.blob_hash)
            if stream_hash is not None:
                blob_num = yield self.storage.get_blob_num_by_hash(stream_hash,
                                                                   blob.blob_hash)
                if blob_num == 0:
                    yield self.blob_manager.set_should_announce(blob.blob_hash, True)

        yield self.close_blob()
        log.info("Received %s", blob)
        yield self.send_response({response_key: True})

    @defer.inlineCallbacks
    def _on_failed_blob(self, exc, response_key):
        yield self.clean_up_failed_upload(exc, self.incoming_blob)
        yield self.send_response({response_key: False})

    def handle_incoming_blob(self, response_key):
        """
        Open blob for writing and send a response indicating if the transfer was
        successful when finished.

        response_key will either be received_blob or received_sd_blob
        """

        blob = self.incoming_blob
        self.blob_writer, self.blob_finished_d = blob.open_for_writing(self.peer)
        self.blob_finished_d.addCallback(self._on_completed_blob, response_key)
        self.blob_finished_d.addErrback(self._on_failed_blob, response_key)

    def close_blob(self):
        self.blob_writer.close()
        self.blob_writer = None
        self.blob_finished_d = None
        self.incoming_blob = None
        self.receiving_blob = False

    ####################
    # Request handling #
    ####################

    def dataReceived(self, data):
        if self.receiving_blob:
            self.blob_writer.write(data)
        else:
            log.debug('Not yet receiving blob, data needs further processing')
            self.request_buff += data
            msg, extra_data = self._get_valid_response(self.request_buff)
            if msg is not None:
                self.request_buff = b''
                d = self.handle_request(msg)
                d.addErrback(self.handle_error)
                if self.receiving_blob and extra_data:
                    log.debug('Writing extra data to blob')
                    self.blob_writer.write(extra_data)

    def _get_valid_response(self, response_msg):
        extra_data = None
        response = None
        curr_pos = 0
        while not self.receiving_blob:
            next_close_paren = response_msg.find(b'}', curr_pos)
            if next_close_paren != -1:
                curr_pos = next_close_paren + 1
                try:
                    response = json.loads(response_msg[:curr_pos])
                except ValueError:
                    if curr_pos > MAXIMUM_QUERY_SIZE:
                        raise ValueError("Error decoding response: %s" % str(response_msg))
                    else:
                        pass
                else:
                    extra_data = response_msg[curr_pos:]
                    break
            else:
                break
        return response, extra_data

    def need_handshake(self):
        return self.received_handshake is False

    def is_descriptor_request(self, request_dict):
        if SD_BLOB_HASH not in request_dict or SD_BLOB_SIZE not in request_dict:
            return False
        if not is_valid_blobhash(request_dict[SD_BLOB_HASH]):
            raise InvalidBlobHashError(request_dict[SD_BLOB_HASH])
        return True

    def is_blob_request(self, request_dict):
        if BLOB_HASH not in request_dict or BLOB_SIZE not in request_dict:
            return False
        if not is_valid_blobhash(request_dict[BLOB_HASH]):
            raise InvalidBlobHashError(request_dict[BLOB_HASH])
        return True

    def handle_request(self, request_dict):
        if self.need_handshake():
            return self.handle_handshake(request_dict)
        if self.is_descriptor_request(request_dict):
            return self.handle_descriptor_request(request_dict)
        if self.is_blob_request(request_dict):
            return self.handle_blob_request(request_dict)
        raise err.ReflectorRequestError("Invalid request")

    def handle_handshake(self, request_dict):
        """
        Upon connecting, the client sends a version handshake:
        {
            'version': int,
        }

        The server replies with the same version if it is supported
        {
            'version': int,
        }
        """

        if VERSION not in request_dict:
            raise err.ReflectorRequestError("Client should send version")

        if int(request_dict[VERSION]) not in [REFLECTOR_V1, REFLECTOR_V2]:
            raise err.ReflectorClientVersionError("Unknown version: %i" % int(request_dict[VERSION]))

        self.peer_version = int(request_dict[VERSION])
        log.debug('Handling handshake for client version %i', self.peer_version)
        self.received_handshake = True
        return self.send_handshake_response()

    def send_handshake_response(self):
        d = defer.succeed({VERSION: self.peer_version})
        d.addCallback(self.send_response)
        return d

    def handle_descriptor_request(self, request_dict):
        """
        If the client is reflecting a whole stream, they send a stream descriptor request:
        {
            'sd_blob_hash': str,
            'sd_blob_size': int
        }

        The server indicates if it's aware of this stream already by requesting (or not requesting)
        the stream descriptor blob. If the server has a validated copy of the sd blob, it will
        include the needed_blobs field (a list of blob hashes missing from reflector) in the
        response. If the server does not have the sd blob the needed_blobs field will not be
        included, as the server does not know what blobs it is missing - so the client should send
        all of the blobs in the stream.
        {
            'send_sd_blob': bool
            'needed_blobs': list, conditional
        }


        The client may begin the file transfer of the sd blob if send_sd_blob was True.
        If the client sends the blob, after receiving it the server indicates if the
        transfer was successful:
        {
            'received_sd_blob': bool
        }
        """

        sd_blob_hash = request_dict[SD_BLOB_HASH]
        sd_blob_size = request_dict[SD_BLOB_SIZE]

        if self.blob_writer is None:
            d = self.blob_manager.get_blob(sd_blob_hash, sd_blob_size)
            d.addCallback(self.get_descriptor_response)
            d.addCallback(self.send_response)
        else:
            self.receiving_blob = True
            d = self.blob_finished_d
        return d

    @defer.inlineCallbacks
    def get_descriptor_response(self, sd_blob):
        if sd_blob.get_is_verified():
            sd_info = yield BlobStreamDescriptorReader(sd_blob).get_info()
            yield save_sd_info(self.blob_manager, sd_blob.blob_hash, sd_info)
            yield self.storage.verify_will_announce_head_and_sd_blobs(sd_info['stream_hash'])
            response = yield self.request_needed_blobs({SEND_SD_BLOB: False}, sd_info['stream_hash'])
        else:
            self.incoming_blob = sd_blob
            self.receiving_blob = True
            self.handle_incoming_blob(RECEIVED_SD_BLOB)
            response = {SEND_SD_BLOB: True}
        defer.returnValue(response)

    @defer.inlineCallbacks
    def request_needed_blobs(self, response, stream_hash):
        needed_blobs = yield self.storage.get_pending_blobs_for_stream(stream_hash)
        response.update({NEEDED_BLOBS: needed_blobs})
        defer.returnValue(response)

    def handle_blob_request(self, request_dict):
        """
        A client queries if the server will accept a blob
        {
            'blob_hash': str,
            'blob_size': int
        }

        The server replies, send_blob will be False if the server has a validated copy of the blob:
        {
            'send_blob': bool
        }

        The client may begin the raw blob file transfer if the server replied True.
        If the client sends the blob, the server replies:
        {
            'received_blob': bool
        }
        """

        blob_hash = request_dict[BLOB_HASH]
        blob_size = request_dict[BLOB_SIZE]

        if self.blob_writer is None:
            log.debug('Received info for blob: %s', blob_hash[:16])
            d = self.blob_manager.get_blob(blob_hash, blob_size)
            d.addCallback(self.get_blob_response)
            d.addCallback(self.send_response)
        else:
            log.debug('blob is already open')
            self.receiving_blob = True
            d = self.blob_finished_d
        return d

    def get_blob_response(self, blob):
        if blob.get_is_verified():
            return defer.succeed({SEND_BLOB: False})
        else:
            self.incoming_blob = blob
            self.receiving_blob = True
            self.handle_incoming_blob(RECEIVED_BLOB)
            d = defer.succeed({SEND_BLOB: True})
        return d


class ReflectorServerFactory(ServerFactory):
    protocol = _ReflectorServer

    def __init__(self, peer_manager, blob_manager, lbry_file_manager):
        self.peer_manager = peer_manager
        self.blob_manager = blob_manager
        self.lbry_file_manager = lbry_file_manager
        self.protocol_version = REFLECTOR_V2

    def buildProtocol(self, addr):
        log.debug('Creating a protocol for %s', addr)
        return ServerFactory.buildProtocol(self, addr)
