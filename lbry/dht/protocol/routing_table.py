import asyncio
import random
import logging
import typing
import itertools

from prometheus_client import Gauge

from lbry import utils
from lbry.dht import constants
from lbry.dht.protocol.distance import Distance
if typing.TYPE_CHECKING:
    from lbry.dht.peer import KademliaPeer, PeerManager

log = logging.getLogger(__name__)


class KBucket:
    """
    Kademlia K-bucket implementation.
    """
    peer_in_routing_table_metric = Gauge(
        "peers_in_routing_table", "Number of peers on routing table", namespace="dht_node",
        labelnames=("scope",)
    )
    peer_with_x_bit_colliding_metric = Gauge(
        "peer_x_bit_colliding", "Number of peers with at least X bits colliding with this node id",
        namespace="dht_node", labelnames=("amount",)
    )

    def __init__(self, peer_manager: 'PeerManager', range_min: int, range_max: int, node_id: bytes):
        """
        @param range_min: The lower boundary for the range in the n-bit ID
                         space covered by this k-bucket
        @param range_max: The upper boundary for the range in the ID space
                         covered by this k-bucket
        """
        self._peer_manager = peer_manager
        self.last_accessed = 0
        self.range_min = range_min
        self.range_max = range_max
        self.peers: typing.List['KademliaPeer'] = []
        self._node_id = node_id
        self._distance_to_self = Distance(node_id)

    def add_peer(self, peer: 'KademliaPeer') -> bool:
        """ Add contact to _contact list in the right order. This will move the
        contact to the end of the k-bucket if it is already present.

        @raise kademlia.kbucket.BucketFull: Raised when the bucket is full and
                                            the contact isn't in the bucket
                                            already

        @param peer: The contact to add
        @type peer: dht.contact._Contact
        """
        if peer in self.peers:
            # Move the existing contact to the end of the list
            # - using the new contact to allow add-on data
            #   (e.g. optimization-specific stuff) to pe updated as well
            self.peers.remove(peer)
            self.peers.append(peer)
            return True
        else:
            for i, _ in enumerate(self.peers):
                local_peer = self.peers[i]
                if local_peer.node_id == peer.node_id:
                    self.peers.remove(local_peer)
                    self.peers.append(peer)
                    return True
        if len(self.peers) < constants.K:
            self.peers.append(peer)
            self.peer_in_routing_table_metric.labels("global").inc()
            bits_colliding = utils.get_colliding_prefix_bits(peer.node_id, self._node_id)
            self.peer_with_x_bit_colliding_metric.labels(amount=bits_colliding).inc()
            return True
        else:
            return False
            # raise BucketFull("No space in bucket to insert contact")

    def get_peer(self, node_id: bytes) -> 'KademliaPeer':
        for peer in self.peers:
            if peer.node_id == node_id:
                return peer
        raise IndexError(node_id)

    def get_peers(self, count=-1, exclude_contact=None, sort_distance_to=None) -> typing.List['KademliaPeer']:
        """ Returns a list containing up to the first count number of contacts

        @param count: The amount of contacts to return (if 0 or less, return
                      all contacts)
        @type count: int
        @param exclude_contact: A node node_id to exclude; if this contact is in
                               the list of returned values, it will be
                               discarded before returning. If a C{str} is
                               passed as this argument, it must be the
                               contact's ID.
        @type exclude_contact: str

        @param sort_distance_to: Sort distance to the node_id, defaulting to the parent node node_id. If False don't
                                 sort the contacts

        @raise IndexError: If the number of requested contacts is too large

        @return: Return up to the first count number of contacts in a list
                If no contacts are present an empty is returned
        @rtype: list
        """
        peers = [peer for peer in self.peers if peer.node_id != exclude_contact]

        # Return all contacts in bucket
        if count <= 0:
            count = len(peers)

        # Get current contact number
        current_len = len(peers)

        # If count greater than k - return only k contacts
        if count > constants.K:
            count = constants.K

        if not current_len:
            return peers

        if sort_distance_to is False:
            pass
        else:
            sort_distance_to = sort_distance_to or self._node_id
            peers.sort(key=lambda c: Distance(sort_distance_to)(c.node_id))

        return peers[:min(current_len, count)]

    def get_bad_or_unknown_peers(self) -> typing.List['KademliaPeer']:
        peer = self.get_peers(sort_distance_to=False)
        return [
            peer for peer in peer
            if self._peer_manager.contact_triple_is_good(peer.node_id, peer.address, peer.udp_port) is not True
        ]

    def remove_peer(self, peer: 'KademliaPeer') -> None:
        self.peers.remove(peer)
        self.peer_in_routing_table_metric.labels("global").dec()
        bits_colliding = utils.get_colliding_prefix_bits(peer.node_id, self._node_id)
        self.peer_with_x_bit_colliding_metric.labels(amount=bits_colliding).dec()

    def key_in_range(self, key: bytes) -> bool:
        """ Tests whether the specified key (i.e. node ID) is in the range
        of the n-bit ID space covered by this k-bucket (in otherwords, it
        returns whether or not the specified key should be placed in this
        k-bucket)

        @param key: The key to test
        @type key: str or int

        @return: C{True} if the key is in this k-bucket's range, or C{False}
                 if not.
        @rtype: bool
        """
        return self.range_min <= self._distance_to_self(key) < self.range_max

    def __len__(self) -> int:
        return len(self.peers)

    def __contains__(self, item) -> bool:
        return item in self.peers


class TreeRoutingTable:
    """ This class implements a routing table used by a Node class.

    The Kademlia routing table is a binary tree whose leaves are k-buckets,
    where each k-bucket contains nodes with some common prefix of their IDs.
    This prefix is the k-bucket's position in the binary tree; it therefore
    covers some range of ID values, and together all of the k-buckets cover
    the entire n-bit ID (or key) space (with no overlap).

    @note: In this implementation, nodes in the tree (the k-buckets) are
    added dynamically, as needed; this technique is described in the 13-page
    version of the Kademlia paper, in section 2.4. It does, however, use the
    ping RPC-based k-bucket eviction algorithm described in section 2.2 of
    that paper.
    """
    bucket_in_routing_table_metric = Gauge(
        "buckets_in_routing_table", "Number of buckets on routing table", namespace="dht_node",
        labelnames=("scope",)
    )

    def __init__(self, loop: asyncio.AbstractEventLoop, peer_manager: 'PeerManager', parent_node_id: bytes,
                 split_buckets_under_index: int = constants.SPLIT_BUCKETS_UNDER_INDEX):
        self._loop = loop
        self._peer_manager = peer_manager
        self._parent_node_id = parent_node_id
        self._split_buckets_under_index = split_buckets_under_index
        self.buckets: typing.List[KBucket] = [
            KBucket(
                self._peer_manager, range_min=0, range_max=2 ** constants.HASH_BITS, node_id=self._parent_node_id
            )
        ]

    def get_peers(self) -> typing.List['KademliaPeer']:
        return list(itertools.chain.from_iterable(map(lambda bucket: bucket.peers, self.buckets)))

    def should_split(self, bucket_index: int, to_add: bytes) -> bool:
        #  https://stackoverflow.com/questions/32129978/highly-unbalanced-kademlia-routing-table/32187456#32187456
        if bucket_index < self._split_buckets_under_index:
            return True
        contacts = self.get_peers()
        distance = Distance(self._parent_node_id)
        contacts.sort(key=lambda c: distance(c.node_id))
        kth_contact = contacts[-1] if len(contacts) < constants.K else contacts[constants.K - 1]
        return distance(to_add) < distance(kth_contact.node_id)

    def find_close_peers(self, key: bytes, count: typing.Optional[int] = None,
                         sender_node_id: typing.Optional[bytes] = None) -> typing.List['KademliaPeer']:
        exclude = [self._parent_node_id]
        if sender_node_id:
            exclude.append(sender_node_id)
        count = count or constants.K
        distance = Distance(key)
        contacts = self.get_peers()
        contacts = [c for c in contacts if c.node_id not in exclude]
        if contacts:
            contacts.sort(key=lambda c: distance(c.node_id))
            return contacts[:min(count, len(contacts))]
        return []

    def get_peer(self, contact_id: bytes) -> 'KademliaPeer':
        """
        @raise IndexError: No contact with the specified contact ID is known
                           by this node
        """
        return self.buckets[self.kbucket_index(contact_id)].get_peer(contact_id)

    def get_refresh_list(self, start_index: int = 0, force: bool = False) -> typing.List[bytes]:
        bucket_index = start_index
        refresh_ids = []
        now = int(self._loop.time())
        for bucket in self.buckets[start_index:]:
            if force or now - bucket.last_accessed >= constants.REFRESH_INTERVAL:
                to_search = self.midpoint_id_in_bucket_range(bucket_index)
                refresh_ids.append(to_search)
            bucket_index += 1
        return refresh_ids

    def remove_peer(self, peer: 'KademliaPeer') -> None:
        if not peer.node_id:
            return
        bucket_index = self.kbucket_index(peer.node_id)
        try:
            self.buckets[bucket_index].remove_peer(peer)
            self._join_buckets()
        except ValueError:
            return

    def kbucket_index(self, key: bytes) -> int:
        i = 0
        for bucket in self.buckets:
            if bucket.key_in_range(key):
                return i
            else:
                i += 1
        return i

    def random_id_in_bucket_range(self, bucket_index: int) -> bytes:
        random_id = int(random.randrange(self.buckets[bucket_index].range_min, self.buckets[bucket_index].range_max))
        return Distance(
            self._parent_node_id
        )(random_id.to_bytes(constants.HASH_LENGTH, 'big')).to_bytes(constants.HASH_LENGTH, 'big')

    def midpoint_id_in_bucket_range(self, bucket_index: int) -> bytes:
        half = int((self.buckets[bucket_index].range_max - self.buckets[bucket_index].range_min) // 2)
        return Distance(self._parent_node_id)(
            int(self.buckets[bucket_index].range_min + half).to_bytes(constants.HASH_LENGTH, 'big')
        ).to_bytes(constants.HASH_LENGTH, 'big')

    def split_bucket(self, old_bucket_index: int) -> None:
        """ Splits the specified k-bucket into two new buckets which together
        cover the same range in the key/ID space

        @param old_bucket_index: The index of k-bucket to split (in this table's
                                 list of k-buckets)
        @type old_bucket_index: int
        """
        # Resize the range of the current (old) k-bucket
        old_bucket = self.buckets[old_bucket_index]
        split_point = old_bucket.range_max - (old_bucket.range_max - old_bucket.range_min) // 2
        # Create a new k-bucket to cover the range split off from the old bucket
        new_bucket = KBucket(self._peer_manager, split_point, old_bucket.range_max, self._parent_node_id)
        old_bucket.range_max = split_point
        # Now, add the new bucket into the routing table tree
        self.buckets.insert(old_bucket_index + 1, new_bucket)
        # Finally, copy all nodes that belong to the new k-bucket into it...
        for contact in old_bucket.peers:
            if new_bucket.key_in_range(contact.node_id):
                new_bucket.add_peer(contact)
        # ...and remove them from the old bucket
        for contact in new_bucket.peers:
            old_bucket.remove_peer(contact)
        self.bucket_in_routing_table_metric.labels("global").set(len(self.buckets))

    def _join_buckets(self):
        if len(self.buckets) == 1:
            return
        to_pop = [i for i, bucket in enumerate(self.buckets) if len(bucket) == 0]
        if not to_pop:
            return
        log.info("join buckets %i", len(to_pop))
        bucket_index_to_pop = to_pop[0]
        assert len(self.buckets[bucket_index_to_pop]) == 0
        can_go_lower = bucket_index_to_pop - 1 >= 0
        can_go_higher = bucket_index_to_pop + 1 < len(self.buckets)
        assert can_go_higher or can_go_lower
        bucket = self.buckets[bucket_index_to_pop]
        if can_go_lower and can_go_higher:
            midpoint = ((bucket.range_max - bucket.range_min) // 2) + bucket.range_min
            self.buckets[bucket_index_to_pop - 1].range_max = midpoint - 1
            self.buckets[bucket_index_to_pop + 1].range_min = midpoint
        elif can_go_lower:
            self.buckets[bucket_index_to_pop - 1].range_max = bucket.range_max
        elif can_go_higher:
            self.buckets[bucket_index_to_pop + 1].range_min = bucket.range_min
        self.buckets.remove(bucket)
        self.bucket_in_routing_table_metric.labels("global").set(len(self.buckets))
        return self._join_buckets()

    def buckets_with_contacts(self) -> int:
        count = 0
        for bucket in self.buckets:
            if len(bucket) > 0:
                count += 1
        return count

    async def add_peer(self, peer: 'KademliaPeer', probe: typing.Callable[['KademliaPeer'], typing.Awaitable]):
        if not peer.node_id:
            log.warning("Tried adding a peer with no node id!")
            return False
        for my_peer in self.get_peers():
            if (my_peer.address, my_peer.udp_port) == (peer.address, peer.udp_port) and my_peer.node_id != peer.node_id:
                self.remove_peer(my_peer)
                self._join_buckets()
        bucket_index = self.kbucket_index(peer.node_id)
        if self.buckets[bucket_index].add_peer(peer):
            return True

        # The bucket is full; see if it can be split (by checking if its range includes the host node's node_id)
        if self.should_split(bucket_index, peer.node_id):
            self.split_bucket(bucket_index)
            # Retry the insertion attempt
            result = await self.add_peer(peer, probe)
            self._join_buckets()
            return result
        else:
            # We can't split the k-bucket
            #
            # The 13 page kademlia paper specifies that the least recently contacted node in the bucket
            # shall be pinged. If it fails to reply it is replaced with the new contact. If the ping is successful
            # the new contact is ignored and not added to the bucket (sections 2.2 and 2.4).
            #
            # A reasonable extension to this is BEP 0005, which extends the above:
            #
            #    Not all nodes that we learn about are equal. Some are "good" and some are not.
            #    Many nodes using the DHT are able to send queries and receive responses,
            #    but are not able to respond to queries from other nodes. It is important that
            #    each node's routing table must contain only known good nodes. A good node is
            #    a node has responded to one of our queries within the last 15 minutes. A node
            #    is also good if it has ever responded to one of our queries and has sent us a
            #    query within the last 15 minutes. After 15 minutes of inactivity, a node becomes
            #    questionable. Nodes become bad when they fail to respond to multiple queries
            #    in a row. Nodes that we know are good are given priority over nodes with unknown status.
            #
            # When there are bad or questionable nodes in the bucket, the least recent is selected for
            # potential replacement (BEP 0005). When all nodes in the bucket are fresh, the head (least recent)
            # contact is selected as described in section 2.2 of the kademlia paper. In both cases the new contact
            # is ignored if the pinged node replies.

            not_good_contacts = self.buckets[bucket_index].get_bad_or_unknown_peers()
            not_recently_replied = []
            for my_peer in not_good_contacts:
                last_replied = self._peer_manager.get_last_replied(my_peer.address, my_peer.udp_port)
                if not last_replied or last_replied + 60 < self._loop.time():
                    not_recently_replied.append(my_peer)
            if not_recently_replied:
                to_replace = not_recently_replied[0]
            else:
                to_replace = self.buckets[bucket_index].peers[0]
                last_replied = self._peer_manager.get_last_replied(to_replace.address, to_replace.udp_port)
                if last_replied and last_replied + 60 > self._loop.time():
                    return False
            log.debug("pinging %s:%s", to_replace.address, to_replace.udp_port)
            try:
                await probe(to_replace)
                return False
            except asyncio.TimeoutError:
                log.debug("Replacing dead contact in bucket %i: %s:%i with %s:%i ", bucket_index,
                          to_replace.address, to_replace.udp_port, peer.address, peer.udp_port)
                if to_replace in self.buckets[bucket_index]:
                    self.buckets[bucket_index].remove_peer(to_replace)
                return await self.add_peer(peer, probe)
