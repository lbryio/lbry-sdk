import logging
from twisted.python import failure
from twisted.internet import error, defer
from twisted.internet.protocol import Protocol, ServerFactory
import json

from lbrynet.core.utils import is_valid_blobhash


log = logging.getLogger(__name__)


class ReflectorServer(Protocol):

    def connectionMade(self):
        peer_info = self.transport.getPeer()
        log.debug('Connection made to %s', peer_info)
        self.peer = self.factory.peer_manager.get_peer(peer_info.host, peer_info.port)
        self.blob_manager = self.factory.blob_manager
        self.received_handshake = False
        self.peer_version = None
        self.receiving_blob = False
        self.incoming_blob = None
        self.blob_write = None
        self.blob_finished_d = None
        self.cancel_write = None
        self.request_buff = ""

    def connectionLost(self, reason=failure.Failure(error.ConnectionDone())):
        pass

    def dataReceived(self, data):
        if self.receiving_blob is False:
            self.request_buff += data
            msg, extra_data = self._get_valid_response(self.request_buff)
            if msg is not None:
                self.request_buff = ''
                d = self.handle_request(msg)
                d.addCallbacks(self.send_response, self.handle_error)
                if self.receiving_blob is True and len(extra_data) != 0:
                    self.blob_write(extra_data)
        else:
            self.blob_write(data)

    def _get_valid_response(self, response_msg):
        extra_data = None
        response = None
        curr_pos = 0
        while True:
            next_close_paren = response_msg.find('}', curr_pos)
            if next_close_paren != -1:
                curr_pos = next_close_paren + 1
                try:
                    response = json.loads(response_msg[:curr_pos])
                except ValueError:
                    if curr_pos > 100:
                        raise Exception("error decoding response")
                    else:
                        pass
                else:
                    extra_data = response_msg[curr_pos:]
                    break
            else:
                break
        return response, extra_data

    def handle_request(self, request_dict):
        if self.received_handshake is False:
            return self.handle_handshake(request_dict)
        else:
            return self.handle_normal_request(request_dict)

    def handle_handshake(self, request_dict):
        if 'version' not in request_dict:
            raise ValueError("Client should send version")
        self.peer_version = int(request_dict['version'])
        if self.peer_version != 0:
            raise ValueError("I don't know that version!")
        self.received_handshake = True
        return defer.succeed({'version': 0})

    def determine_blob_needed(self, blob):
        if blob.is_validated():
            return {'send_blob': False}
        else:
            self.incoming_blob = blob
            self.blob_finished_d, self.blob_write, self.cancel_write = blob.open_for_writing(self.peer)
            return {'send_blob': True}

    def close_blob(self):
        self.blob_finished_d = None
        self.blob_write = None
        self.cancel_write = None
        self.incoming_blob = None
        self.receiving_blob = False

    def handle_normal_request(self, request_dict):
        if self.blob_write is None:
            #  we haven't opened a blob yet, meaning we must be waiting for the
            #  next message containing a blob hash and a length. this message
            #  should be it. if it's one we want, open the blob for writing, and
            #  return a nice response dict (in a Deferred) saying go ahead
            if not 'blob_hash' in request_dict or not 'blob_size' in request_dict:
                raise ValueError("Expected a blob hash and a blob size")
            if not is_valid_blobhash(request_dict['blob_hash']):
                raise ValueError("Got a bad blob hash: {}".format(request_dict['blob_hash']))
            d = self.blob_manager.get_blob(
                request_dict['blob_hash'],
                True,
                int(request_dict['blob_size'])
            )
            d.addCallback(self.determine_blob_needed)
        else:
            #  we have a blob open already, so this message should have nothing
            #  important in it. to the deferred that fires when the blob is done,
            #  add a callback which returns a nice response dict saying to keep
            #  sending, and then return that deferred
            self.receiving_blob = True
            d = self.blob_finished_d
            d.addCallback(lambda _: self.close_blob())
            d.addCallback(lambda _: {'received_blob': True})
        return d

    def send_response(self, response_dict):
        self.transport.write(json.dumps(response_dict))

    def handle_error(self, err):
        log.error(err.getTraceback())
        self.transport.loseConnection()


class ReflectorServerFactory(ServerFactory):
    protocol = ReflectorServer

    def __init__(self, peer_manager, blob_manager):
        self.peer_manager = peer_manager
        self.blob_manager = blob_manager