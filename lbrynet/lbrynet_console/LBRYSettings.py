import binascii
import json
import unqlite
import logging
import os
from twisted.internet import threads, defer


log = logging.getLogger(__name__)


class LBRYSettings(object):
    def __init__(self, db_dir):
        self.db_dir = db_dir
        self.db = None

    def start(self):
        return self._open_db()

    def stop(self):
        self.db = None
        return defer.succeed(True)

    def _open_db(self):
        log.debug("Opening %s as the settings database", str(os.path.join(self.db_dir, "settings.db")))
        self.db = unqlite.UnQLite(os.path.join(self.db_dir, "settings.db"))
        return defer.succeed(True)

    def save_lbryid(self, lbryid):

        def save_lbryid():
            self.db['lbryid'] = binascii.hexlify(lbryid)

        return threads.deferToThread(save_lbryid)

    def get_lbryid(self):

        def get_lbryid():
            if 'lbryid' in self.db:
                return binascii.unhexlify(self.db['lbryid'])
            else:
                return None

        return threads.deferToThread(get_lbryid)

    def get_server_running_status(self):

        def get_status():
            if 'server_running' in self.db:
                return json.loads(self.db['server_running'])
            else:
                return True

        return threads.deferToThread(get_status)

    def save_server_running_status(self, running):

        def save_status():
            self.db['server_running'] = json.dumps(running)

        return threads.deferToThread(save_status)

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

    def _get_payment_rate(self, rate_type):

        def get_rate():
            if rate_type in self.db:
                return json.loads(self.db[rate_type])
            else:
                return None

        return threads.deferToThread(get_rate)

    def _save_payment_rate(self, rate_type, rate):

        def save_rate():
            if rate is not None:
                self.db[rate_type] = json.dumps(rate)
            elif rate_type in self.db:
                del self.db[rate_type]

        return threads.deferToThread(save_rate)

    def get_query_handler_status(self, query_identifier):

        def get_status():
            if json.dumps(('q_h', query_identifier)) in self.db:
                return json.loads(self.db[(json.dumps(('q_h', query_identifier)))])
            else:
                return True

        return threads.deferToThread(get_status)

    def enable_query_handler(self, query_identifier):
        return self._set_query_handler_status(query_identifier, True)

    def disable_query_handler(self, query_identifier):
        return self._set_query_handler_status(query_identifier, False)

    def _set_query_handler_status(self, query_identifier, status):
        def set_status():
            self.db[json.dumps(('q_h', query_identifier))] = json.dumps(status)
        return threads.deferToThread(set_status)
