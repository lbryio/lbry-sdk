import tempfile
import shutil
from twisted.trial import unittest
from twisted.internet import defer
from lbrynet.lbryfile.EncryptedFileMetadataManager import EncryptedFileMetadataManager
from lbrynet.core import Storage
from lbrynet.cryptstream.CryptBlob import CryptBlobInfo
from lbrynet.core.Error import NoSuchStreamHash
from tests.util import random_lbry_hash


class EncryptedFileMetadataManagerTest(unittest.TestCase):
    def setUp(self):
        self.db_dir = tempfile.mkdtemp()
        self.manager = EncryptedFileMetadataManager(Storage.FileStorage(self.db_dir))

    def tearDown(self):
        shutil.rmtree(self.db_dir)

    @defer.inlineCallbacks
    def test_basic(self):
        yield self.manager.setup()
        out = yield self.manager.get_all_streams()
        self.assertEqual(len(out), 0)

        stream_hash = random_lbry_hash()
        file_name = 'file_name'
        suggested_name = 'suggested_name'
        key = 'key'
        blob1 = CryptBlobInfo(random_lbry_hash(), 0, 10, 1)
        blob2 = CryptBlobInfo(random_lbry_hash(), 1, 10, 1)
        blobs = [blob1, blob2]

        # save stream
        yield self.manager.save_stream(stream_hash, file_name, key, suggested_name, blobs)

        out = yield self.manager.get_stream_info(stream_hash)

        self.assertEqual(key, out[0])
        self.assertEqual(file_name, out[1])

        out = yield self.manager.check_if_stream_exists(stream_hash)
        self.assertTrue(out)

        out = yield self.manager.get_blobs_for_stream(stream_hash)
        self.assertEqual(2, len(out))

        out = yield self.manager.get_all_streams()
        self.assertEqual(1, len(out))

        # add a blob to stream
        blob3 = CryptBlobInfo(random_lbry_hash(), 2, 10, 1)
        blobs = [blob3]
        out = yield self.manager.add_blobs_to_stream(stream_hash, blobs)
        out = yield self.manager.get_blobs_for_stream(stream_hash)
        self.assertEqual(3, len(out))

        out = yield self.manager.get_stream_of_blob(blob3.blob_hash)
        self.assertEqual(stream_hash, out)

        # check non existing stream
        with self.assertRaises(NoSuchStreamHash):
            out = yield self.manager.get_stream_info(random_lbry_hash())

        # check save of sd blob hash
        sd_blob_hash = random_lbry_hash()
        yield self.manager.save_sd_blob_hash_to_stream(stream_hash, sd_blob_hash)
        out = yield self.manager.get_sd_blob_hashes_for_stream(stream_hash)
        self.assertEqual(1, len(out))
        self.assertEqual(sd_blob_hash, out[0])

        # delete stream
        yield self.manager.delete_stream(stream_hash)
        out = yield self.manager.check_if_stream_exists(stream_hash)
        self.assertFalse(out)
