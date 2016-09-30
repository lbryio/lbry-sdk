from collections import defaultdict
import datetime


class Peer(object):
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.attempt_connection_at = None
        self.down_count = 0
        self.score = 0
        self.stats = defaultdict(float)  # {string stat_type, float count}

    def is_available(self):
        if self.attempt_connection_at is None or datetime.datetime.today() > self.attempt_connection_at:
            return True
        return False

    def report_up(self):
        self.down_count = 0
        self.attempt_connection_at = None

    def report_down(self):
        self.down_count += 1
        timeout_time = datetime.timedelta(seconds=60 * self.down_count)
        self.attempt_connection_at = datetime.datetime.today() + timeout_time

    def update_score(self, score_change):
        self.score += score_change

    def update_stats(self, stat_type, count):
        self.stats[stat_type] += count

    def __str__(self):
        return '{}:{}'.format(self.host, self.port)

    def __repr__(self):
        return 'Peer({!r}, {!r})'.format(self.host, self.port)
