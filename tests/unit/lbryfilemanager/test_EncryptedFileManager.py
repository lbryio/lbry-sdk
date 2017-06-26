from twisted.internet import defer
from twisted.trial import unittest
from lbrynet.file_manager.EncryptedFileDownloader import ManagedEncryptedFileDownloader
from lbrynet.file_manager.EncryptedFileManager import EncryptedFileManager
from tests.util import random_lbry_hash

class TestEncryptedFileManager(unittest.TestCase):

    @defer.inlineCallbacks
    def test_database_operations(self):
        # test database read/write functions in EncrypteFileManager

        class MocSession(object):
            pass

        session = MocSession()
        session.db_dir = '.'
        stream_info_manager  = None
        sd_identifier = None
        download_directory = '.'
        manager = EncryptedFileManager(session, stream_info_manager, sd_identifier, download_directory)
        yield manager._open_db()
        out = yield manager._get_all_lbry_files()
        self.assertEqual(len(out),0)

        stream_hash = random_lbry_hash()
        blob_data_rate = 0
        out = yield manager._save_lbry_file(stream_hash, blob_data_rate)
        rowid = yield manager._get_rowid_for_stream_hash(stream_hash)
        self.assertEqual(out, rowid)
        files = yield manager._get_all_lbry_files()
        self.assertEqual(1, len(files))
        yield manager._change_file_status(rowid, ManagedEncryptedFileDownloader.STATUS_RUNNING)
        out = yield manager._get_lbry_file_status(rowid)
        self.assertEqual(out, ManagedEncryptedFileDownloader.STATUS_RUNNING)
