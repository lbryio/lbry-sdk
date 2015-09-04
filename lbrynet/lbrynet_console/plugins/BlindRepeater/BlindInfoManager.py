from twisted.internet import defer
from ValuableBlobInfo import ValuableBlobInfo
import os
import sqlite3
from twisted.enterprise import adbapi
from lbrynet.core.sqlite_helpers import rerun_if_locked


class BlindInfoManager(object):

    def __init__(self, db_dir, peer_manager):
        self.db_dir = db_dir
        self.db_conn = None
        self.peer_manager = peer_manager

    def setup(self):
        # check_same_thread=False is solely to quiet a spurious error that appears to be due
        # to a bug in twisted, where the connection is closed by a different thread than the
        # one that opened it. The individual connections in the pool are not used in multiple
        # threads.
        self.db_conn = adbapi.ConnectionPool('sqlite3', os.path.join(self.db_dir, "blind_info.db"),
                                             check_same_thread=False)

        def set_up_table(transaction):
            transaction.execute("create table if not exists valuable_blobs (" +
                                "    blob_hash text primary key, " +
                                "    blob_length integer, " +
                                "    reference text, " +
                                "    peer_host text, " +
                                "    peer_port integer, " +
                                "    peer_score text" +
                                ")")
        return self.db_conn.runInteraction(set_up_table)

    def stop(self):
        self.db = None
        return defer.succeed(True)

    def get_all_blob_infos(self):
        d = self._get_all_blob_infos()

        def make_blob_infos(blob_data):
            blob_infos = []
            for blob in blob_data:
                blob_hash, length, reference, peer_host, peer_port, peer_score = blob
                peer = self.peer_manager.get_peer(peer_host, peer_port)
                blob_info = ValuableBlobInfo(blob_hash, length, reference, peer, peer_score)
                blob_infos.append(blob_info)
            return blob_infos
        d.addCallback(make_blob_infos)
        return d

    def save_blob_infos(self, blob_infos):
        blobs = []
        for blob_info in blob_infos:
            blob_hash = blob_info.blob_hash
            length = blob_info.length
            reference = blob_info.reference
            peer_host = blob_info.peer.host
            peer_port = blob_info.peer.port
            peer_score = blob_info.peer_score
            blobs.append((blob_hash, length, reference, peer_host, peer_port, peer_score))
        return self._save_blob_infos(blobs)

    @rerun_if_locked
    def _get_all_blob_infos(self):
        return self.db_conn.runQuery("select * from valuable_blobs")

    @rerun_if_locked
    def _save_blob_infos(self, blobs):
        def save_infos(transaction):
            for blob in blobs:
                try:
                    transaction.execute("insert into valuable_blobs values (?, ?, ?, ?, ?, ?)",
                                        blob)
                except sqlite3.IntegrityError:
                    pass
        return self.db_conn.runInteraction(save_infos)