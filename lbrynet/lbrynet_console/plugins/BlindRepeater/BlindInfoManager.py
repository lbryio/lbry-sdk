from twisted.internet import threads, defer
from ValuableBlobInfo import ValuableBlobInfo
from db_keys import BLOB_INFO_TYPE
import json
import leveldb


class BlindInfoManager(object):

    def __init__(self, db, peer_manager):
        self.db = db
        self.peer_manager = peer_manager

    def setup(self):
        return defer.succeed(True)

    def stop(self):
        self.db = None
        return defer.succeed(True)

    def get_all_blob_infos(self):
        d = threads.deferToThread(self._get_all_blob_infos)

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
        return threads.deferToThread(self._save_blob_infos, blobs)

    def _get_all_blob_infos(self):
        blob_infos = []
        for key, blob_info in self.db.RangeIter():
            key_type, blob_hash = json.loads(key)
            if key_type == BLOB_INFO_TYPE:
                blob_infos.append([blob_hash] + json.loads(blob_info))
        return blob_infos

    def _save_blob_infos(self, blobs):
        batch = leveldb.WriteBatch()
        for blob in blobs:
            try:
                self.db.Get(json.dumps((BLOB_INFO_TYPE, blob[0])))
            except KeyError:
                batch.Put(json.dumps((BLOB_INFO_TYPE, blob[0])), json.dumps(blob[1:]))
        self.db.Write(batch, sync=True)