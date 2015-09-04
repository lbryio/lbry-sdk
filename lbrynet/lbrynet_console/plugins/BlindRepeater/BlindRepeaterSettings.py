from twisted.internet import threads, defer
import json
import unqlite
import os
from twisted.enterprise import adbapi
from lbrynet.core.sqlite_helpers import rerun_if_locked

class BlindRepeaterSettings(object):

    def __init__(self, db_dir):
        self.db_dir = db_dir
        self.unq_db = None
        self.sql_db = None

    def setup(self):
        self.unq_db = unqlite.UnQLite(os.path.join(self.db_dir, "blind_settings.db"))
        # check_same_thread=False is solely to quiet a spurious error that appears to be due
        # to a bug in twisted, where the connection is closed by a different thread than the
        # one that opened it. The individual connections in the pool are not used in multiple
        # threads.
        self.sql_db = adbapi.ConnectionPool('sqlite3', os.path.join(self.db_dir, "blind_peers.db"),
                                            check_same_thread=False)

        return self.sql_db.runQuery("create table if not exists approved_peers (" +
                                    "    ip_address text, " +
                                    "    port integer" +
                                    ")")

    def stop(self):
        self.unq_db = None
        self.sql_db = None
        return defer.succeed(True)

    def save_repeater_status(self, running):
        def save_status():
            self.unq_db["running"] = json.dumps(running)

        return threads.deferToThread(save_status)

    def get_repeater_saved_status(self):
        def get_status():
            if "running" in self.unq_db:
                return json.loads(self.unq_db['running'])
            else:
                return False

        return threads.deferToThread(get_status)

    def save_max_space(self, max_space):
        def save_space():
            self.unq_db['max_space'] = json.dumps(max_space)

        return threads.deferToThread(save_space)

    def get_saved_max_space(self):
        def get_space():
            if 'max_space' in self.unq_db:
                return json.loads(self.unq_db['max_space'])
            else:
                return 0

        return threads.deferToThread(get_space)

    @rerun_if_locked
    def save_approved_peer(self, host, port):
        return self.sql_db.runQuery("insert into approved_peers values (?, ?)",
                                    (host, port))

    @rerun_if_locked
    def remove_approved_peer(self, host, port):
        return self.sql_db.runQuery("delete from approved_peers where ip_address = ? and port = ?",
                                    (host, port))

    @rerun_if_locked
    def get_approved_peers(self):
        return self.sql_db.runQuery("select * from approved_peers")

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
        if rate_type in self.unq_db:
            return json.loads(self.unq_db[rate_type])
        else:
            return None

    def _save_rate(self, rate_type, rate):
        if rate is not None:
            self.unq_db[rate_type] = json.dumps(rate)
        elif rate_type in self.unq_db:
            del self.unq_db[rate_type]