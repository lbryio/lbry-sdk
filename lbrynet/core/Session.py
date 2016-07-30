import logging
import miniupnpc
from lbrynet.core.PTCWallet import PTCWallet
from lbrynet.core.BlobManager import DiskBlobManager, TempBlobManager
from lbrynet.dht import node
from lbrynet.core.PeerManager import PeerManager
from lbrynet.core.RateLimiter import RateLimiter
from lbrynet.core.client.DHTPeerFinder import DHTPeerFinder
from lbrynet.core.HashAnnouncer import DummyHashAnnouncer
from lbrynet.core.server.DHTHashAnnouncer import DHTHashAnnouncer
from lbrynet.core.utils import generate_id
from lbrynet.core.PaymentRateManager import BasePaymentRateManager
from twisted.internet import threads, defer


log = logging.getLogger(__name__)


class LBRYSession(object):
    """This class manages all important services common to any application that uses the network:
    the hash announcer, which informs other peers that this peer is associated with some hash. Usually,
    this means this peer has a blob identified by the hash in question, but it can be used for other
    purposes.
    the peer finder, which finds peers that are associated with some hash.
    the blob manager, which keeps track of which blobs have been downloaded and provides access to them,
    the rate limiter, which attempts to ensure download and upload rates stay below a set maximum,
    and upnp, which opens holes in compatible firewalls so that remote peers can connect to this peer."""
    def __init__(self, blob_data_payment_rate, db_dir=None, lbryid=None, peer_manager=None, dht_node_port=None,
                 known_dht_nodes=None, peer_finder=None, hash_announcer=None,
                 blob_dir=None, blob_manager=None, peer_port=None, use_upnp=True,
                 rate_limiter=None, wallet=None, dht_node_class=node.Node):
        """
        @param blob_data_payment_rate: The default payment rate for blob data

        @param db_dir: The directory in which levelDB files should be stored

        @param lbryid: The unique ID of this node

        @param peer_manager: An object which keeps track of all known peers. If None, a PeerManager will be created

        @param dht_node_port: The port on which the dht node should listen for incoming connections

        @param known_dht_nodes: A list of nodes which the dht node should use to bootstrap into the dht

        @param peer_finder: An object which is used to look up peers that are associated with some hash. If None,
            a DHTPeerFinder will be used, which looks for peers in the distributed hash table.

        @param hash_announcer: An object which announces to other peers that this peer is associated with some hash.
            If None, and peer_port is not None, a DHTHashAnnouncer will be used. If None and
            peer_port is None, a DummyHashAnnouncer will be used, which will not actually announce
            anything.

        @param blob_dir: The directory in which blobs will be stored. If None and blob_manager is None, blobs will
            be stored in memory only.

        @param blob_manager: An object which keeps track of downloaded blobs and provides access to them. If None,
            and blob_dir is not None, a DiskBlobManager will be used, with the given blob_dir.
            If None and blob_dir is None, a TempBlobManager will be used, which stores blobs in
            memory only.

        @param peer_port: The port on which other peers should connect to this peer

        @param use_upnp: Whether or not to try to open a hole in the firewall so that outside peers can connect to
            this peer's peer_port and dht_node_port

        @param rate_limiter: An object which keeps track of the amount of data transferred to and from this peer,
            and can limit that rate if desired

        @param wallet: An object which will be used to keep track of expected payments and which will pay peers.
            If None, a wallet which uses the Point Trader system will be used, which is meant for testing
            only

        @return:
        """
        self.db_dir = db_dir

        self.lbryid = lbryid

        self.peer_manager = peer_manager

        self.dht_node_port = dht_node_port
        self.known_dht_nodes = known_dht_nodes
        if self.known_dht_nodes is None:
            self.known_dht_nodes = []
        self.peer_finder = peer_finder
        self.hash_announcer = hash_announcer

        self.blob_dir = blob_dir
        self.blob_manager = blob_manager

        self.peer_port = peer_port

        self.use_upnp = use_upnp

        self.rate_limiter = rate_limiter

        self.external_ip = '127.0.0.1'

        self.upnp_redirects = []

        self.wallet = wallet
        self.dht_node_class = dht_node_class
        self.dht_node = None

        self.base_payment_rate_manager = BasePaymentRateManager(blob_data_payment_rate)

    def setup(self):
        """Create the blob directory and database if necessary, start all desired services"""

        log.debug("Setting up the lbry session")

        if self.lbryid is None:
            self.lbryid = generate_id()

        if self.wallet is None:
            self.wallet = PTCWallet(self.db_dir)

        if self.peer_manager is None:
            self.peer_manager = PeerManager()

        if self.use_upnp is True:
            d = self._try_upnp()
        else:
            d = defer.succeed(True)

        if self.peer_finder is None:
            d.addCallback(lambda _: self._setup_dht())
        else:
            if self.hash_announcer is None and self.peer_port is not None:
                log.warning("The server has no way to advertise its available blobs.")
                self.hash_announcer = DummyHashAnnouncer()

        d.addCallback(lambda _: self._setup_other_components())
        return d

    def shut_down(self):
        """Stop all services"""
        ds = []
        if self.dht_node is not None:
            ds.append(defer.maybeDeferred(self.dht_node.stop))
        if self.rate_limiter is not None:
            ds.append(defer.maybeDeferred(self.rate_limiter.stop))
        if self.peer_finder is not None:
            ds.append(defer.maybeDeferred(self.peer_finder.stop))
        if self.hash_announcer is not None:
            ds.append(defer.maybeDeferred(self.hash_announcer.stop))
        if self.wallet is not None:
            ds.append(defer.maybeDeferred(self.wallet.stop))
        if self.blob_manager is not None:
            ds.append(defer.maybeDeferred(self.blob_manager.stop))
        if self.use_upnp is True:
            ds.append(defer.maybeDeferred(self._unset_upnp))
        return defer.DeferredList(ds)

    def _try_upnp(self):

        log.debug("In _try_upnp")

        def threaded_try_upnp():
            if self.use_upnp is False:
                log.debug("Not using upnp")
                return False
            u = miniupnpc.UPnP()
            num_devices_found = u.discover()
            if num_devices_found > 0:
                u.selectigd()
                external_ip = u.externalipaddress()
                if external_ip != '0.0.0.0':
                    self.external_ip = external_ip
                if self.peer_port is not None:
                    if u.getspecificportmapping(self.peer_port, 'TCP') is None:
                        u.addportmapping(self.peer_port, 'TCP', u.lanaddr, self.peer_port, 'LBRY peer port', '')
                        self.upnp_redirects.append((self.peer_port, 'TCP'))
                        log.info("Set UPnP redirect for TCP port %d", self.peer_port)
                    else:
                        log.warning("UPnP redirect already set for TCP port %d", self.peer_port)
                if self.dht_node_port is not None:
                    if u.getspecificportmapping(self.dht_node_port, 'UDP') is None:
                        u.addportmapping(self.dht_node_port, 'UDP', u.lanaddr, self.dht_node_port, 'LBRY DHT port', '')
                        self.upnp_redirects.append((self.dht_node_port, 'UDP'))
                        log.info("Set UPnP redirect for UPD port %d", self.dht_node_port)
                    else:
                        log.warning("UPnP redirect already set for UDP port %d", self.dht_node_port)
                return True
            return False

        def upnp_failed(err):
            log.warning("UPnP failed. Reason: %s", err.getErrorMessage())
            return False

        d = threads.deferToThread(threaded_try_upnp)
        d.addErrback(upnp_failed)
        return d

    def _setup_dht(self):

        from twisted.internet import reactor

        log.debug("Starting the dht")

        def match_port(h, p):
            return h, p

        def join_resolved_addresses(result):
            addresses = []
            for success, value in result:
                if success is True:
                    addresses.append(value)
            return addresses

        def start_dht(addresses):
            self.dht_node.joinNetwork(addresses)
            self.peer_finder.run_manage_loop()
            self.hash_announcer.run_manage_loop()
            return True

        ds = []
        for host, port in self.known_dht_nodes:
            d = reactor.resolve(host)
            d.addCallback(match_port, port)
            ds.append(d)

        self.dht_node = self.dht_node_class(
            udpPort=self.dht_node_port,
            lbryid=self.lbryid,
            externalIP=self.external_ip
        )
        self.peer_finder = DHTPeerFinder(self.dht_node, self.peer_manager)
        if self.hash_announcer is None:
            self.hash_announcer = DHTHashAnnouncer(self.dht_node, self.peer_port)

        dl = defer.DeferredList(ds)
        dl.addCallback(join_resolved_addresses)
        dl.addCallback(start_dht)
        return dl

    def _setup_other_components(self):
        log.debug("Setting up the rest of the components")

        if self.rate_limiter is None:
            self.rate_limiter = RateLimiter()

        if self.blob_manager is None:
            if self.blob_dir is None:
                self.blob_manager = TempBlobManager(self.hash_announcer)
            else:
                self.blob_manager = DiskBlobManager(self.hash_announcer, self.blob_dir, self.db_dir)

        self.rate_limiter.start()
        d1 = self.blob_manager.setup()
        d2 = self.wallet.start()

        dl = defer.DeferredList([d1, d2], fireOnOneErrback=True, consumeErrors=True)

        dl.addErrback(lambda err: err.value.subFailure)
        return dl

    def _unset_upnp(self):

        def threaded_unset_upnp():
            u = miniupnpc.UPnP()
            num_devices_found = u.discover()
            if num_devices_found > 0:
                u.selectigd()
                for port, protocol in self.upnp_redirects:
                    if u.getspecificportmapping(port, protocol) is None:
                        log.warning("UPnP redirect for %s %d was removed by something else.", protocol, port)
                    else:
                        u.deleteportmapping(port, protocol)
                        log.info("Removed UPnP redirect for %s %d.", protocol, port)
                self.upnp_redirects = []

        d = threads.deferToThread(threaded_unset_upnp)
        d.addErrback(lambda err: str(err))
        return d
