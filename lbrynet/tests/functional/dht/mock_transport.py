import struct
import logging
from twisted.internet import defer, error
from lbrynet.core.utils import generate_id
from lbrynet.dht.encoding import Bencode
from lbrynet.dht.error import DecodeError
from lbrynet.dht.msgformat import DefaultFormat
from lbrynet.dht.msgtypes import ResponseMessage, RequestMessage, ErrorMessage

_encode = Bencode()
_datagram_formatter = DefaultFormat()

log = logging.getLogger()

MOCK_DHT_NODES = [
    "cc8db9d0dd9b65b103594b5f992adf09f18b310958fa451d61ce8d06f3ee97a91461777c2b7dea1a89d02d2f23eb0e4f",
    "83a3a398eead3f162fbbe1afb3d63482bb5b6d3cdd8f9b0825c1dfa58dffd3f6f6026d6e64d6d4ae4c3dfe2262e734ba",
    "b6928ff25778a7bbb5d258d3b3a06e26db1654f3d2efce8c26681d43f7237cdf2e359a4d309c4473d5d89ec99fb4f573",
]

MOCK_DHT_SEED_DNS = {  # these map to mock nodes 0, 1, and 2
    "lbrynet1.lbry.io": "10.42.42.1",
    "lbrynet2.lbry.io": "10.42.42.2",
    "lbrynet3.lbry.io": "10.42.42.3",
    "lbrynet4.lbry.io": "10.42.42.4",
    "lbrynet5.lbry.io": "10.42.42.5",
    "lbrynet6.lbry.io": "10.42.42.6",
    "lbrynet7.lbry.io": "10.42.42.7",
    "lbrynet8.lbry.io": "10.42.42.8",
    "lbrynet9.lbry.io": "10.42.42.9",
    "lbrynet10.lbry.io": "10.42.42.10",
    "lbrynet11.lbry.io": "10.42.42.11",
    "lbrynet12.lbry.io": "10.42.42.12",
    "lbrynet13.lbry.io": "10.42.42.13",
    "lbrynet14.lbry.io": "10.42.42.14",
    "lbrynet15.lbry.io": "10.42.42.15",
    "lbrynet16.lbry.io": "10.42.42.16",
}


def resolve(name, timeout=(1, 3, 11, 45)):
    if name not in MOCK_DHT_SEED_DNS:
        return defer.fail(error.DNSLookupError(name))
    return defer.succeed(MOCK_DHT_SEED_DNS[name])


class MockUDPTransport(object):
    def __init__(self, address, port, max_packet_size, protocol):
        self.address = address
        self.port = port
        self.max_packet_size = max_packet_size
        self._node = protocol._node

    def write(self, data, address):
        if address in MockNetwork.peers:
            dest = MockNetwork.peers[address][0]
            debug_kademlia_packet(data, (self.address, self.port), address, self._node)
            dest.datagramReceived(data, (self.address, self.port))
        else:  # the node is sending to an address that doesnt currently exist, act like it never arrived
            pass


class MockUDPPort(object):
    def __init__(self, protocol, remover):
        self.protocol = protocol
        self._remover = remover

    def startListening(self, reason=None):
        return self.protocol.startProtocol()

    def stopListening(self, reason=None):
        result = self.protocol.stopProtocol()
        self._remover()
        return result


class MockNetwork(object):
    peers = {}  # (interface, port): (protocol, max_packet_size)

    @classmethod
    def add_peer(cls, port, protocol, interface, maxPacketSize):
        interface = protocol._node.externalIP
        protocol.transport = MockUDPTransport(interface, port, maxPacketSize, protocol)
        cls.peers[(interface, port)] = (protocol, maxPacketSize)

        def remove_peer():
            del protocol.transport
            if (interface, port) in cls.peers:
                del cls.peers[(interface, port)]

        return remove_peer


def listenUDP(port, protocol, interface='', maxPacketSize=8192):
    remover = MockNetwork.add_peer(port, protocol, interface, maxPacketSize)
    port = MockUDPPort(protocol, remover)
    port.startListening()
    return port


def address_generator(address=(10, 42, 42, 1)):
    def increment(addr):
        value = struct.unpack("I", "".join([chr(x) for x in list(addr)[::-1]]))[0] + 1
        new_addr = []
        for i in range(4):
            new_addr.append(value % 256)
            value >>= 8
        return tuple(new_addr[::-1])

    while True:
        yield "{}.{}.{}.{}".format(*address)
        address = increment(address)


def mock_node_generator(count=None, mock_node_ids=MOCK_DHT_NODES):
    if mock_node_ids is None:
        mock_node_ids = MOCK_DHT_NODES
    mock_node_ids = list(mock_node_ids)

    for num, node_ip in enumerate(address_generator()):
        if count and num >= count:
            break
        if num >= len(mock_node_ids):
            node_id = generate_id().encode('hex')
        else:
            node_id = mock_node_ids[num]
        yield (node_id, node_ip)


def debug_kademlia_packet(data, source, destination, node):
    if log.level != logging.DEBUG:
        return
    try:
        packet = _datagram_formatter.fromPrimitive(_encode.decode(data))
        if isinstance(packet, RequestMessage):
            log.debug("request %s --> %s %s (node time %s)", source[0], destination[0], packet.request,
                      node.clock.seconds())
        elif isinstance(packet, ResponseMessage):
            if isinstance(packet.response, (str, unicode)):
                log.debug("response %s <-- %s %s (node time %s)", destination[0], source[0], packet.response,
                          node.clock.seconds())
            else:
                log.debug("response %s <-- %s %i contacts (node time %s)", destination[0], source[0],
                          len(packet.response), node.clock.seconds())
        elif isinstance(packet, ErrorMessage):
            log.error("error %s <-- %s %s (node time %s)", destination[0], source[0], packet.exceptionType,
                      node.clock.seconds())
    except DecodeError:
        log.exception("decode error %s --> %s (node time %s)", source[0], destination[0], node.clock.seconds())
