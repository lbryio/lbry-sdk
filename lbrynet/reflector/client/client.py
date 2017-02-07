import json
import logging

from twisted.internet.error import ConnectionRefusedError
from twisted.protocols.basic import FileSender
from twisted.internet.protocol import Protocol, ClientFactory
from twisted.internet import defer, error

from lbrynet.reflector.common import IncompleteResponse, ReflectorRequestError
from lbrynet.reflector.common import REFLECTOR_V1, REFLECTOR_V2

log = logging.getLogger(__name__)


class EncryptedFileReflectorClient(Protocol):
    #  Protocol stuff
    def connectionMade(self):
        log.debug("Connected to reflector")
        self.blob_manager = self.factory.blob_manager
        self.response_buff = ''
        self.outgoing_buff = ''
        self.blob_hashes_to_send = []
        self.next_blob_to_send = None
        self.read_handle = None
        self.sent_stream_info = False
        self.received_descriptor_response = False
        self.protocol_version = self.factory.protocol_version
        self.received_server_version = False
        self.server_version = None
        self.stream_descriptor = None
        self.descriptor_needed = None
        self.needed_blobs = []
        self.reflected_blobs = []
        self.file_sender = None
        self.producer = None
        self.streaming = False
        d = self.load_descriptor()
        d.addCallback(lambda _: self.send_handshake())
        d.addErrback(
            lambda err: log.warning("An error occurred immediately: %s", err.getTraceback()))

    def dataReceived(self, data):
        self.response_buff += data
        try:
            msg = self.parse_response(self.response_buff)
        except IncompleteResponse:
            pass
        else:
            self.response_buff = ''
            d = self.handle_response(msg)
            d.addCallback(lambda _: self.send_next_request())
            d.addErrback(self.response_failure_handler)

    def connectionLost(self, reason):
        if reason.check(error.ConnectionDone):
            log.debug('Finished sending data via reflector')
            self.factory.finished_deferred.callback(self.reflected_blobs)
        else:
            log.debug('Reflector finished: %s', reason)
            self.factory.finished_deferred.callback(reason)

    #  IConsumer stuff

    def registerProducer(self, producer, streaming):
        self.producer = producer
        self.streaming = streaming
        if self.streaming is False:
            from twisted.internet import reactor
            reactor.callLater(0, self.producer.resumeProducing)

    def unregisterProducer(self):
        self.producer = None

    def write(self, data):
        self.transport.write(data)
        if self.producer is not None and self.streaming is False:
            from twisted.internet import reactor
            reactor.callLater(0, self.producer.resumeProducing)

    def get_validated_blobs(self, blobs_in_stream):
        def get_blobs(blobs):
            for (blob, _, _, blob_len) in blobs:
                if blob:
                    yield self.blob_manager.get_blob(blob, True, blob_len)

        dl = defer.DeferredList(list(get_blobs(blobs_in_stream)), consumeErrors=True)
        dl.addCallback(lambda blobs: [blob for r, blob in blobs if r and blob.is_validated()])
        return dl

    def set_blobs_to_send(self, blobs_to_send):
        for blob in blobs_to_send:
            if blob not in self.blob_hashes_to_send:
                self.blob_hashes_to_send.append(blob)

    def get_blobs_to_send(self):
        def _show_missing_blobs(filtered):
            if filtered:
                needs_desc = "" if not self.descriptor_needed else "descriptor and "
                log.info("Reflector needs %s%i blobs for %s",
                         needs_desc,
                         len(filtered),
                         str(self.stream_descriptor)[:16])
            return filtered

        d = self.factory.stream_info_manager.get_blobs_for_stream(self.factory.stream_hash)
        d.addCallback(self.get_validated_blobs)
        if not self.descriptor_needed:
            d.addCallback(lambda filtered:
                          [blob for blob in filtered if blob.blob_hash in self.needed_blobs])
        d.addCallback(_show_missing_blobs)
        d.addCallback(self.set_blobs_to_send)
        return d

    def send_request(self, request_dict):
        self.write(json.dumps(request_dict))

    def send_handshake(self):
        self.send_request({'version': self.protocol_version})

    def load_descriptor(self):
        def _save_descriptor_blob(sd_blob):
            self.stream_descriptor = sd_blob

        d = self.factory.stream_info_manager.get_sd_blob_hashes_for_stream(self.factory.stream_hash)
        d.addCallback(lambda sd: self.factory.blob_manager.get_blob(sd[0], True))
        d.addCallback(_save_descriptor_blob)
        return d

    def parse_response(self, buff):
        try:
            return json.loads(buff)
        except ValueError:
            raise IncompleteResponse()

    def response_failure_handler(self, err):
        log.warning("An error occurred handling the response: %s", err.getTraceback())

    def handle_response(self, response_dict):
        if not self.received_server_version:
            return self.handle_handshake_response(response_dict)
        elif not self.received_descriptor_response and self.server_version == REFLECTOR_V2:
            return self.handle_descriptor_response(response_dict)
        else:
            return self.handle_normal_response(response_dict)

    def set_not_uploading(self):
        if self.next_blob_to_send is not None:
            log.debug("Close %s", self.next_blob_to_send)
            self.next_blob_to_send.close_read_handle(self.read_handle)
            self.read_handle = None
            self.next_blob_to_send = None
        self.file_sender.stopProducing()
        self.file_sender = None
        return defer.succeed(None)

    def start_transfer(self):
        assert self.read_handle is not None, \
            "self.read_handle was None when trying to start the transfer"
        d = self.file_sender.beginFileTransfer(self.read_handle, self)
        return d

    def handle_handshake_response(self, response_dict):
        if 'version' not in response_dict:
            raise ValueError("Need protocol version number!")
        self.server_version = int(response_dict['version'])
        if self.server_version not in [REFLECTOR_V1, REFLECTOR_V2]:
            raise ValueError("I can't handle protocol version {}!".format(self.server_version))
        self.received_server_version = True
        return defer.succeed(True)

    def handle_descriptor_response(self, response_dict):
        if self.file_sender is None:  # Expecting Server Info Response
            if 'send_sd_blob' not in response_dict:
                raise ReflectorRequestError("I don't know whether to send the sd blob or not!")
            if response_dict['send_sd_blob'] is True:
                self.file_sender = FileSender()
            else:
                self.received_descriptor_response = True
            self.descriptor_needed = response_dict['send_sd_blob']
            self.needed_blobs = response_dict.get('needed_blobs', [])
            return self.get_blobs_to_send()
        else:  # Expecting Server Blob Response
            if 'received_sd_blob' not in response_dict:
                raise ValueError("I don't know if the sd blob made it to the intended destination!")
            else:
                self.received_descriptor_response = True
                if response_dict['received_sd_blob']:
                    self.reflected_blobs.append(self.next_blob_to_send.blob_hash)
                    log.info("Sent reflector descriptor %s", self.next_blob_to_send.blob_hash[:16])
                else:
                    log.warning("Reflector failed to receive descriptor %s, trying again later",
                                self.next_blob_to_send.blob_hash[:16])
                    self.blob_hashes_to_send.append(self.next_blob_to_send.blob_hash)
                return self.set_not_uploading()

    def handle_normal_response(self, response_dict):
        if self.file_sender is None:  # Expecting Server Info Response
            if 'send_blob' not in response_dict:
                raise ValueError("I don't know whether to send the blob or not!")
            if response_dict['send_blob'] is True:
                self.file_sender = FileSender()
                return defer.succeed(True)
            else:
                log.warning("Reflector already has %s", self.next_blob_to_send.blob_hash[:16])
                return self.set_not_uploading()
        else:  # Expecting Server Blob Response
            if 'received_blob' not in response_dict:
                raise ValueError("I don't know if the blob made it to the intended destination!")
            else:
                if response_dict['received_blob']:
                    self.reflected_blobs.append(self.next_blob_to_send.blob_hash)
                    log.info("Sent reflector blob %s", self.next_blob_to_send.blob_hash[:16])
                else:
                    log.warning("Reflector failed to receive blob %s, trying again later",
                                self.next_blob_to_send.blob_hash[:16])
                    self.blob_hashes_to_send.append(self.next_blob_to_send.blob_hash)
                return self.set_not_uploading()

    def open_blob_for_reading(self, blob):
        if blob.is_validated():
            read_handle = blob.open_for_reading()
            if read_handle is not None:
                log.debug('Getting ready to send %s', blob.blob_hash)
                self.next_blob_to_send = blob
                self.read_handle = read_handle
                return defer.succeed(None)
        return defer.fail(ValueError(
            "Couldn't open that blob for some reason. blob_hash: {}".format(blob.blob_hash)))

    def send_blob_info(self):
        assert self.next_blob_to_send is not None, "need to have a next blob to send at this point"
        r = {
            'blob_hash': self.next_blob_to_send.blob_hash,
            'blob_size': self.next_blob_to_send.length
        }
        self.send_request(r)

    def send_descriptor_info(self):
        assert self.stream_descriptor is not None, "need to have a sd blob to send at this point"
        r = {
            'sd_blob_hash': self.stream_descriptor.blob_hash,
            'sd_blob_size': self.stream_descriptor.length
        }
        self.sent_stream_info = True
        self.send_request(r)

    def skip_missing_blob(self, err, blob_hash):
        log.warning("Can't reflect blob %s", str(blob_hash)[:16])
        err.trap(ValueError)
        return self.send_next_request()

    def send_next_request(self):
        if self.file_sender is not None:
            # send the blob
            return self.start_transfer()
        elif not self.sent_stream_info:
            # open the sd blob to send
            blob = self.stream_descriptor
            d = self.open_blob_for_reading(blob)
            d.addCallback(lambda _: self.send_descriptor_info())
            return d
        elif self.blob_hashes_to_send:
            # open the next blob to send
            blob = self.blob_hashes_to_send[0]
            self.blob_hashes_to_send = self.blob_hashes_to_send[1:]
            d = self.open_blob_for_reading(blob)
            d.addCallbacks(lambda _: self.send_blob_info(),
                           lambda err: self.skip_missing_blob(err, blob.blob_hash))
            return d
        # close connection
        self.transport.loseConnection()


class EncryptedFileReflectorClientFactory(ClientFactory):
    protocol = EncryptedFileReflectorClient

    def __init__(self, blob_manager, stream_info_manager, stream_hash):
        self.protocol_version = REFLECTOR_V2
        self.blob_manager = blob_manager
        self.stream_info_manager = stream_info_manager
        self.stream_hash = stream_hash
        self.p = None
        self.finished_deferred = defer.Deferred()

    def buildProtocol(self, addr):
        p = self.protocol()
        p.factory = self
        self.p = p
        return p

    def startFactory(self):
        log.debug('Starting reflector factory')
        ClientFactory.startFactory(self)

    def startedConnecting(self, connector):
        log.debug('Connecting to reflector')

    def clientConnectionLost(self, connector, reason):
        """If we get disconnected, reconnect to server."""

    def clientConnectionFailed(self, connector, reason):
        if reason.check(ConnectionRefusedError):
            log.warning("Could not connect to reflector server")
        else:
            log.error("Reflector connection failed: %s", reason)
