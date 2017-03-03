import logging
import json
from twisted.python import failure
from twisted.internet import error, defer
from twisted.internet.protocol import Protocol, ServerFactory
from lbrynet.core.utils import is_valid_blobhash
from lbrynet.core.Error import DownloadCanceledError, InvalidBlobHashError
from lbrynet.reflector.common import REFLECTOR_V1, REFLECTOR_V2
from lbrynet.reflector.common import ReflectorRequestError, ReflectorClientVersionError


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


class ReflectorServer(Protocol):
    def connectionMade(self):
        peer_info = self.transport.getPeer()
        log.debug('Connection made to %s', peer_info)
        self.peer = self.factory.peer_manager.get_peer(peer_info.host, peer_info.port)
        self.blob_manager = self.factory.blob_manager
        self.protocol_version = self.factory.protocol_version
        self.received_handshake = False
        self.peer_version = None
        self.receiving_blob = False
        self.incoming_blob = None
        self.blob_write = None
        self.blob_finished_d = None
        self.cancel_write = None
        self.request_buff = ""

    def connectionLost(self, reason=failure.Failure(error.ConnectionDone())):
        log.info("Reflector upload from %s finished" % self.peer.host)

    def handle_error(self, err):
        log.error(err.getTraceback())
        self.transport.loseConnection()

    def send_response(self, response_dict):
        self.transport.write(json.dumps(response_dict))

    ############################
    # Incoming blob file stuff #
    ############################

    def clean_up_failed_upload(self, err, blob):
        log.warning("Failed to receive %s", blob)
        if err.check(DownloadCanceledError):
            self.blob_manager.delete_blobs([blob.blob_hash])
        else:
            log.exception(err)

    @defer.inlineCallbacks
    def _on_completed_blob(self, blob, response_key):
        yield self.blob_manager.blob_completed(blob)
        yield self.close_blob()
        log.info("Received %s", blob)
        yield self.send_response({response_key: True})

    @defer.inlineCallbacks
    def _on_failed_blob(self, err, response_key):
        yield self.clean_up_failed_upload(err, self.incoming_blob)
        yield self.send_response({response_key: False})

    def handle_incoming_blob(self, response_key):
        """
        Open blob for writing and send a response indicating if the transfer was
        successful when finished.

        response_key will either be received_blob or received_sd_blob
        """

        blob = self.incoming_blob
        self.blob_finished_d, self.blob_write, self.cancel_write = blob.open_for_writing(self.peer)
        self.blob_finished_d.addCallback(self._on_completed_blob, response_key)
        self.blob_finished_d.addErrback(self._on_failed_blob, response_key)

    def close_blob(self):
        self.blob_finished_d = None
        self.blob_write = None
        self.cancel_write = None
        self.incoming_blob = None
        self.receiving_blob = False

    ####################
    # Request handling #
    ####################

    def dataReceived(self, data):
        if self.receiving_blob:
            self.blob_write(data)
        else:
            log.debug('Not yet recieving blob, data needs further processing')
            self.request_buff += data
            msg, extra_data = self._get_valid_response(self.request_buff)
            if msg is not None:
                self.request_buff = ''
                d = self.handle_request(msg)
                d.addErrback(self.handle_error)
                if self.receiving_blob and extra_data:
                    log.debug('Writing extra data to blob')
                    self.blob_write(extra_data)

    def _get_valid_response(self, response_msg):
        extra_data = None
        response = None
        curr_pos = 0
        while not self.receiving_blob:
            next_close_paren = response_msg.find('}', curr_pos)
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
        raise ReflectorRequestError("Invalid request")

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
            raise ReflectorRequestError("Client should send version")

        if int(request_dict[VERSION]) not in [REFLECTOR_V1, REFLECTOR_V2]:
            raise ReflectorClientVersionError("Unknown version: %i" % int(request_dict[VERSION]))

        log.debug('Handling handshake for client version %i', self.peer_version)

        self.peer_version = int(request_dict[VERSION])
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

        if self.blob_write is None:
            d = self.blob_manager.get_blob(sd_blob_hash, length=sd_blob_size)
            d.addCallback(self.get_descriptor_response)
            d.addCallback(self.send_response)
        else:
            self.receiving_blob = True
            d = self.blob_finished_d
        return d

    def get_descriptor_response(self, sd_blob):
        if sd_blob.is_validated():
            d = defer.succeed({SEND_SD_BLOB: False})
            d.addCallback(self.request_needed_blobs, sd_blob)
        else:
            self.incoming_blob = sd_blob
            self.receiving_blob = True
            self.handle_incoming_blob(RECEIVED_SD_BLOB)
            d = defer.succeed({SEND_SD_BLOB: True})
        return d

    def request_needed_blobs(self, response, sd_blob):
        def _add_needed_blobs_to_response(needed_blobs):
            response.update({NEEDED_BLOBS: needed_blobs})
            return response

        d = self.determine_missing_blobs(sd_blob)
        d.addCallback(_add_needed_blobs_to_response)
        return d

    def determine_missing_blobs(self, sd_blob):
        with sd_blob.open_for_reading() as sd_file:
            sd_blob_data = sd_file.read()
        decoded_sd_blob = json.loads(sd_blob_data)
        return self.get_unvalidated_blobs_in_stream(decoded_sd_blob)

    def get_unvalidated_blobs_in_stream(self, sd_blob):
        dl = defer.DeferredList(list(self._iter_unvalidated_blobs_in_stream(sd_blob)),
                                consumeErrors=True)
        dl.addCallback(lambda needed: [blob[1] for blob in needed if blob[1]])
        return dl

    def _iter_unvalidated_blobs_in_stream(self, sd_blob):
        for blob in sd_blob['blobs']:
            if 'blob_hash' in blob and 'length' in blob:
                blob_hash, blob_len = blob['blob_hash'], blob['length']
                d = self.blob_manager.get_blob(blob_hash, blob_len)
                d.addCallback(lambda blob: blob_hash if not blob.is_validated() else None)
                yield d

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

        if self.blob_write is None:
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
        if blob.is_validated():
            return defer.succeed({SEND_BLOB: False})
        else:
            self.incoming_blob = blob
            self.receiving_blob = True
            self.handle_incoming_blob(RECEIVED_BLOB)
            d = defer.succeed({SEND_BLOB: True})
        return d


class ReflectorServerFactory(ServerFactory):
    protocol = ReflectorServer

    def __init__(self, peer_manager, blob_manager):
        self.peer_manager = peer_manager
        self.blob_manager = blob_manager
        self.protocol_version = REFLECTOR_V2

    def buildProtocol(self, addr):
        log.debug('Creating a protocol for %s', addr)
        return ServerFactory.buildProtocol(self, addr)
