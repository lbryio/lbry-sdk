import logging
from twisted.internet import defer
from lbrynet.core.BlobManager import DiskBlobManager
from lbrynet.database.storage import SQLiteStorage
from lbrynet.core.RateLimiter import RateLimiter
from lbrynet.core.PaymentRateManager import BasePaymentRateManager, OnlyFreePaymentsManager

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

    def __init__(self, blob_data_payment_rate, db_dir=None, node_id=None, dht_node_port=None,
                 known_dht_nodes=None, peer_finder=None, hash_announcer=None, blob_dir=None, blob_manager=None,
                 peer_port=None, rate_limiter=None, wallet=None, external_ip=None, storage=None,
                 dht_node=None, peer_manager=None):
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
        self.peer_port = peer_port
        self.rate_limiter = rate_limiter
        self.external_ip = external_ip
        self.upnp_redirects = []
        self.wallet = wallet
        self.dht_node = dht_node
        self.base_payment_rate_manager = BasePaymentRateManager(blob_data_payment_rate)
        self.payment_rate_manager = OnlyFreePaymentsManager()
        self.storage = storage or SQLiteStorage(self.db_dir)

    def setup(self):
        """Create the blob directory and database if necessary, start all desired services"""

        log.debug("Starting session.")

        if self.dht_node is not None:
            if self.peer_manager is None:
                self.peer_manager = self.dht_node.peer_manager

            if self.peer_finder is None:
                self.peer_finder = self.dht_node.peer_finder

        d = self.storage.setup()
        d.addCallback(lambda _: self._setup_other_components())
        return d

    def shut_down(self):
        """Stop all services"""
        log.info('Stopping session.')
        ds = []
        if self.rate_limiter is not None:
            ds.append(defer.maybeDeferred(self.rate_limiter.stop))
        if self.blob_manager is not None:
            ds.append(defer.maybeDeferred(self.blob_manager.stop))
        return defer.DeferredList(ds)

    def _setup_other_components(self):
        log.debug("Setting up the rest of the components")

        if self.rate_limiter is None:
            self.rate_limiter = RateLimiter()

        if self.blob_manager is None:
            if self.blob_dir is None:
                raise Exception(
                    "TempBlobManager is no longer supported, specify BlobManager or db_dir")
            else:
                self.blob_manager = DiskBlobManager(self.blob_dir, self.storage, self.dht_node._dataStore)

        self.rate_limiter.start()
        d = self.blob_manager.setup()
        return d
