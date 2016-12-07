#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive
#

# Thanks to Paul Cannon for IP-address resolution functions (taken from aspn.activestate.com)

import argparse
import os, sys, time, signal

amount = 0


def destroyNetwork(nodes):
    print 'Destroying Kademlia network...'
    i = 0
    for node in nodes:
        i += 1
        hashAmount = i*50/amount
        hashbar = '#'*hashAmount
        output = '\r[%-50s] %d/%d' % (hashbar, i, amount)
        sys.stdout.write(output)
        time.sleep(0.15)
        os.kill(node, signal.SIGTERM)
    print


def main():

    parser = argparse.ArgumentParser(description="Launch a network of dht nodes")

    parser.add_argument("amount_of_nodes",
                        help="The number of nodes to create",
                        type=int)
    parser.add_argument(
        "--nic_ip_address",
        help=("The network interface on which these nodes will listen for connections "
              "from each other and from other nodes. If omitted, an attempt will be "
              "made to automatically determine the system's IP address, but this may "
              "result in the nodes being reachable only from this system"))

    args = parser.parse_args()

    global amount
    amount = args.amount_of_nodes
    if args.nic_ip_address:
        ipAddress = args.nic_ip_address
    else:
        import socket
        ipAddress = socket.gethostbyname(socket.gethostname())
        print 'Network interface IP address omitted; using %s...' % ipAddress

    startPort = 4000
    port = startPort+1
    nodes = []
    print 'Creating Kademlia network...'
    try:
        node = os.spawnlp(
            os.P_NOWAIT, 'lbrynet-launch-node', 'lbrynet-launch-node', str(startPort))
        nodes.append(node)
        for i in range(amount-1):
            time.sleep(0.15)
            hashAmount = i*50/amount
            hashbar = '#'*hashAmount
            output = '\r[%-50s] %d/%d' % (hashbar, i, amount)
            sys.stdout.write(output)
            node = os.spawnlp(
                os.P_NOWAIT, 'lbrynet-launch-node', 'lbrynet-launch-node', str(port),
                ipAddress, str(startPort))
            nodes.append(node)
            port += 1
    except KeyboardInterrupt:
        '\nNetwork creation cancelled.'
        destroyNetwork(nodes)
        sys.exit(1)

    print '\n\n---------------\nNetwork running\n---------------\n'
    try:
        while 1:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        destroyNetwork(nodes)

if __name__ == '__main__':
    main()
