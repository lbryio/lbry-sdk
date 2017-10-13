import logging
import requests
import miniupnpc
import argparse
from copy import deepcopy
from twisted.internet import reactor, defer
from twisted.web import resource
from twisted.web.server import Site

from lbrynet import conf
from lbrynet.core.log_support import configure_console
from lbrynet.dht.error import TimeoutError
conf.initialize_settings()

log = logging.getLogger("dht tool")
configure_console()
log.setLevel(logging.INFO)

from lbrynet.dht.node import Node
from lbrynet.dht.contact import Contact
from lbrynet.daemon.auth.server import AuthJSONRPCServer
from lbrynet.core.utils import generate_id

def get_external_ip_and_setup_upnp():
    try:
        u = miniupnpc.UPnP()
        u.discoverdelay = 200
        u.discover()
        u.selectigd()

        if u.getspecificportmapping(4444, "UDP"):
            u.deleteportmapping(4444, "UDP")
            log.info("Removed UPnP redirect for UDP 4444.")
        u.addportmapping(4444, 'UDP', u.lanaddr, 4444, 'LBRY DHT port', '')
        log.info("got external ip from upnp")
        return u.externalipaddress()
    except Exception:
        log.exception("derp")
        r = requests.get('https://api.ipify.org', {'format': 'json'})
        log.info("got external ip from ipify.org")
        return r.json()['ip']


class NodeRPC(AuthJSONRPCServer):
    def __init__(self, lbryid, seeds, node_port, rpc_port):
        AuthJSONRPCServer.__init__(self, False)
        self.root = None
        self.port = None
        self.seeds = seeds
        self.node_port = node_port
        self.rpc_port = rpc_port
        if lbryid:
            lbryid = lbryid.decode('hex')
        else:
            lbryid = generate_id()
        self.node_id = lbryid
        self.external_ip = get_external_ip_and_setup_upnp()
        self.node_port = node_port

    @defer.inlineCallbacks
    def setup(self):
        self.node = Node(node_id=self.node_id, udpPort=self.node_port,
                               externalIP=self.external_ip)
        hosts = []
        for hostname, hostport in self.seeds:
            host_ip = yield reactor.resolve(hostname)
            hosts.append((host_ip, hostport))
        log.info("connecting to dht")
        yield self.node.joinNetwork(tuple(hosts))
        log.info("connected to dht")
        if not self.announced_startup:
            self.announced_startup = True
            self.start_api()
        log.info("lbry id: %s (%i bytes)", self.node.node_id.encode('hex'), len(self.node.node_id))

    def start_api(self):
        root = resource.Resource()
        root.putChild('', self)
        self.port = reactor.listenTCP(self.rpc_port, Site(root), interface='localhost')
        log.info("started jsonrpc server")

    @defer.inlineCallbacks
    def jsonrpc_node_id_set(self, node_id):
        old_id = self.node.node_id
        self.node.stop()
        del self.node
        self.node_id = node_id.decode('hex')
        yield self.setup()
        msg = "changed dht id from %s to %s" % (old_id.encode('hex'),
                                                self.node.node_id.encode('hex'))
        defer.returnValue(msg)

    def jsonrpc_node_id_get(self):
        return self._render_response(self.node.node_id.encode('hex'))

    @defer.inlineCallbacks
    def jsonrpc_peer_find(self, node_id):
        node_id = node_id.decode('hex')
        contact = yield self.node.findContact(node_id)
        result = None
        if contact:
            result = (contact.address, contact.port)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def jsonrpc_peer_list_for_blob(self, blob_hash):
        peers = yield self.node.getPeersForBlob(blob_hash.decode('hex'))
        defer.returnValue(peers)

    @defer.inlineCallbacks
    def jsonrpc_ping(self, node_id):
        contact_host = yield self.jsonrpc_peer_find(node_id=node_id)
        if not contact_host:
            defer.returnValue("failed to find node")
        contact_ip, contact_port = contact_host
        contact = Contact(node_id.decode('hex'), contact_ip, contact_port, self.node._protocol)
        try:
            result = yield contact.ping()
        except TimeoutError:
            self.node.removeContact(contact.id)
            self.node._dataStore.removePeer(contact.id)
            result = {'error': 'timeout'}
        defer.returnValue(result)

    def get_routing_table(self):
        result = {}
        data_store = deepcopy(self.node._dataStore._dict)
        datastore_len = len(data_store)
        hosts = {}
        missing_contacts = []
        if datastore_len:
            for k, v in data_store.iteritems():
                for value, lastPublished, originallyPublished, originalPublisherID in v:
                    try:
                        contact = self.node._routingTable.getContact(originalPublisherID)
                    except ValueError:
                        if originalPublisherID.encode('hex') not in missing_contacts:
                            missing_contacts.append(originalPublisherID.encode('hex'))
                        continue
                    if contact in hosts:
                        blobs = hosts[contact]
                    else:
                        blobs = []
                    blobs.append(k.encode('hex'))
                    hosts[contact] = blobs

        contact_set = []
        blob_hashes = []
        result['buckets'] = {}

        for i in range(len(self.node._routingTable._buckets)):
            for contact in self.node._routingTable._buckets[i]._contacts:
                contacts = result['buckets'].get(i, [])
                if contact in hosts:
                    blobs = hosts[contact]
                    del hosts[contact]
                else:
                    blobs = []
                host = {
                    "address": contact.address,
                    "id": contact.id.encode("hex"),
                    "blobs": blobs,
                }
                for blob_hash in blobs:
                    if blob_hash not in blob_hashes:
                        blob_hashes.append(blob_hash)
                contacts.append(host)
                result['buckets'][i] = contacts
                contact_set.append(contact.id.encode("hex"))
        if hosts:
            result['datastore extra'] = [
                {
                    "id": host.id.encode('hex'),
                    "blobs": hosts[host],
                }
            for host in hosts]
        result['missing contacts'] = missing_contacts
        result['contacts'] = contact_set
        result['blob hashes'] = blob_hashes
        result['node id'] = self.node_id.encode('hex')
        return result

    def jsonrpc_routing_table_get(self):
        return self._render_response(self.get_routing_table())


def main():
    parser = argparse.ArgumentParser(description="Launch a dht node which responds to rpc commands")
    parser.add_argument("--node_port",
                        help=("The UDP port on which the node will listen for connections "
                              "from other dht nodes"),
                        type=int, default=4444)
    parser.add_argument("--rpc_port",
                        help="The TCP port on which the node will listen for rpc commands",
                        type=int, default=5280)
    parser.add_argument("--bootstrap_host",
                        help="The IP of a DHT node to be used to bootstrap into the network",
                        default='lbrynet1.lbry.io')
    parser.add_argument("--node_id",
                        help="The IP of a DHT node to be used to bootstrap into the network",
                        default=None)
    parser.add_argument("--bootstrap_port",
                        help="The port of a DHT node to be used to bootstrap into the network",
                        default=4444, type=int)

    args = parser.parse_args()
    seeds = [(args.bootstrap_host, args.bootstrap_port)]
    server = NodeRPC(args.node_id, seeds, args.node_port, args.rpc_port)
    reactor.addSystemEventTrigger('after', 'startup', server.setup)
    reactor.run()


if __name__ == "__main__":
    main()
