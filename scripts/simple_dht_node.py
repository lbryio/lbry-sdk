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
    nodeid = "9648996b4bef3ff41176668a0577f86aba7f1ea2996edd18f9c42430802c8085331345c5f0c44a7f352e2ba8ae59aaaa".decode("hex")
    node = Node(node_id=nodeid, externalIP='127.0.0.1', udpPort=21999, peerPort=1234)
    node.startNetwork()
    yield node.joinNetwork([("127.0.0.1", 21001)])

    print ""
    print ""
    print ""
    print ""
    print ""
    print ""

    yield node.announceHaveBlob("2bb150cb996b4bef3ff41176648a0577f86abb7f1ea2996edd18f9c42430802c8085331345c5f0c44a7f352e2ba8ae59".decode("hex"))

    log.info("Shutting down...")
    reactor.callLater(1, reactor.stop)


def main():
    log_support.configure_console(level='DEBUG')
    log_support.configure_twisted()
    reactor.callLater(0, run)
    log.info("Running reactor")
    reactor.run()


if __name__ == '__main__':
    sys.exit(main())
