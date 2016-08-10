"""
The reflector protocol (all dicts encoded in json):

Client Handshake (sent once per connection, at the start of the connection):

{
    'version': 0,
}


Server Handshake (sent once per connection, after receiving the client handshake):

{
    'version': 0,
}


Client Info Request:

{
    'blob_hash': "<blob_hash>",
    'blob_size': <blob_size>
}


Server Info Response (sent in response to Client Info Request):

{
    'send_blob': True|False
}

If response is 'YES', client may send a Client Blob Request or a Client Info Request.
If response is 'NO', client may only send a Client Info Request


Client Blob Request:

{}  # Yes, this is an empty dictionary, in case something needs to go here in the future
<raw blob_data>  # this blob data must match the info sent in the most recent Client Info Request


Server Blob Response (sent in response to Client Blob Request):
{
    'received_blob': True
}

Client may now send another Client Info Request

"""
import json
import logging
from twisted.protocols.basic import FileSender
from twisted.internet.protocol import Protocol, ClientFactory
from twisted.internet import defer, error


log = logging.getLogger(__name__)


class IncompleteResponseError(Exception):
    pass


class LBRYFileReflectorClient(Protocol):

    #  Protocol stuff

    def connectionMade(self):
        self.blob_manager = self.factory.blob_manager
        self.response_buff = ''
        self.outgoing_buff = ''
        self.blob_hashes_to_send = []
        self.next_blob_to_send = None
        self.blob_read_handle = None
        self.received_handshake_response = False
        self.protocol_version = None
        self.file_sender = None
        self.producer = None
        self.streaming = False
        d = self.get_blobs_to_send(self.factory.stream_info_manager, self.factory.stream_hash)
        d.addCallback(lambda _: self.send_handshake())
        d.addErrback(lambda err: log.warning("An error occurred immediately: %s", err.getTraceback()))

    def dataReceived(self, data):
        self.response_buff += data
        try:
            msg = self.parse_response(self.response_buff)
        except IncompleteResponseError:
            pass
        else:
            self.response_buff = ''
            d = self.handle_response(msg)
            d.addCallback(lambda _: self.send_next_request())
            d.addErrback(self.response_failure_handler)

    def connectionLost(self, reason):
        if reason.check(error.ConnectionDone):
            self.factory.finished_deferred.callback(True)
        else:
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

    def get_blobs_to_send(self, stream_info_manager, stream_hash):
        log.info("Get blobs to send to reflector")
        d = stream_info_manager.get_blobs_for_stream(stream_hash)

        def set_blobs(blob_hashes):
            for blob_hash, position, iv, length in blob_hashes:
                log.info("Preparing to send %s", blob_hash)
                if blob_hash is not None:
                    self.blob_hashes_to_send.append(blob_hash)

        d.addCallback(set_blobs)

        d.addCallback(lambda _: stream_info_manager.get_sd_blob_hashes_for_stream(stream_hash))

        def set_sd_blobs(sd_blob_hashes):
            for sd_blob_hash in sd_blob_hashes:
                self.blob_hashes_to_send.append(sd_blob_hash)

        d.addCallback(set_sd_blobs)
        return d

    def send_handshake(self):
        self.write(json.dumps({'version': 0}))

    def parse_response(self, buff):
        try:
            return json.loads(buff)
        except ValueError:
            raise IncompleteResponseError()

    def response_failure_handler(self, err):
        log.warning("An error occurred handling the response: %s", err.getTraceback())

    def handle_response(self, response_dict):
        if self.received_handshake_response is False:
            return self.handle_handshake_response(response_dict)
        else:
            return self.handle_normal_response(response_dict)

    def set_not_uploading(self):
        if self.next_blob_to_send is not None:
            self.next_blob_to_send.close_read_handle(self.read_handle)
            self.read_handle = None
            self.next_blob_to_send = None
        self.file_sender = None
        return defer.succeed(None)

    def start_transfer(self):
        self.write(json.dumps({}))
        assert self.read_handle is not None, "self.read_handle was None when trying to start the transfer"
        d = self.file_sender.beginFileTransfer(self.read_handle, self)
        return d

    def handle_handshake_response(self, response_dict):
        if 'version' not in response_dict:
            raise ValueError("Need protocol version number!")
        self.protocol_version = int(response_dict['version'])
        if self.protocol_version != 0:
            raise ValueError("I can't handle protocol version {}!".format(self.protocol_version))
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
                return self.set_not_uploading()

    def open_blob_for_reading(self, blob):
        if blob.is_validated():
            read_handle = blob.open_for_reading()
            if read_handle is not None:
                self.next_blob_to_send = blob
                self.read_handle = read_handle
                return None
        raise ValueError("Couldn't open that blob for some reason. blob_hash: {}".format(blob.blob_hash))

    def send_blob_info(self):
        log.info("Send blob info for %s", self.next_blob_to_send.blob_hash)
        assert self.next_blob_to_send is not None, "need to have a next blob to send at this point"
        self.write(json.dumps({
            'blob_hash': self.next_blob_to_send.blob_hash,
            'blob_size': self.next_blob_to_send.length
        }))

    def send_next_request(self):
        if self.file_sender is not None:
            # send the blob
            return self.start_transfer()
        elif self.blob_hashes_to_send:
            # open the next blob to send
            blob_hash = self.blob_hashes_to_send[0]
            self.blob_hashes_to_send = self.blob_hashes_to_send[1:]
            d = self.blob_manager.get_blob(blob_hash, True)
            d.addCallback(self.open_blob_for_reading)
            # send the server the next blob hash + length
            d.addCallback(lambda _: self.send_blob_info())
            return d
        else:
            # close connection
            self.transport.loseConnection()


class LBRYFileReflectorClientFactory(ClientFactory):
    protocol = LBRYFileReflectorClient

    def __init__(self, blob_manager, stream_info_manager, stream_hash):
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