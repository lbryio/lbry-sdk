import functools
import hashlib
import asyncio
import typing
import binascii

from lbrynet.peer import Peer
from lbrynet.dht import constants


class KademliaRPC:
    def __init__(self, protocol, loop: asyncio.BaseEventLoop, peer_port: int = 3333):
        self.protocol = protocol
        self.loop = loop
        self.peer_port = peer_port
        self.old_token_secret: bytes = None
        self.token_secret = constants.generate_id()

    def compact_address(self):
        compact_ip = functools.reduce(lambda buff, x: buff + bytearray([int(x)]),
                                      self.protocol.external_ip.split('.'), bytearray())
        compact_port = self.peer_port.to_bytes(2, 'big')
        return compact_ip + compact_port + self.protocol.node_id

    @staticmethod
    def ping():
        return b'pong'

    def store(self, rpc_contact: Peer, blob_hash: bytes, token: bytes, port: int,
              original_publisher_id: bytes, age: int) -> bytes:
        if original_publisher_id is None:
            original_publisher_id = rpc_contact.node_id
        rpc_contact.update_tcp_port(port)
        if self.loop.time() - self.protocol.started_listening_time < constants.token_secret_refresh_interval:
            pass
        elif not self.verify_token(token, rpc_contact.compact_ip()):
            raise ValueError("Invalid token")
        now = int(self.loop.time())
        originally_published = now - age
        self.protocol.data_store.add_peer_to_blob(
            rpc_contact, blob_hash, rpc_contact.compact_address_tcp(), now, originally_published, original_publisher_id
        )
        return b'OK'

    def find_node(self, rpc_contact: Peer, key: bytes) -> typing.List[typing.Tuple[bytes, str, int]]:
        if len(key) != constants.hash_length:
            raise ValueError("invalid contact node_id length: %i" % len(key))

        contacts = self.protocol.routing_table.find_close_peers(key, sender_node_id=rpc_contact.node_id)
        contact_triples = []
        for contact in contacts:
            contact_triples.append((contact.node_id, contact.address, contact.udp_port))
        return contact_triples

    def find_value(self, rpc_contact: Peer, key: bytes):
        if len(key) != constants.hash_length:
            raise ValueError("invalid blob_exchange hash length: %i" % len(key))

        response = {
            b'token': self.make_token(rpc_contact.compact_ip()),
        }

        if self.protocol.protocol_version:
            response[b'protocolVersion'] = self.protocol.protocol_version

        # get peers we have stored for this blob_exchange
        has_other_peers = self.protocol.data_store.has_peers_for_blob(key)
        peers = []
        if has_other_peers:
            peers.extend(self.protocol.data_store.get_peers_for_blob(key))

        # if we don't have k storing peers to return and we have this hash locally, include our contact information
        if len(peers) < constants.k and binascii.hexlify(key).decode() in self.protocol.data_store.completed_blobs:
            peers.append(self.compact_address())
        if peers:
            response[key] = peers
        else:
            response[b'contacts'] = self.find_node(rpc_contact, key)
        return response

    def refresh_token(self):  # TODO: this needs to be called periodically
        self.old_token_secret = self.token_secret
        self.token_secret = constants.generate_id()

    def make_token(self, compact_ip):
        h = hashlib.new('sha384')
        h.update(self.token_secret + compact_ip)
        return h.digest()

    def verify_token(self, token, compact_ip):
        h = hashlib.new('sha384')
        h.update(self.token_secret + compact_ip)
        if self.old_token_secret and not token == h.digest():  # TODO: why should we be accepting the previous token?
            h = hashlib.new('sha384')
            h.update(self.old_token_secret + compact_ip)
            if not token == h.digest():
                return False
        return True
