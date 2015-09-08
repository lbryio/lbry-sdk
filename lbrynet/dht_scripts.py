from lbrynet.dht.node import Node
import binascii
from twisted.internet import reactor, task
import logging
import sys
from lbrynet.core.utils import generate_id


log = logging.getLogger(__name__)


def print_usage():
    print "Usage:\n%s UDP_PORT KNOWN_NODE_IP KNOWN_NODE_PORT HASH"


def join_network(udp_port, known_nodes):
    lbryid = generate_id()

    log.info('Creating Node...')
    node = Node(udpPort=udp_port, lbryid=lbryid)

    log.info('Joining network...')
    d = node.joinNetwork(known_nodes)

    def log_network_size():
        log.info("Approximate number of nodes in DHT: %s", str(node.getApproximateTotalDHTNodes()))
        log.info("Approximate number of blobs in DHT: %s", str(node.getApproximateTotalHashes()))

    d.addCallback(lambda _: log_network_size())

    d.addCallback(lambda _: node)

    return d


def get_hosts(node, h):

    def print_hosts(hosts):
        print "Hosts returned from the DHT: "
        print hosts

    log.info("Looking up %s", h)
    d = node.getPeersForBlob(h)
    d.addCallback(print_hosts)
    return d


def announce_hash(node, h):
    d = node.announceHaveBlob(h, 34567)

    def log_results(results):
        for success, result in results:
            if success:
                log.info("Succeeded: %s", str(result))
            else:
                log.info("Failed: %s", str(result.getErrorMessage()))

    d.addCallback(log_results)
    return d


def get_args():
    if len(sys.argv) < 5:
        print_usage()
        sys.exit(1)
    udp_port = int(sys.argv[1])
    known_nodes = [(sys.argv[2], int(sys.argv[3]))]
    h = binascii.unhexlify(sys.argv[4])
    return udp_port, known_nodes, h


def run_dht_script(dht_func):
    log_format = "(%(asctime)s)[%(filename)s:%(lineno)s] %(funcName)s(): %(message)s"
    logging.basicConfig(level=logging.DEBUG, format=log_format)

    udp_port, known_nodes, h = get_args()

    d = task.deferLater(reactor, 0, join_network, udp_port, known_nodes)

    def run_dht_func(node):
        return dht_func(node, h)

    d.addCallback(run_dht_func)

    def log_err(err):
        log.error("An error occurred: %s", err.getTraceback())
        return err

    def shut_down():
        log.info("Shutting down")
        reactor.stop()

    d.addErrback(log_err)
    d.addBoth(lambda _: shut_down())
    reactor.run()


def get_hosts_for_hash_in_dht():
    run_dht_script(get_hosts)


def announce_hash_to_dht():
    run_dht_script(announce_hash)