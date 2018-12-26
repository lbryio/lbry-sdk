import logging
import asyncio
import typing
import socket

from lbrynet.peer import PeerManager
from lbrynet.dht.protocol.protocol import KademliaProtocol
from lbrynet.dht import constants

log = logging.getLogger(__name__)


class Node:
    def __init__(self, peer_manager: PeerManager, loop: asyncio.BaseEventLoop, node_id: bytes, udp_port: int,
                 internal_udp_port: int, peer_port: int, external_ip: str):
        self.loop = loop
        self.internal_udp_port = internal_udp_port
        self.protocol = KademliaProtocol(peer_manager, loop, node_id, external_ip, udp_port, peer_port)
        self.listening_port: asyncio.DatagramTransport = None

    def stop(self) -> None:
        if self.listening_port is not None:
            self.listening_port.close()
        self.listening_port = None

    async def start_listening(self, interface: str = '') -> None:
        if not self.listening_port:
            self.listening_port, _ = await self.loop.create_datagram_endpoint(
                lambda: self.protocol, (interface, self.internal_udp_port)
            )
            log.info("listening on %i", self.internal_udp_port)
        else:
            log.warning("Already bound to port %s", self.listening_port)

    async def join_network(self, interface: typing.Optional[str] = '',
                           known_node_urls: typing.Optional[typing.List[typing.Tuple[str, int]]] = None,
                           known_node_addresses: typing.Optional[typing.List[typing.Tuple[str, int]]] = None):
        if not self.listening_port:
            await self.start_listening(interface)
        known_node_addresses = known_node_addresses or []
        if known_node_urls:
            for host, port in known_node_urls:
                info = await self.loop.getaddrinfo(
                    host, 'https',
                    proto=socket.IPPROTO_TCP,
                )
                if (info[0][4][0], port) not in known_node_addresses:
                    known_node_addresses.append((info[0][4][0], port))
        futs = []
        for address, port in known_node_addresses:
            peer = self.protocol.peer_manager.make_peer(address, udp_port=port)
            futs.append(peer.ping())
        await asyncio.gather(*futs, loop=self.loop)
        await self.protocol.cumulative_find_node(self.protocol.node_id)

    def get_iterative_value_finder(self, key: bytes, bottom_out_limit: int = constants.bottom_out_limit,
                                   max_results: int = constants.k):
        return self.protocol.get_find_iterator('findValue', key, bottom_out_limit=bottom_out_limit, max_results=max_results)
