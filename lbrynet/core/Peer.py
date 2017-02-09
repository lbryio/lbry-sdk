import datetime
from collections import defaultdict
from lbrynet.core import utils


class Peer(object):
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.attempt_connection_at = None
        self.down_count = 0
        self.score = 0
        self.stats = defaultdict(float)  # {string stat_type, float count}

    def is_available(self):
        if self.attempt_connection_at is None or utils.today() > self.attempt_connection_at:
            return True
        return False

    def report_up(self):
        self.down_count = 0
        self.attempt_connection_at = None

    def report_down(self):
        self.down_count += 1
        timeout_time = datetime.timedelta(seconds=60 * self.down_count)
        self.attempt_connection_at = utils.today() + timeout_time

    def update_score(self, score_change):
        self.score += score_change

    def update_stats(self, stat_type, count):
        self.stats[stat_type] += count

    def __str__(self):
        return '{}:{}'.format(self.host, self.port)

    def __repr__(self):
        return 'Peer({!r}, {!r})'.format(self.host, self.port)


# A set of peers, ensure that there is only one peer with the same host and port
class PeerSet(object):
    def __init__(self, peer_list={}):
        # key: (host,port) value: peer
        self.peers = {}
        for peer in peer_list:
            self.peers[(peer.host,peer.port)] = peer

    def __iter__(self):
        return self.peers.values().__iter__()

    def __len__(self):
        return len(self.peers)

    def __getitem__(self, peer):
        return self.peers[(peer.host,peer.port)]

    def __delitem__(self, peer):
        del self.peers[(peer.host,peer.port)]

    def add(self, peer):
        self.peers[(peer.host,peer.port)] = peer

    def intersection(self,peer_set):
        out = PeerSet()
        for p in peer_set:
            if p in self:
                out.add(p)
        return out

    def get_peer(host,port):
        return self.peers[(host,port)]

    def __contains__(self, peer):
        return (peer.host, peer.port) in self.peers

