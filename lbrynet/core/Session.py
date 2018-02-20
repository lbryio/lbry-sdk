import logging
import miniupnpc
from twisted.internet import threads, defer
from lbrynet.core.BlobManager import DiskBlobManager
from lbrynet.dht import node, peermanager, hashannouncer
from lbrynet.database.storage import SQLiteStorage
from lbrynet.core.RateLimiter import RateLimiter
from lbrynet.core.utils import generate_id
from lbrynet.core.PaymentRateManager import BasePaymentRateManager, NegotiatedPaymentRateManager
from lbrynet.core.BlobAvailability import BlobAvailabilityTracker

log = logging.getLogger(__name__)


class Session(object):
    """This class manages all important services common to any application that uses the network.

    the hash announcer, which informs other peers that this peer is
    associated with some hash. Usually, this means this peer has a
    blob identified by the hash in question, but it can be used for
    other purposes.

    the peer finder, which finds peers that are associated with some
    hash.

    the blob manager, which keeps track of which blobs have been
    downloaded and provides access to them,

    the rate limiter, which attempts to ensure download and upload
    rates stay below a set maximum

    upnp, which opens holes in compatible firewalls so that remote
    peers can connect to this peer.
    """

    def __init__(self, blob_data_payment_rate, db_dir=None,
                 node_id=None, peer_manager=None, dht_node_port=None,
                 known_dht_nodes=None, peer_finder=None,
                 hash_announcer=None, blob_dir=None,
                 blob_manager=None, peer_port=None, use_upnp=True,
                 rate_limiter=None, wallet=None,
                 dht_node_class=node.Node, blob_tracker_class=None,
                 payment_rate_manager_class=None, is_generous=True, external_ip=None, storage=None):
        """@param blob_data_payment_rate: The default payment rate for blob data

        @param db_dir: The directory in which levelDB files should be stored

        @param node_id: The unique ID of this node

        @param peer_manager: An object which keeps track of all known
            peers. If None, a PeerManager will be created

        @param dht_node_port: The port on which the dht node should
            listen for incoming connections

        @param known_dht_nodes: A list of nodes which the dht node
        should use to bootstrap into the dht

        @param peer_finder: An object which is used to look up peers
            that are associated with some hash. If None, a
            DHTPeerFinder will be used, which looks for peers in the
            distributed hash table.

        @param hash_announcer: An object which announces to other
            peers that this peer is associated with some hash.  If
            None, and peer_port is not None, a DHTHashAnnouncer will
            be used. If None and peer_port is None, a
            DummyHashAnnouncer will be used, which will not actually
            announce anything.

        @param blob_dir: The directory in which blobs will be
            stored. If None and blob_manager is None, blobs will be
            stored in memory only.

        @param blob_manager: An object which keeps track of downloaded
            blobs and provides access to them. If None, and blob_dir
            is not None, a DiskBlobManager will be used, with the
            given blob_dir.  If None and blob_dir is None, a
            TempBlobManager will be used, which stores blobs in memory
            only.

        @param peer_port: The port on which other peers should connect
            to this peer

        @param use_upnp: Whether or not to try to open a hole in the
            firewall so that outside peers can connect to this peer's
            peer_port and dht_node_port

        @param rate_limiter: An object which keeps track of the amount
            of data transferred to and from this peer, and can limit
            that rate if desired

        @param wallet: An object which will be used to keep track of
            expected payments and which will pay peers.  If None, a
            wallet which uses the Point Trader system will be used,
            which is meant for testing only

        """
        self.db_dir = db_dir
        self.node_id = node_id
        self.peer_manager = peer_manager
        self.peer_finder = peer_finder
        self.hash_announcer = hash_announcer
        self.dht_node_port = dht_node_port
        self.known_dht_nodes = known_dht_nodes
        if self.known_dht_nodes is None:
            self.known_dht_nodes = []
        self.blob_dir = blob_dir
        self.blob_manager = blob_manager
        self.blob_tracker = None
        self.blob_tracker_class = blob_tracker_class or BlobAvailabilityTracker
        self.peer_port = peer_port
        self.use_upnp = use_upnp
        self.rate_limiter = rate_limiter
        self.external_ip = external_ip
        self.upnp_redirects = []
        self.wallet = wallet
        self.dht_node_class = dht_node_class
        self.dht_node = None
        self.base_payment_rate_manager = BasePaymentRateManager(blob_data_payment_rate)
        self.payment_rate_manager = None
        self.payment_rate_manager_class = payment_rate_manager_class or NegotiatedPaymentRateManager
        self.is_generous = is_generous
        self.storage = storage or SQLiteStorage(self.db_dir)

    def setup(self):
        """Create the blob directory and database if necessary, start all desired services"""

        log.debug("Starting session.")

        if self.node_id is None:
            self.node_id = generate_id()

        if self.wallet is None:
            from lbrynet.core.PTCWallet import PTCWallet
            self.wallet = PTCWallet(self.db_dir)

        if self.use_upnp is True:
            d = self._try_upnp()
        else:
            d = defer.succeed(True)
        d.addCallback(lambda _: self._setup_dht())
        d.addCallback(lambda _: self._setup_other_components())
        return d

    def shut_down(self):
        """Stop all services"""
        log.info('Stopping session.')
        ds = []
        if self.blob_tracker is not None:
            ds.append(defer.maybeDeferred(self.blob_tracker.stop))
        if self.dht_node is not None:
            ds.append(defer.maybeDeferred(self.dht_node.stop))
        if self.rate_limiter is not None:
            ds.append(defer.maybeDeferred(self.rate_limiter.stop))
        if self.wallet is not None:
            ds.append(defer.maybeDeferred(self.wallet.stop))
        if self.blob_manager is not None:
            ds.append(defer.maybeDeferred(self.blob_manager.stop))
        if self.use_upnp is True:
            ds.append(defer.maybeDeferred(self._unset_upnp))
        return defer.DeferredList(ds)

    def _try_upnp(self):

        log.debug("In _try_upnp")

        def get_free_port(upnp, port, protocol):
            # returns an existing mapping if it exists
            mapping = upnp.getspecificportmapping(port, protocol)
            if not mapping:
                return port
            if upnp.lanaddr == mapping[0]:
                return mapping
            return get_free_port(upnp, port + 1, protocol)

        def get_port_mapping(upnp, internal_port, protocol, description):
            # try to map to the requested port, if there is already a mapping use the next external
            # port available
            if protocol not in ['UDP', 'TCP']:
                raise Exception("invalid protocol")
            external_port = get_free_port(upnp, internal_port, protocol)
            if isinstance(external_port, tuple):
                log.info("Found existing UPnP redirect %s:%i (%s) to %s:%i, using it",
                         self.external_ip, external_port[1], protocol, upnp.lanaddr, internal_port)
                return external_port[1], protocol
            upnp.addportmapping(external_port, protocol, upnp.lanaddr, internal_port,
                                description, '')
            log.info("Set UPnP redirect %s:%i (%s) to %s:%i", self.external_ip, external_port,
                     protocol, upnp.lanaddr, internal_port)
            return external_port, protocol

        def threaded_try_upnp():
            if self.use_upnp is False:
                log.debug("Not using upnp")
                return False
            u = miniupnpc.UPnP()
            num_devices_found = u.discover()
            if num_devices_found > 0:
                u.selectigd()
                external_ip = u.externalipaddress()
                if external_ip != '0.0.0.0' and not self.external_ip:
                    # best not to rely on this external ip, the router can be behind layers of NATs
                    self.external_ip = external_ip
                if self.peer_port:
                    self.upnp_redirects.append(
                        get_port_mapping(u, self.peer_port, 'TCP', 'LBRY peer port')
                    )
                if self.dht_node_port:
                    self.upnp_redirects.append(
                        get_port_mapping(u, self.dht_node_port, 'UDP', 'LBRY DHT port')
                    )
                return True
            return False

        def upnp_failed(err):
            log.warning("UPnP failed. Reason: %s", err.getErrorMessage())
            return False

        d = threads.deferToThread(threaded_try_upnp)
        d.addErrback(upnp_failed)
        return d

    @defer.inlineCallbacks
    def _setup_dht(self):
        log.info("Starting DHT")
        self.dht_node = self.dht_node_class(
            self.hash_announcer,
            udpPort=self.dht_node_port,
            node_id=self.node_id,
            externalIP=self.external_ip,
            peerPort=self.peer_port,
            peer_manager=self.peer_manager,
            peer_finder=self.peer_finder,
        )
        yield self.dht_node.joinNetwork(self.known_dht_nodes)

    def _setup_other_components(self):
        log.debug("Setting up the rest of the components")

        if self.rate_limiter is None:
            self.rate_limiter = RateLimiter()

        if self.blob_manager is None:
            if self.blob_dir is None:
                raise Exception(
                    "TempBlobManager is no longer supported, specify BlobManager or db_dir")
            else:
                self.blob_manager = DiskBlobManager(
                    self.dht_node.hash_announcer, self.blob_dir, self.storage
                )

        if self.blob_tracker is None:
            self.blob_tracker = self.blob_tracker_class(
                self.blob_manager, self.dht_node.peer_finder, self.dht_node
            )
        if self.payment_rate_manager is None:
            self.payment_rate_manager = self.payment_rate_manager_class(
                self.base_payment_rate_manager, self.blob_tracker, self.is_generous
            )

        self.rate_limiter.start()
        d = self.storage.setup()
        d.addCallback(lambda _: self.blob_manager.setup())
        d.addCallback(lambda _: self.wallet.start())
        d.addCallback(lambda _: self.blob_tracker.start())
        return d

    def _unset_upnp(self):
        log.info("Unsetting upnp for session")

        def threaded_unset_upnp():
            u = miniupnpc.UPnP()
            num_devices_found = u.discover()
            if num_devices_found > 0:
                u.selectigd()
                for port, protocol in self.upnp_redirects:
                    if u.getspecificportmapping(port, protocol) is None:
                        log.warning(
                            "UPnP redirect for %s %d was removed by something else.",
                            protocol, port)
                    else:
                        u.deleteportmapping(port, protocol)
                        log.info("Removed UPnP redirect for %s %d.", protocol, port)
                self.upnp_redirects = []

        d = threads.deferToThread(threaded_unset_upnp)
        d.addErrback(lambda err: str(err))
        return d
