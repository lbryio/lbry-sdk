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
    'response': ['YES', 'NO']
}

If response is 'YES', client may send a Client Blob Request or a Client Info Request.
If response is 'NO', client may only send a Client Info Request


Client Blob Request:

{}  # Yes, this is an empty dictionary, in case something needs to go here in the future
<raw blob_data>  # this blob data must match the info sent in the most recent Client Info Request


Server Blob Response (sent in response to Client Blob Request):
{
    'received': True
}

Client may now send another Client Info Request

"""
import json
import logging
from twisted.internet.protocol import Protocol, ClientFactory


log = logging.getLogger(__name__)


class IncompleteResponseError(Exception):
    pass


class LBRYFileReflectorClient(Protocol):
    def connectionMade(self):
        self.peer = self.factory.peer
        self.response_buff = ''
        self.outgoing_buff = ''
        self.blob_hashes_to_send = []
        self.next_blob_to_send = None
        self.received_handshake_response = False
        d = self.get_blobs_to_send(self.factory.stream_info_manager, self.factory.stream_hash)
        d.addCallback(lambda _: self.send_handshake())

    def dataReceived(self, data):
        self.response_buff += data
        try:
            msg = self.parse_response(self.response_buff)
        except IncompleteResponseError:
            pass
        else:
            self.response_buff = ''
            d = self.handle_response(msg)
            d.addCallbacks(lambda _: self.send_next_request(), self.response_failure_handler)

    def connectionLost(self, reason):
        pass

    def get_blobs_to_send(self, stream_info_manager, stream_hash):
        d = stream_info_manager.get_blobs_for_stream(stream_hash)

        def set_blobs(blob_hashes):
            for blob_hash, position, iv, length in blob_hashes:
                self.blob_hashes_to_send.append(blob_hash)

        d.addCallback(set_blobs)
        return d

    def parse_response(self, buff):
        try:
            return json.loads(buff)
        except ValueError:
            raise IncompleteResponseError()

    def handle_response(self, response_dict):
        if self.received_handshake_response is False:
            self.handle_handshake_response(response_dict)
        else:
            self.handle_normal_response(response_dict)

    def handle_handshake_response(self, response_dict):
        pass

    def handle_normal_response(self, response_dict):
        pass

    def send_next_request(self):
        if self.next_blob_to_send is not None:
            # send the blob
            pass
        elif self.blobs_to_send:
            # send the server the next blob hash + length
            pass
        else:
            # close connection
            pass


class LBRYFileReflectorClientFactory(ClientFactory):
    protocol = LBRYFileReflectorClient

    def __init__(self, stream_info_manager, peer, stream_hash):
        self.peer = peer
        self.stream_info_manager = stream_info_manager
        self.stream_hash = stream_hash
        self.p = None

    def buildProtocol(self, addr):
        p = self.protocol()
        p.factory = self
        self.p = p
        return p