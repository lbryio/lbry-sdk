from lbrynet.core.Peer import Peer


class PeerManager(object):
    def __init__(self):
        self.peers = []

    def get_peer(self, host, port):
        for peer in self.peers:
            if peer.host == host and peer.port == port:
                return peer
        peer = Peer(host, port)
        self.peers.append(peer)
        return peer