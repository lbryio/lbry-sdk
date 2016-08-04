import logging
from twisted.python import failure
from twisted.internet import error
from twisted.internet.protocol import Protocol, ServerFactory
import json


log = logging.getLogger(__name__)


class IncompleteMessageError(Exception):
    pass


class ReflectorServer(Protocol):
    """
    """

    def connectionMade(self):
        peer_info = self.transport.getPeer()
        self.peer = self.factory.peer_manager.get_peer(peer_info.host, peer_info.port)
        self.received_handshake = False
        self.peer_version = None
        self.receiving_blob = False
        self.blob_write = None
        self.blob_finished_d = None
        self.request_buff = ""

    def connectionLost(self, reason=failure.Failure(error.ConnectionDone())):
        pass

    def dataReceived(self, data):
        if self.receiving_blob is False:
            self.request_buff += data
            try:
                msg = self.parse_request(self.request_buff)
            except IncompleteMessageError:
                pass
            else:
                self.request_buff = ''
                d = self.handle_request(msg)
                d.addCallbacks(self.send_response, self.handle_error)
        else:
            self.blob_write(data)

    def parse_request(self, buff):
        try:
            return json.loads(buff)
        except ValueError:
            raise IncompleteMessageError()

    def handle_request(self, request_dict):
        if self.received_handshake is False:
            return self.handle_handshake(request_dict)
        else:
            return self.handle_normal_request(request_dict)

    def handle_handshake(self, request_dict):
        pass

    def handle_normal_request(self, request_dict):
        if self.blob_write is None:
            #  we haven't opened a blob yet, meaning we must be waiting for the
            #  next message containing a blob hash and a length. this message
            #  should be it. if it's one we want, open the blob for writing, and
            #  return a nice response dict (in a Deferred) saying go ahead
            pass
        else:
            #  we have a blob open already, so this message should have nothing
            #  important in it. to the deferred that fires when the blob is done,
            #  add a callback which returns a nice response dict saying to keep
            #  sending, and then return that deferred
            pass

    def send_response(self, response_dict):
        pass

    def handle_error(self, err):
        pass


class ReflectorServerFactory(ServerFactory):
    protocol = ReflectorServer

    def __init__(self, peer_manager):
        self.peer_manager = peer_manager