import six
import json
import socket
import logging
from itertools import cycle
from twisted.internet import defer, reactor, protocol
from twisted.application.internet import ClientService, CancelledError
from twisted.internet.endpoints import clientFromString
from twisted.protocols.basic import LineOnlyReceiver
from errors import RemoteServiceException, ProtocolException
from errors import TransportException

from .stream import StreamController

log = logging.getLogger()


def unicode2bytes(string):
    if isinstance(string, six.text_type):
        return string.encode('iso-8859-1')
    return string


class StratumClientProtocol(LineOnlyReceiver):
    delimiter = '\n'

    def __init__(self):
        self.request_id = 0
        self.lookup_table = {}
        self.session = {}

        self.on_disconnected_controller = StreamController()
        self.on_disconnected = self.on_disconnected_controller.stream

    def _get_id(self):
        self.request_id += 1
        return self.request_id

    @property
    def _ip(self):
        return self.transport.getPeer().host

    def get_session(self):
        return self.session

    def connectionMade(self):
        try:
            self.transport.setTcpNoDelay(True)
            self.transport.setTcpKeepAlive(True)
            self.transport.socket.setsockopt(
                socket.SOL_TCP, socket.TCP_KEEPIDLE, 120
                # Seconds before sending keepalive probes
            )
            self.transport.socket.setsockopt(
                socket.SOL_TCP, socket.TCP_KEEPINTVL, 1
                # Interval in seconds between keepalive probes
            )
            self.transport.socket.setsockopt(
                socket.SOL_TCP, socket.TCP_KEEPCNT, 5
                # Failed keepalive probles before declaring other end dead
            )
        except Exception as err:
            # Supported only by the socket transport,
            # but there's really no better place in code to trigger this.
            log.warning("Error setting up socket: %s", err)

    def connectionLost(self, reason=None):
        self.on_disconnected_controller.add(True)

    def lineReceived(self, line):

        try:
            # `line` comes in as a byte string but `json.loads` automatically converts everything to
            # unicode. For keys it's not a big deal but for values there is an expectation
            # everywhere else in wallet code that most values are byte strings.
            message = json.loads(
                line, object_hook=lambda obj: {
                    k: unicode2bytes(v) for k, v in obj.items()
                }
            )
        except (ValueError, TypeError):
            raise ProtocolException("Cannot decode message '{}'".format(line.strip()))

        if message.get('id'):
            try:
                d = self.lookup_table.pop(message['id'])
                if message.get('error'):
                    d.errback(RemoteServiceException(*message['error']))
                else:
                    d.callback(message.get('result'))
            except KeyError:
                raise ProtocolException(
                    "Lookup for deferred object for message ID '{}' failed.".format(message['id']))
        elif message.get('method') in self.network.subscription_controllers:
            controller = self.network.subscription_controllers[message['method']]
            controller.add(message.get('params'))
        else:
            log.warning("Cannot handle message '%s'" % line)

    def rpc(self, method, *args):
        message_id = self._get_id()
        message = json.dumps({
            'id': message_id,
            'method': method,
            'params': args
        })
        self.sendLine(message)
        d = self.lookup_table[message_id] = defer.Deferred()
        return d


class StratumClientFactory(protocol.ClientFactory):

    protocol = StratumClientProtocol

    def __init__(self, network):
        self.network = network
        self.client = None

    def buildProtocol(self, addr):
        client = self.protocol()
        client.factory = self
        client.network = self.network
        self.client = client
        return client


class Network:

    def __init__(self, config):
        self.config = config
        self.client = None
        self.service = None
        self.running = False

        self._on_connected_controller = StreamController()
        self.on_connected = self._on_connected_controller.stream

        self._on_header_controller = StreamController()
        self.on_header = self._on_header_controller.stream

        self._on_status_controller = StreamController()
        self.on_status = self._on_status_controller.stream

        self.subscription_controllers = {
            'blockchain.headers.subscribe': self._on_header_controller,
            'blockchain.address.subscribe': self._on_status_controller,
        }

    @defer.inlineCallbacks
    def start(self):
        for server in cycle(self.config['default_servers']):
            endpoint = clientFromString(reactor, 'tcp:{}:{}'.format(*server))
            self.service = ClientService(endpoint, StratumClientFactory(self))
            self.service.startService()
            try:
                self.client = yield self.service.whenConnected(failAfterFailures=2)
                self._on_connected_controller.add(True)
                yield self.client.on_disconnected.first
            except CancelledError:
                return
            except Exception as e:
                pass
            finally:
                self.client = None
            if not self.running:
                return

    def stop(self):
        self.running = False
        if self.service is not None:
            self.service.stopService()
        if self.is_connected:
            return self.client.on_disconnected.first
        else:
            return defer.succeed(True)

    @property
    def is_connected(self):
        return self.client is not None and self.client.connected

    def rpc(self, list_or_method, *args):
        if self.is_connected:
            return self.client.rpc(list_or_method, *args)
        else:
            raise TransportException("Attempting to send rpc request when connection is not available.")

    def broadcast(self, raw_transaction):
        return self.rpc('blockchain.transaction.broadcast', raw_transaction)

    def get_history(self, address):
        return self.rpc('blockchain.address.get_history', address)

    def get_transaction(self, tx_hash):
        return self.rpc('blockchain.transaction.get', tx_hash)

    def get_merkle(self, tx_hash, height):
        return self.rpc('blockchain.transaction.get_merkle', tx_hash, height)

    def get_headers(self, height, count=10000):
        return self.rpc('blockchain.block.headers', height, count)

    def subscribe_headers(self):
        return self.rpc('blockchain.headers.subscribe')

    def subscribe_address(self, address):
        return self.rpc('blockchain.address.subscribe', address)
