import binascii
import functools
import json
import logging
import os

from twisted.internet import threads, defer
import unqlite


log = logging.getLogger(__name__)


def run_in_thread(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        return threads.deferToThread(fn, *args, **kwargs)
    return wrapped


class Settings(object):
    NAME = "settings.db"
    def __init__(self, db_dir):
        self.db_dir = db_dir
        self.db = None

    def start(self):
        return self._open_db()

    def stop(self):
        self.db.close()
        self.db = None
        return defer.succeed(True)

    def _open_db(self):
        filename = os.path.join(self.db_dir, self.NAME)
        log.debug("Opening %s as the settings database", filename)
        self.db = unqlite.UnQLite(filename)
        return defer.succeed(True)

    @run_in_thread
    def save_lbryid(self, lbryid):
        self.db['lbryid'] = binascii.hexlify(lbryid)
        self.db.commit()

    @run_in_thread
    def get_lbryid(self):
        if 'lbryid' in self.db:
            return binascii.unhexlify(self.db['lbryid'])
        else:
            return None

    @run_in_thread
    def get_server_running_status(self):
        if 'server_running' in self.db:
            return json.loads(self.db['server_running'])
        else:
            return True

    @run_in_thread
    def save_server_running_status(self, running):
        self.db['server_running'] = json.dumps(running)
        self.db.commit()

    def get_default_data_payment_rate(self):
        return self._get_payment_rate("default_data_payment_rate")

    def save_default_data_payment_rate(self, rate):
        return self._save_payment_rate("default_data_payment_rate", rate)

    def get_server_data_payment_rate(self):
        return self._get_payment_rate("server_data_payment_rate")

    def save_server_data_payment_rate(self, rate):
        return self._save_payment_rate("server_data_payment_rate", rate)

    def get_server_crypt_info_payment_rate(self):
        return self._get_payment_rate("server_crypt_info_payment_rate")

    def save_server_crypt_info_payment_rate(self, rate):
        return self._save_payment_rate("server_crypt_info_payment_rate", rate)

    @run_in_thread
    def _get_payment_rate(self, rate_type):
        if rate_type in self.db:
            return json.loads(self.db[rate_type])
        else:
            return None

    @run_in_thread
    def _save_payment_rate(self, rate_type, rate):
        if rate is not None:
            self.db[rate_type] = json.dumps(rate)
        elif rate_type in self.db:
            del self.db[rate_type]
        self.db.commit()

    @run_in_thread
    def get_query_handler_status(self, query_identifier):
        if json.dumps(('q_h', query_identifier)) in self.db:
            return json.loads(self.db[(json.dumps(('q_h', query_identifier)))])
        else:
            return True

    def enable_query_handler(self, query_identifier):
        return self._set_query_handler_status(query_identifier, True)

    def disable_query_handler(self, query_identifier):
        return self._set_query_handler_status(query_identifier, False)

    @run_in_thread
    def _set_query_handler_status(self, query_identifier, status):
        self.db[json.dumps(('q_h', query_identifier))] = json.dumps(status)
        self.db.commit()
