#!/usr/bin/env python3
"""
Basic class with peer methods for the Daemon class (JSON-RPC server).
"""
import asyncio
from binascii import hexlify, unhexlify

from lbry.extras.daemon.daemon_meta import JSONRPCServerType
from lbry.extras.daemon.daemon_meta import requires
from lbry.extras.daemon.daemon_meta import paginate_list
from lbry.extras.daemon.components import DHT_COMPONENT
from lbry.blob.blob_file import is_valid_blobhash
from lbry.dht.peer import make_kademlia_peer


class Daemon_peer(metaclass=JSONRPCServerType):
    @requires(DHT_COMPONENT)
    async def jsonrpc_peer_list(self, blob_hash, search_bottom_out_limit=None, page=None, page_size=None):
        """
        Get peers for blob hash

        Usage:
            peer_list (<blob_hash> | --blob_hash=<blob_hash>)
                [<search_bottom_out_limit> | --search_bottom_out_limit=<search_bottom_out_limit>]
                [--page=<page>] [--page_size=<page_size>]

        Options:
            --blob_hash=<blob_hash>                                  : (str) find available peers for this blob hash
            --search_bottom_out_limit=<search_bottom_out_limit>      : (int) the number of search probes in a row
                                                                             that don't find any new peers
                                                                             before giving up and returning
            --page=<page>                                            : (int) page to return during paginating
            --page_size=<page_size>                                  : (int) number of items on page during pagination

        Returns:
            (list) List of contact dictionaries {'address': <peer ip>, 'udp_port': <dht port>, 'tcp_port': <peer port>,
             'node_id': <peer node id>}
        """

        if not is_valid_blobhash(blob_hash):
            raise Exception("invalid blob hash")
        if search_bottom_out_limit is not None:
            search_bottom_out_limit = int(search_bottom_out_limit)
            if search_bottom_out_limit <= 0:
                raise Exception("invalid bottom out limit")
        else:
            search_bottom_out_limit = 4
        peers = []
        peer_q = asyncio.Queue(loop=self.component_manager.loop)
        await self.dht_node._peers_for_value_producer(blob_hash, peer_q)
        while not peer_q.empty():
            peers.extend(peer_q.get_nowait())
        results = [
            {
                "node_id": hexlify(peer.node_id).decode(),
                "address": peer.address,
                "udp_port": peer.udp_port,
                "tcp_port": peer.tcp_port,
            }
            for peer in peers
        ]
        return paginate_list(results, page, page_size)

    @requires(DHT_COMPONENT)
    async def jsonrpc_peer_ping(self, node_id, address, port):
        """
        Send a kademlia ping to the specified peer. If address and port are provided the peer is directly pinged,
        if not provided the peer is located first.

        Usage:
            peer_ping (<node_id> | --node_id=<node_id>) (<address> | --address=<address>) (<port> | --port=<port>)

        Options:
            None

        Returns:
            (str) pong, or {'error': <error message>} if an error is encountered
        """
        peer = None
        if node_id and address and port:
            peer = make_kademlia_peer(unhexlify(node_id), address, udp_port=int(port))
            try:
                return await self.dht_node.protocol.get_rpc_peer(peer).ping()
            except asyncio.TimeoutError:
                return {'error': 'timeout'}
        if not peer:
            return {'error': 'peer not found'}
