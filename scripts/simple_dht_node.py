#!/usr/bin/env python

from lbrynet.core import log_support
import logging.handlers
import sys
import time
from pprint import pprint

from twisted.internet import defer, reactor
from lbrynet.dht.node import Node
import lbrynet.dht.constants
import lbrynet.dht.datastore
from lbrynet.tests.util import random_lbry_hash

log = logging.getLogger(__name__)


@defer.inlineCallbacks
def run():
    node = Node(externalIP='127.0.0.1', udpPort=21215)
    node.startNetwork()
    yield node.joinNetwork([("127.0.0.1", 21216)])
    node2 = Node(externalIP='127.0.0.1', udpPort=21217)
    node2.startNetwork()
    yield node2.joinNetwork([("127.0.0.1", 21216)])
    log.info("Shutting down...")
    reactor.callLater(0, reactor.stop)


def main():
    log_support.configure_console(level='DEBUG')
    log_support.configure_twisted()
    reactor.callLater(0, run)
    log.info("Running reactor")
    reactor.run()


if __name__ == '__main__':
    sys.exit(main())
