from db_keys import SETTING_TYPE, PEER_TYPE
from twisted.internet import threads
import json


class BlindRepeaterSettings(object):

    def __init__(self, db):
        self.db = db

    def save_repeater_status(self, running):
        def save_status():
            self.db.Put(json.dumps((SETTING_TYPE, "running")), json.dumps(running), sync=True)

        return threads.deferToThread(save_status)

    def get_repeater_saved_status(self):
        def get_status():
            try:
                return json.loads(self.db.Get(json.dumps((SETTING_TYPE, "running"))))
            except KeyError:
                return False

        return threads.deferToThread(get_status)

    def save_max_space(self, max_space):
        def save_space():
            self.db.Put(json.dumps((SETTING_TYPE, "max_space")), str(max_space), sync=True)

        return threads.deferToThread(save_space)

    def get_saved_max_space(self):
        def get_space():
            try:
                return int(self.db.Get(json.dumps((SETTING_TYPE, "max_space"))))
            except KeyError:
                return 0

        return threads.deferToThread(get_space)

    def save_approved_peer(self, host, port):
        def add_peer():
            peer_string = json.dumps((PEER_TYPE, (host, port)))
            self.db.Put(peer_string, "", sync=True)

        return threads.deferToThread(add_peer)

    def remove_approved_peer(self, host, port):
        def remove_peer():
            peer_string = json.dumps((PEER_TYPE, (host, port)))
            self.db.Delete(peer_string, sync=True)

        return threads.deferToThread(remove_peer)

    def get_approved_peers(self):
        def get_peers():
            peers = []
            for k, v in self.db.RangeIter():
                key_type, peer_info = json.loads(k)
                if key_type == PEER_TYPE:
                    peers.append(peer_info)
            return peers

        return threads.deferToThread(get_peers)

    def get_data_payment_rate(self):
        return threads.deferToThread(self._get_rate, "data_payment_rate")

    def save_data_payment_rate(self, rate):
        return threads.deferToThread(self._save_rate, "data_payment_rate", rate)

    def get_valuable_info_payment_rate(self):
        return threads.deferToThread(self._get_rate, "valuable_info_rate")

    def save_valuable_info_payment_rate(self, rate):
        return threads.deferToThread(self._save_rate, "valuable_info_rate", rate)

    def get_valuable_hash_payment_rate(self):
        return threads.deferToThread(self._get_rate, "valuable_hash_rate")

    def save_valuable_hash_payment_rate(self, rate):
        return threads.deferToThread(self._save_rate, "valuable_hash_rate", rate)

    def _get_rate(self, rate_type):
        try:
            return json.loads(self.db.Get(json.dumps((SETTING_TYPE, rate_type))))
        except KeyError:
            return None

    def _save_rate(self, rate_type, rate):
        if rate is not None:
            self.db.Put(json.dumps((SETTING_TYPE, rate_type)), json.dumps(rate), sync=True)
        else:
            self.db.Delete(json.dumps((SETTING_TYPE, rate_type)), sync=True)