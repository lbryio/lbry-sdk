
from collections import Counter
import datetime


class HashWatcher():
    def __init__(self, ttl=600):
        self.ttl = 600
        self.hashes = []
        self.next_tick = None

    def tick(self):

        from twisted.internet import reactor

        self._remove_old_hashes()
        self.next_tick = reactor.callLater(10, self.tick)

    def stop(self):
        if self.next_tick is not None:
            self.next_tick.cancel()
            self.next_tick = None

    def add_requested_hash(self, hashsum, from_ip):
        matching_hashes = [h for h in self.hashes if h[0] == hashsum and h[2] == from_ip]
        if len(matching_hashes) == 0:
            self.hashes.append((hashsum, datetime.datetime.now(), from_ip))

    def most_popular_hashes(self, num_to_return=10):
        hash_counter = Counter([h[0] for h in self.hashes])
        return hash_counter.most_common(num_to_return)

    def _remove_old_hashes(self):
        remove_time = datetime.datetime.now() - datetime.timedelta(minutes=10)
        self.hashes = [h for h in self.hashes if h[1] < remove_time]
