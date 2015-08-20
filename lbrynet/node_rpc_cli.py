"""
CLI for sending rpc commands to a DHT node
"""


from twisted.internet import reactor
from txjsonrpc.web.jsonrpc import Proxy
import argparse
import sys


def print_value(value):
    print value


def print_error(err):
    print err.getErrorMessage()


def shut_down():
    reactor.stop()


def main():
    parser = argparse.ArgumentParser(description="Send an rpc command to a dht node")
    parser.add_argument("rpc_command",
                        help="The rpc command to send to the dht node")
    parser.add_argument("--node_host",
                        help="The host of the node to connect to",
                        default="127.0.0.1")
    parser.add_argument("--node_port",
                        help="The port of the node to connect to",
                        default="8888")

    args = parser.parse_args()
    connect_string = 'http://%s:%s' % (args.node_host, args.node_port)
    proxy = Proxy(connect_string)

    d = proxy.callRemote(args.rpc_command)
    d.addCallbacks(print_value, print_error)
    d.addBoth(lambda _: shut_down())
    reactor.run()