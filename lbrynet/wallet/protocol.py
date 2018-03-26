import sys
import time
import json
import socket
import logging
from itertools import cycle
from twisted.internet import defer, reactor, protocol, threads
from twisted.application.internet import ClientService, CancelledError
from twisted.internet.endpoints import clientFromString
from twisted.protocols.basic import LineOnlyReceiver
from errors import RemoteServiceException, ProtocolException
from errors import TransportException

from .stream import StreamController

log = logging.getLogger()


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
            message = json.loads(line)
        except (ValueError, TypeError):
            raise ProtocolException("Cannot decode message '%s'" % line.strip())
        msg_id = message.get('id', 0)
        msg_result = message.get('result')
        msg_error = message.get('error')
        msg_method = message.get('method')
        msg_params = message.get('params')
        if msg_id:
            # It's a RPC response
            # Perform lookup to the table of waiting requests.
            try:
                meta = self.lookup_table[msg_id]
                del self.lookup_table[msg_id]
            except KeyError:
                # When deferred object for given message ID isn't found, it's an error
                raise ProtocolException(
                    "Lookup for deferred object for message ID '%s' failed." % msg_id)
            # If there's an error, handle it as errback
            # If both result and error are null, handle it as a success with blank result
            if msg_error != None:
                meta['defer'].errback(
                    RemoteServiceException(msg_error[0], msg_error[1], msg_error[2])
                )
            else:
                meta['defer'].callback(msg_result)
        elif msg_method:
            if msg_method == 'blockchain.headers.subscribe':
                self.network._on_header_controller.add(msg_params[0])
            elif msg_method == 'blockchain.address.subscribe':
                self.network._on_address_controller.add(msg_params)
        else:
            log.warning("Cannot handle message '%s'" % line)

    def write_request(self, method, params, is_notification=False):
        request_id = None if is_notification else self._get_id()
        serialized = json.dumps({'id': request_id, 'method': method, 'params': params})
        self.sendLine(serialized)
        return request_id

    def rpc(self, method, params, is_notification=False):
        request_id = self.write_request(method, params, is_notification)
        if is_notification:
            return
        d = defer.Deferred()
        self.lookup_table[request_id] = {
            'method': method,
            'params': params,
            'defer': d,
        }
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

        self._on_transaction_controller = StreamController()
        self.on_transaction = self._on_transaction_controller.stream

    @defer.inlineCallbacks
    def start(self):
        for server in cycle(self.config.get('default_servers')):
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

    def rpc(self, method, params, *args, **kwargs):
        if self.is_connected:
            return self.client.rpc(method, params, *args, **kwargs)
        else:
            raise TransportException("Attempting to send rpc request when connection is not available.")

    def claimtrie_getvaluesforuris(self, block_hash, *uris):
        return self.rpc(
            'blockchain.claimtrie.getvaluesforuris', [block_hash] + list(uris)
        )

    def claimtrie_getvaluesforuri(self, block_hash, uri):
        return self.rpc('blockchain.claimtrie.getvaluesforuri', [block_hash, uri])

    def claimtrie_getclaimssignedbynthtoname(self, name, n):
        return self.rpc('blockchain.claimtrie.getclaimssignedbynthtoname', [name, n])

    def claimtrie_getclaimssignedbyid(self, certificate_id):
        return self.rpc('blockchain.claimtrie.getclaimssignedbyid', [certificate_id])

    def claimtrie_getclaimssignedby(self, name):
        return self.rpc('blockchain.claimtrie.getclaimssignedby', [name])

    def claimtrie_getnthclaimforname(self, name, n):
        return self.rpc('blockchain.claimtrie.getnthclaimforname', [name, n])

    def claimtrie_getclaimsbyids(self, *claim_ids):
        return self.rpc('blockchain.claimtrie.getclaimsbyids', list(claim_ids))

    def claimtrie_getclaimbyid(self, claim_id):
        return self.rpc('blockchain.claimtrie.getclaimbyid', [claim_id])

    def claimtrie_get(self):
        return self.rpc('blockchain.claimtrie.get', [])

    def block_get_block(self, block_hash):
        return self.rpc('blockchain.block.get_block', [block_hash])

    def claimtrie_getclaimsforname(self, name):
        return self.rpc('blockchain.claimtrie.getclaimsforname', [name])

    def claimtrie_getclaimsintx(self, txid):
        return self.rpc('blockchain.claimtrie.getclaimsintx', [txid])

    def claimtrie_getvalue(self, name, block_hash=None):
        return self.rpc('blockchain.claimtrie.getvalue', [name, block_hash])

    def relayfee(self):
        return self.rpc('blockchain.relayfee', [])

    def estimatefee(self):
        return self.rpc('blockchain.estimatefee', [])

    def transaction_get(self, txid):
        return self.rpc('blockchain.transaction.get', [txid])

    def transaction_get_merkle(self, tx_hash, height, cache_only=False):
        return self.rpc('blockchain.transaction.get_merkle', [tx_hash, height, cache_only])

    def transaction_broadcast(self, raw_transaction):
        return self.rpc('blockchain.transaction.broadcast', [raw_transaction])

    def block_get_chunk(self, index, cache_only=False):
        return self.rpc('blockchain.block.get_chunk', [index, cache_only])

    def block_get_header(self, height, cache_only=False):
        return self.rpc('blockchain.block.get_header', [height, cache_only])

    def block_headers(self, height, count=10000):
        return self.rpc('blockchain.block.headers', [height, count])

    def utxo_get_address(self, txid, pos):
        return self.rpc('blockchain.utxo.get_address', [txid, pos])

    def address_listunspent(self, address):
        return self.rpc('blockchain.address.listunspent', [address])

    def address_get_proof(self, address):
        return self.rpc('blockchain.address.get_proof', [address])

    def address_get_balance(self, address):
        return self.rpc('blockchain.address.get_balance', [address])

    def address_get_mempool(self, address):
        return self.rpc('blockchain.address.get_mempool', [address])

    def address_get_history(self, address):
        return self.rpc('blockchain.address.get_history', [address])

    def address_subscribe(self, addresses):
        if isinstance(addresses, str):
            return self.rpc('blockchain.address.subscribe', [addresses])
        else:
            msgs = map(lambda addr: ('blockchain.address.subscribe', [addr]), addresses)
            self.network.send(msgs, self.addr_subscription_response)

    def headers_subscribe(self):
        return self.rpc('blockchain.headers.subscribe', [], True)
