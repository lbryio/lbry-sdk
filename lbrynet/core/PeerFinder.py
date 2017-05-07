from twisted.internet import defer
from lbrynet.core.Peer import Peer

class DummyPeerFinder(object):
    """This class finds peers which have announced to the DHT that they have certain blobs"""
    def __init__(self):
        pass

    def run_manage_loop(self):
        pass

    def stop(self):
        pass

    def find_peers_for_blob(self, blob_hash):
        return defer.succeed([])

    def get_most_popular_hashes(self, num_to_return):
        return []


class ForceConnectPeerFinder(object):
    """ This peer finder forces a connection to some server"""
    def __init__(self, host, port):
        self.host = host
        self.port = port

    def run_manage_loop(self):
        pass

    def stop(self):
        pass

    def find_peers_for_blob(self, blob_hash):
        peer = Peer(self.host, self.port)
        return defer.succeed([peer])

    def get_most_popular_hashes(self, num_to_return):
        return []




