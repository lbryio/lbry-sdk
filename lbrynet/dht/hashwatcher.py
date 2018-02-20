from collections import Counter
import datetime
from twisted.internet import task, threads


class HashWatcher(object):
    def __init__(self, clock=None):
        if not clock:
            from twisted.internet import reactor as clock
        self.ttl = 600
        self.hashes = []
        self.lc = task.LoopingCall(self._remove_old_hashes)
        self.lc.clock = clock

    def start(self):
        return self.lc.start(10)

    def stop(self):
        return self.lc.stop()

    def add_requested_hash(self, hashsum, contact):
        from_ip = contact.compact_ip
        matching_hashes = [h for h in self.hashes if h[0] == hashsum and h[2] == from_ip]
        if len(matching_hashes) == 0:
            self.hashes.append((hashsum, datetime.datetime.now(), from_ip))

    def most_popular_hashes(self, num_to_return=10):
        hash_counter = Counter([h[0] for h in self.hashes])
        return hash_counter.most_common(num_to_return)

    def _remove_old_hashes(self):
        remove_time = datetime.datetime.now() - datetime.timedelta(minutes=10)
        self.hashes = [h for h in self.hashes if h[1] < remove_time]
