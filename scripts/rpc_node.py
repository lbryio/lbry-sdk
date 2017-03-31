#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive
#

# Thanks to Paul Cannon for IP-address resolution functions (taken from aspn.activestate.com)


"""
Launch a DHT node which can respond to RPC commands.
"""

import argparse
from lbrynet.dht.node import Node
from txjsonrpc.web import jsonrpc
from twisted.web import server
from twisted.internet import reactor, defer


class RPCNode(jsonrpc.JSONRPC):
    def __init__(self, node, shut_down_cb):
        jsonrpc.JSONRPC.__init__(self)
        self.node = node
        self.shut_down_cb = shut_down_cb

    def jsonrpc_total_dht_nodes(self):
        return self.node.getApproximateTotalDHTNodes()

    def jsonrpc_total_dht_hashes(self):
        return self.node.getApproximateTotalHashes()

    def jsonrpc_stop(self):
        self.shut_down_cb()
        return "fine"


def main():
    parser = argparse.ArgumentParser(description="Launch a dht node which responds to rpc commands")

    parser.add_argument("node_port",
                        help=("The UDP port on which the node will listen for connections "
                              "from other dht nodes"),
                        type=int)
    parser.add_argument("rpc_port",
                        help="The TCP port on which the node will listen for rpc commands",
                        type=int)
    parser.add_argument("dht_bootstrap_host",
                        help="The IP of a DHT node to be used to bootstrap into the network",
                        nargs='?')
    parser.add_argument("dht_bootstrap_port",
                        help="The port of a DHT node to be used to bootstrap into the network",
                        nargs='?', default=4000, type=int)
    parser.add_argument("--rpc_ip_address",
                        help="The network interface on which to listen for rpc connections",
                        default="127.0.0.1")

    args = parser.parse_args()

    def start_rpc():
        rpc_node = RPCNode(node, shut_down)
        reactor.listenTCP(args.rpc_port, server.Site(rpc_node), interface=args.rpc_ip_address)

    def shut_down():
        d = defer.maybeDeferred(node.stop)
        d.addBoth(lambda _: reactor.stop())
        return d

    known_nodes = []
    if args.dht_bootstrap_host:
        known_nodes.append((args.dht_bootstrap_host, args.dht_bootstrap_port))

    node = Node(udpPort=args.node_port)
    node.joinNetwork(known_nodes)
    d = node._joinDeferred
    d.addCallback(lambda _: start_rpc())
    reactor.run()


if __name__ == '__main__':
    main()
