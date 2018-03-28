from lbrynet.core import log_support

import logging.handlers
import sys
import traceback

from lbrynet.dht.node import Node

from twisted.internet import reactor, defer
from lbrynet.core.utils import generate_id


log = logging.getLogger(__name__)


def print_usage():
    print "Usage:\n%s UDP_PORT KNOWN_NODE_IP KNOWN_NODE_PORT HASH"


@defer.inlineCallbacks
def join_network(udp_port, known_nodes):
    lbryid = generate_id()

    log.info('Creating node')
    node = Node(udpPort=udp_port, node_id=lbryid)

    log.info('Joining network')
    yield node.joinNetwork(known_nodes)

    defer.returnValue(node)


@defer.inlineCallbacks
def get_hosts(node, h):
    log.info("Looking up %s", h)
    hosts = yield node.getPeersForBlob(h.decode("hex"))
    log.info("Hosts returned from the DHT: %s", hosts)


@defer.inlineCallbacks
def announce_hash(node, h):
    results = yield node.announceHaveBlob(h, 34567)
    for success, result in results:
        if success:
            log.info("Succeeded: %s", str(result))
        else:
            log.info("Failed: %s", str(result.getErrorMessage()))


# def get_args():
#     if len(sys.argv) < 5:
#         print_usage()
#         sys.exit(1)
#     udp_port = int(sys.argv[1])
#     known_nodes = [(sys.argv[2], int(sys.argv[3]))]
#     h = binascii.unhexlify(sys.argv[4])
#     return udp_port, known_nodes, h


@defer.inlineCallbacks
def connect(port=None):
    try:
        if port is None:
            raise Exception("need a port")
        known_nodes = [('54.236.227.82', 4444)]  # lbrynet1
        node = yield join_network(port, known_nodes)
        log.info("joined")
        reactor.callLater(3, find, node)
    except Exception:
        log.error("CAUGHT EXCEPTION")
        traceback.print_exc()
        log.info("Stopping reactor")
        yield reactor.stop()


def getApproximateTotalDHTNodes(node):
    from lbrynet.dht import constants
    # get the deepest bucket and the number of contacts in that bucket and multiply it
    # by the number of equivalently deep buckets in the whole DHT to get a really bad
    # estimate!
    bucket = node._routingTable._buckets[node._routingTable._kbucketIndex(node.node_id)]
    num_in_bucket = len(bucket._contacts)
    factor = (2 ** constants.key_bits) / (bucket.rangeMax - bucket.rangeMin)
    return num_in_bucket * factor


def getApproximateTotalHashes(node):
    # Divide the number of hashes we know about by k to get a really, really, really
    # bad estimate of the average number of hashes per node, then multiply by the
    # approximate number of nodes to get a horrendous estimate of the total number
    # of hashes in the DHT
    num_in_data_store = len(node._dataStore._dict)
    if num_in_data_store == 0:
        return 0
    return num_in_data_store * getApproximateTotalDHTNodes(node) / 8


@defer.inlineCallbacks
def find(node):
    try:
        log.info("Approximate number of nodes in DHT: %s", str(getApproximateTotalDHTNodes(node)))
        log.info("Approximate number of blobs in DHT: %s", str(getApproximateTotalHashes(node)))

        h = "578f5e82da7db97bfe0677826d452cc0c65406a8e986c9caa126af4ecdbf4913daad2f7f5d1fb0ffec17d0bf8f187f5a"
        peersFake = yield node.getPeersForBlob(h.decode("hex"))
        print peersFake
        peers = yield node.getPeersForBlob(h.decode("hex"))
        print peers

        # yield get_hosts(node, h)
    except Exception:
        log.error("CAUGHT EXCEPTION")
        traceback.print_exc()

    log.info("Stopping reactor")
    yield reactor.stop()



def main():
    log_support.configure_console(level='DEBUG')
    log_support.configure_twisted()
    reactor.callLater(0, connect, port=10001)
    log.info("Running reactor")
    reactor.run()


if __name__ == '__main__':
    sys.exit(main())
