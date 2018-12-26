import asyncio
import random
import logging
import typing

from lbrynet.peer import Peer
from lbrynet.dht import constants
from lbrynet.dht.routing import kbucket
from lbrynet.dht.routing.distance import Distance

log = logging.getLogger(__name__)


class TreeRoutingTable:
    """ This class implements a routing table used by a Node class.

    The Kademlia routing table is a binary tree whFose leaves are k-buckets,
    where each k-bucket contains nodes with some common prefix of their IDs.
    This prefix is the k-bucket's position in the binary tree; it therefore
    covers some range of ID values, and together all of the k-buckets cover
    the entire n-bit ID (or key) space (with no overlap).

    @note: In this implementation, nodes in the tree (the k-buckets) are
    added dynamically, as needed; this technique is described in the 13-page
    version of the Kademlia paper, in section 2.4. It does, however, use the
    C{PING} RPC-based k-bucket eviction algorithm described in section 2.2 of
    that paper.
    """

    def __init__(self, parent_node_id: bytes, loop: asyncio.BaseEventLoop):
        self._loop = loop
        self._parent_node_id = parent_node_id
        self._buckets: typing.List[kbucket.KBucket] = [
            kbucket.KBucket(
                range_min=0, range_max=2 ** constants.hash_bits, node_id=self._parent_node_id
            )
        ]
        self._ongoing_replacements = set()
        self._lock = asyncio.Lock(loop=self._loop)

    def get_peers(self) -> typing.List[Peer]:
        contacts = []
        for i in range(len(self._buckets)):
            for contact in self._buckets[i]._contacts:
                contacts.append(contact)
        return contacts

    def _should_split(self, bucket_index: int, to_add: bytes) -> bool:
        #  https://stackoverflow.com/questions/32129978/highly-unbalanced-kademlia-routing-table/32187456#32187456
        if self._buckets[bucket_index].key_in_range(self._parent_node_id):
            return True
        contacts = self.get_peers()
        distance = Distance(self._parent_node_id)
        contacts.sort(key=lambda c: distance(c.node_id))
        kth_contact = contacts[-1] if len(contacts) < constants.k else contacts[constants.k - 1]
        return distance(to_add) < distance(kth_contact.node_id)

    async def _add_peer(self, peer: Peer):
        bucket_index = self._kbucket_index(peer.node_id)
        if self._buckets[bucket_index].add_peer(peer):
            return True
        # The bucket is full; see if it can be split (by checking if its range includes the host node's node_id)
        if self._should_split(bucket_index, peer.node_id):
            self._split_bucket(bucket_index)
            # Retry the insertion attempt
            result = await self._add_peer(peer)
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

            not_good_contacts = self._buckets[bucket_index].get_bad_or_unknown_peers()

            if not_good_contacts:
                to_replace = not_good_contacts[0]
            else:
                to_replace = self._buckets[bucket_index]._contacts[0]
            log.debug("pinging %s:%s", to_replace.address, to_replace.udp_port)
            try:
                await to_replace.ping()
                return False
            except asyncio.TimeoutError:
                log.debug("Replacing dead contact in bucket %i: %s:%i (%s) with %s:%i (%s)", bucket_index,
                          to_replace.address, to_replace.udp_port, to_replace.log_id(), peer.address,
                          peer.udp_port, peer.log_id())
                if to_replace in self._buckets[bucket_index]:
                    self._buckets[bucket_index].remove_peer(to_replace)
                return await self._add_peer(peer)

    async def add_peer(self, peer: Peer) -> bool:
        if peer.node_id == self._parent_node_id:
            return False
        await self._lock.acquire()
        try:
            return await self._add_peer(peer)
        finally:
            self._lock.release()

    def find_close_peers(self, key: bytes, count: typing.Optional[int] = None,
                         sender_node_id: typing.Optional[bytes] = None) -> typing.List[Peer]:
        exclude = [self._parent_node_id]
        if sender_node_id:
            exclude.append(sender_node_id)
        if key in exclude:
            exclude.remove(key)
        count = count or constants.k
        distance = Distance(key)
        contacts = self.get_peers()
        contacts = [c for c in contacts if c.node_id not in exclude]
        if contacts:
            contacts.sort(key=lambda c: distance(c.node_id))
            return contacts[:min(count, len(contacts))]
        return []

    def get_peer(self, contact_id: bytes) -> Peer:
        """
        @raise IndexError: No contact with the specified contact ID is known
                           by this node
        """
        return self._buckets[self._kbucket_index(contact_id)].get_peer(contact_id)

    def get_refresh_list(self, start_index: int = 0, force: bool = False) -> typing.List[bytes]:
        bucket_index = start_index
        refresh_ids = []
        now = int(self._loop.time())
        for bucket in self._buckets[start_index:]:
            if force or now - bucket.last_accessed >= constants.refresh_interval:
                searchID = self.midpoint_id_in_bucket_range(bucket_index)
                refresh_ids.append(searchID)
            bucket_index += 1
        return refresh_ids

    def remove_peer(self, peer: Peer) -> None:
        bucket_index = self._kbucket_index(peer.node_id)
        try:
            self._buckets[bucket_index].remove_peer(peer)
        except ValueError:
            return

    def touch_kbucket(self, key: bytes) -> None:
        self.touch_kbucket_by_index(self._kbucket_index(key))

    def touch_kbucket_by_index(self, bucket_index: int):
        self._buckets[bucket_index].last_accessed = int(self._loop.time())

    def _kbucket_index(self, key: bytes) -> int:
        i = 0
        for bucket in self._buckets:
            if bucket.key_in_range(key):
                return i
            else:
                i += 1
        return i

    def random_id_in_bucket_range(self, bucket_index: int) -> bytes:
        random_id = int(random.randrange(self._buckets[bucket_index].range_min, self._buckets[bucket_index].range_max))
        return random_id.to_bytes(constants.hash_length, 'big')

    def midpoint_id_in_bucket_range(self, bucket_index: int) -> bytes:
        half = int((self._buckets[bucket_index].range_max - self._buckets[bucket_index].range_min) // 2)
        return int(self._buckets[bucket_index].range_min + half).to_bytes(constants.hash_length, 'big')

    def _split_bucket(self, old_bucket_index: int) -> None:
        """ Splits the specified k-bucket into two new buckets which together
        cover the same range in the key/ID space

        @param old_bucket_index: The index of k-bucket to split (in this table's
                                 list of k-buckets)
        @type old_bucket_index: int
        """
        # Resize the range of the current (old) k-bucket
        old_bucket = self._buckets[old_bucket_index]
        split_point = old_bucket.range_max - (old_bucket.range_max - old_bucket.range_min) / 2
        # Create a new k-bucket to cover the range split off from the old bucket
        new_bucket = kbucket.KBucket(split_point, old_bucket.range_max, self._parent_node_id)
        old_bucket.range_max = split_point
        # Now, add the new bucket into the routing table tree
        self._buckets.insert(old_bucket_index + 1, new_bucket)
        # Finally, copy all nodes that belong to the new k-bucket into it...
        for contact in old_bucket._contacts:
            if new_bucket.key_in_range(contact.node_id):
                new_bucket.add_peer(contact)
        # ...and remove them from the old bucket
        for contact in new_bucket._contacts:
            old_bucket.remove_peer(contact)

    def _join_buckets(self):
        to_pop = [i for i, bucket in enumerate(self._buckets) if not len(bucket)]
        if not to_pop:
            return
        log.info("join buckets %i", len(to_pop))
        bucket_index_to_pop = to_pop[0]
        assert len(self._buckets[bucket_index_to_pop]) == 0
        can_go_lower = bucket_index_to_pop - 1 >= 0
        can_go_higher = bucket_index_to_pop + 1 < len(self._buckets)
        assert can_go_higher or can_go_lower
        bucket = self._buckets[bucket_index_to_pop]
        if can_go_lower and can_go_higher:
            midpoint = ((bucket.range_max - bucket.range_min) // 2) + bucket.range_min
            self._buckets[bucket_index_to_pop - 1].range_max = midpoint - 1
            self._buckets[bucket_index_to_pop + 1].range_min = midpoint
        elif can_go_lower:
            self._buckets[bucket_index_to_pop - 1].range_max = bucket.range_max
        elif can_go_higher:
            self._buckets[bucket_index_to_pop + 1].range_min = bucket.range_min
        self._buckets.remove(bucket)
        return self._join_buckets()

    def contact_in_routing_table(self, address_tuple: typing.Tuple[str, int]) -> bool:
        for bucket in self._buckets:
            for contact in bucket.get_peers(sort_distance_to=False):
                if address_tuple[0] == contact.address and address_tuple[1] == contact.udp_port:
                    return True
        return False

    def buckets_with_contacts(self) -> int:
        count = 0
        for bucket in self._buckets:
            if len(bucket):
                count += 1
        return count
