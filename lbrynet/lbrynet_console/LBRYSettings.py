import binascii
import json
import leveldb
import logging
import os
from twisted.internet import threads, defer


class LBRYSettings(object):
    def __init__(self, db_dir):
        self.db_dir = db_dir
        self.db = None

    def start(self):
        return threads.deferToThread(self._open_db)

    def stop(self):
        self.db = None
        return defer.succeed(True)

    def _open_db(self):
        logging.debug("Opening %s as the settings database", str(os.path.join(self.db_dir, "settings.db")))
        self.db = leveldb.LevelDB(os.path.join(self.db_dir, "settings.db"))

    def save_lbryid(self, lbryid):

        def save_lbryid():
            self.db.Put("lbryid", binascii.hexlify(lbryid), sync=True)

        return threads.deferToThread(save_lbryid)

    def get_lbryid(self):

        def get_lbryid():
            try:
                return binascii.unhexlify(self.db.Get("lbryid"))
            except KeyError:
                return None

        return threads.deferToThread(get_lbryid)

    def get_server_running_status(self):

        def get_status():
            try:
                return json.loads(self.db.Get("server_running"))
            except KeyError:
                return True

        return threads.deferToThread(get_status)

    def save_server_running_status(self, running):

        def save_status():
            self.db.Put("server_running", json.dumps(running), sync=True)

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
            try:
                return json.loads(self.db.Get(rate_type))
            except KeyError:
                return None

        return threads.deferToThread(get_rate)

    def _save_payment_rate(self, rate_type, rate):

        def save_rate():
            if rate is not None:
                self.db.Put(rate_type, json.dumps(rate), sync=True)
            else:
                self.db.Delete(rate_type, sync=True)

        return threads.deferToThread(save_rate)

    def get_query_handler_status(self, query_identifier):

        def get_status():
            try:
                return json.loads(self.db.Get(json.dumps(('q_h', query_identifier))))
            except KeyError:
                return True

        return threads.deferToThread(get_status)

    def enable_query_handler(self, query_identifier):
        return self._set_query_handler_status(query_identifier, True)

    def disable_query_handler(self, query_identifier):
        return self._set_query_handler_status(query_identifier, False)

    def _set_query_handler_status(self, query_identifier, status):
        def set_status():
            self.db.Put(json.dumps(('q_h', query_identifier)), json.dumps(status), sync=True)
        return threads.deferToThread(set_status)