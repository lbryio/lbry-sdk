import json
import logging

from twisted.protocols.basic import FileSender
from twisted.internet.protocol import Protocol, ClientFactory
from twisted.internet import defer, error

from lbrynet.extras.reflector.common import IncompleteResponse, REFLECTOR_V2


log = logging.getLogger(__name__)


class BlobReflectorClient(Protocol):
    #  Protocol stuff

    def connectionMade(self):
        self.blob_manager = self.factory.blob_manager
        self.response_buff = b''
        self.outgoing_buff = ''
        self.blob_hashes_to_send = self.factory.blobs
        self.next_blob_to_send = None
        self.blob_read_handle = None
        self.received_handshake_response = False
        self.protocol_version = self.factory.protocol_version
        self.file_sender = None
        self.producer = None
        self.streaming = False
        self.reflected_blobs = []
        d = self.send_handshake()
        d.addErrback(
            lambda err: log.warning("An error occurred immediately: %s", err.getTraceback()))

    def dataReceived(self, data):
        log.debug('Received %s', data)
        self.response_buff += data
        try:
            msg = self.parse_response(self.response_buff)
        except IncompleteResponse:
            pass
        else:
            self.response_buff = b''
            d = self.handle_response(msg)
            d.addCallback(lambda _: self.send_next_request())
            d.addErrback(self.response_failure_handler)

    def connectionLost(self, reason):
        if reason.check(error.ConnectionDone):
            if self.reflected_blobs:
                log.info('Finished sending data via reflector')
            self.factory.finished_deferred.callback(self.reflected_blobs)
        else:
            log.info('Reflector finished: %s', reason)
            self.factory.finished_deferred.callback(reason)

    # IConsumer stuff

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

    def send_handshake(self):
        log.debug('Sending handshake')
        self.write(json.dumps({'version': self.protocol_version}).encode())
        return defer.succeed(None)

    def parse_response(self, buff):
        try:
            return json.loads(buff)
        except ValueError:
            raise IncompleteResponse()

    def response_failure_handler(self, err):
        log.warning("An error occurred handling the response: %s", err.getTraceback())

    def handle_response(self, response_dict):
        if self.received_handshake_response is False:
            return self.handle_handshake_response(response_dict)
        else:
            return self.handle_normal_response(response_dict)

    def set_not_uploading(self):
        if self.next_blob_to_send is not None:
            self.read_handle.close()
            self.read_handle = None
            self.next_blob_to_send = None
        self.file_sender = None
        return defer.succeed(None)

    def start_transfer(self):
        assert self.read_handle is not None, \
            "self.read_handle was None when trying to start the transfer"
        d = self.file_sender.beginFileTransfer(self.read_handle, self)
        d.addCallback(lambda _: self.read_handle.close())
        return d

    def handle_handshake_response(self, response_dict):
        if 'version' not in response_dict:
            raise ValueError("Need protocol version number!")
        server_version = int(response_dict['version'])
        if self.protocol_version != server_version:
            raise ValueError(f"I can't handle protocol version {self.protocol_version}!")
        self.received_handshake_response = True
        return defer.succeed(True)

    def handle_normal_response(self, response_dict):
        if self.file_sender is None:  # Expecting Server Info Response
            if 'send_blob' not in response_dict:
                raise ValueError("I don't know whether to send the blob or not!")
            if response_dict['send_blob'] is True:
                self.file_sender = FileSender()
                return defer.succeed(True)
            else:
                return self.set_not_uploading()
        else:  # Expecting Server Blob Response
            if 'received_blob' not in response_dict:
                raise ValueError("I don't know if the blob made it to the intended destination!")
            else:
                if response_dict['received_blob']:
                    self.reflected_blobs.append(self.next_blob_to_send.blob_hash)
                return self.set_not_uploading()

    def open_blob_for_reading(self, blob):
        if blob.get_is_verified():
            read_handle = blob.open_for_reading()
            if read_handle is not None:
                log.debug('Getting ready to send %s', blob.blob_hash)
                self.next_blob_to_send = blob
                self.read_handle = read_handle
                return None
        raise ValueError(
            f"Couldn't open that blob for some reason. blob_hash: {blob.blob_hash}")

    def send_blob_info(self):
        log.debug("Send blob info for %s", self.next_blob_to_send.blob_hash)
        assert self.next_blob_to_send is not None, "need to have a next blob to send at this point"
        log.debug('sending blob info')
        self.write(json.dumps({
            'blob_hash': self.next_blob_to_send.blob_hash,
            'blob_size': self.next_blob_to_send.length
        }).encode())

    def disconnect(self, err):
        self.transport.loseConnection()

    def send_next_request(self):
        if self.file_sender is not None:
            # send the blob
            log.debug('Sending the blob')
            return self.start_transfer()
        elif self.blob_hashes_to_send:
            # open the next blob to send
            blob_hash = self.blob_hashes_to_send[0]
            log.debug('No current blob, sending the next one: %s', blob_hash)
            self.blob_hashes_to_send = self.blob_hashes_to_send[1:]
            d = self.blob_manager.get_blob(blob_hash)
            d.addCallback(self.open_blob_for_reading)
            # send the server the next blob hash + length
            d.addCallbacks(
                lambda _: self.send_blob_info(), self.disconnect,
            )
            return d
        else:
            # close connection
            log.debug('No more blob hashes, closing connection')
            self.transport.loseConnection()


class BlobReflectorClientFactory(ClientFactory):
    protocol = BlobReflectorClient

    def __init__(self, blob_manager, blobs):
        self.protocol_version = REFLECTOR_V2
        self.blob_manager = blob_manager
        self.blobs = blobs
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
        log.debug('Started connecting')

    def clientConnectionLost(self, connector, reason):
        """If we get disconnected, reconnect to server."""
        log.debug("connection lost: %s", reason.getErrorMessage())

    def clientConnectionFailed(self, connector, reason):
        log.debug("connection failed: %s", reason.getErrorMessage())
