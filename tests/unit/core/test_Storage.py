from twisted.internet import defer
from twisted.trial import unittest
from lbrynet.lbryfilemanager.EncryptedFileDownloader import ManagedEncryptedFileDownloader
from tests.util import random_lbry_hash
from lbrynet.core.Storage import MemoryStorage


class TestEncryptedFileManagerStorage(unittest.TestCase):

    @defer.inlineCallbacks
    def test_database_operations(self):
        # test database read/write functions in EncrypteFileManager
        storage = MemoryStorage()
        out = yield storage.get_all_lbry_files()
        self.assertEqual(len(out),0)

        stream_hash = random_lbry_hash()
        blob_data_rate = 0
        out = yield storage.save_lbry_file(stream_hash, blob_data_rate)
        rowid = yield storage.get_file_row_id(stream_hash)
        self.assertEqual(out, rowid)
        files = yield storage.get_all_lbry_files()
        self.assertEqual(1, len(files))
        yield storage.change_file_status(rowid, ManagedEncryptedFileDownloader.STATUS_RUNNING)
        out = yield storage.get_lbry_file_status(rowid)
        self.assertEqual(out, ManagedEncryptedFileDownloader.STATUS_RUNNING)
