import os
import shutil
import tempfile
import logging
from copy import deepcopy
from twisted.internet import defer
from twisted.trial import unittest
from lbrynet import conf
from lbrynet.database.storage import SQLiteStorage, open_file_for_writing
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier
from lbrynet.file_manager.EncryptedFileDownloader import ManagedEncryptedFileDownloader
from lbrynet.file_manager.EncryptedFileManager import EncryptedFileManager
from lbrynet.tests.util import random_lbry_hash

log = logging.getLogger()


def blob_info_dict(blob_info):
    info = {
        "length": blob_info.length,
        "blob_num": blob_info.blob_num,
        "iv": blob_info.iv
    }
    if blob_info.length:
        info['blob_hash'] = blob_info.blob_hash
    return info


fake_claim_info = {
    'name': "test",
    'claim_id': 'deadbeef' * 5,
    'address': "bT6wc54qiUUYt34HQF9wnW8b2o2yQTXf2S",
    'claim_sequence': 1,
    'value':  {
        "version": "_0_0_1",
        "claimType": "streamType",
        "stream": {
          "source": {
            "source": 'deadbeef' * 12,
            "version": "_0_0_1",
            "contentType": "video/mp4",
            "sourceType": "lbry_sd_hash"
          },
          "version": "_0_0_1",
          "metadata": {
            "license": "LBRY inc",
            "description": "What is LBRY? An introduction with Alex Tabarrok",
            "language": "en",
            "title": "What is LBRY?",
            "author": "Samuel Bryan",
            "version": "_0_1_0",
            "nsfw": False,
            "licenseUrl": "",
            "preview": "",
            "thumbnail": "https://s3.amazonaws.com/files.lbry.io/logo.png"
          }
        }
    },
    'height': 10000,
    'amount': 1.0,
    'effective_amount': 1.0,
    'nout': 0,
    'txid': "deadbeef" * 8,
    'supports': [],
    'channel_claim_id': None,
    'channel_name': None
}


class FakeAnnouncer(object):
    def __init__(self):
        self._queue_size = 0

    def hash_queue_size(self):
        return self._queue_size


class MocSession(object):
    def __init__(self, storage):
        self.storage = storage


class StorageTest(unittest.TestCase):
    maxDiff = 5000

    @defer.inlineCallbacks
    def setUp(self):
        conf.initialize_settings(False)
        self.db_dir = tempfile.mkdtemp()
        self.storage = SQLiteStorage(self.db_dir)
        yield self.storage.setup()

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.storage.stop()
        shutil.rmtree(self.db_dir)

    @defer.inlineCallbacks
    def store_fake_blob(self, blob_hash, blob_length=100, next_announce=0, should_announce=0):
        yield self.storage.add_completed_blob(blob_hash, blob_length, next_announce,
                                              should_announce)
        yield self.storage.set_blob_status(blob_hash, "finished")

    @defer.inlineCallbacks
    def store_fake_stream_blob(self, stream_hash, blob_hash, blob_num, length=100, iv="DEADBEEF"):
        blob_info = {
            'blob_hash': blob_hash, 'blob_num': blob_num, 'iv': iv
        }
        if length:
            blob_info['length'] = length
        yield self.storage.add_blobs_to_stream(stream_hash, [blob_info])

    @defer.inlineCallbacks
    def store_fake_stream(self, stream_hash, sd_hash, file_name="fake_file", key="DEADBEEF",
                          blobs=[]):
        yield self.storage.store_stream(stream_hash, sd_hash, file_name, key,
                                           file_name, blobs)

    @defer.inlineCallbacks
    def make_and_store_fake_stream(self, blob_count=2, stream_hash=None, sd_hash=None):
        stream_hash = stream_hash or random_lbry_hash()
        sd_hash = sd_hash or random_lbry_hash()
        blobs = {
            i + 1: random_lbry_hash() for i in range(blob_count)
        }

        yield self.store_fake_blob(sd_hash)

        for blob in blobs.itervalues():
            yield self.store_fake_blob(blob)

        yield self.store_fake_stream(stream_hash, sd_hash)

        for pos, blob in sorted(blobs.iteritems(), key=lambda x: x[0]):
            yield self.store_fake_stream_blob(stream_hash, blob, pos)


class TestSetup(StorageTest):
    @defer.inlineCallbacks
    def test_setup(self):
        files = yield self.storage.get_all_lbry_files()
        self.assertEqual(len(files), 0)
        blobs = yield self.storage.get_all_blob_hashes()
        self.assertEqual(len(blobs), 0)


class BlobStorageTests(StorageTest):
    @defer.inlineCallbacks
    def test_store_blob(self):
        blob_hash = random_lbry_hash()
        yield self.store_fake_blob(blob_hash)
        blob_hashes = yield self.storage.get_all_blob_hashes()
        self.assertEqual(blob_hashes, [blob_hash])

    @defer.inlineCallbacks
    def test_delete_blob(self):
        blob_hash = random_lbry_hash()
        yield self.store_fake_blob(blob_hash)
        blob_hashes = yield self.storage.get_all_blob_hashes()
        self.assertEqual(blob_hashes, [blob_hash])
        yield self.storage.delete_blobs_from_db(blob_hashes)
        blob_hashes = yield self.storage.get_all_blob_hashes()
        self.assertEqual(blob_hashes, [])


class StreamStorageTests(StorageTest):
    @defer.inlineCallbacks
    def test_store_stream(self, stream_hash=None):
        stream_hash = stream_hash or random_lbry_hash()
        sd_hash = random_lbry_hash()
        blob1 = random_lbry_hash()
        blob2 = random_lbry_hash()

        yield self.store_fake_blob(sd_hash)
        yield self.store_fake_blob(blob1)
        yield self.store_fake_blob(blob2)

        yield self.store_fake_stream(stream_hash, sd_hash)
        yield self.store_fake_stream_blob(stream_hash, blob1, 1)
        yield self.store_fake_stream_blob(stream_hash, blob2, 2)

        stream_blobs = yield self.storage.get_blobs_for_stream(stream_hash)
        stream_blob_hashes = [b.blob_hash for b in stream_blobs]
        self.assertListEqual(stream_blob_hashes, [blob1, blob2])

        blob_hashes = yield self.storage.get_all_blob_hashes()
        self.assertSetEqual(set(blob_hashes), {sd_hash, blob1, blob2})

        stream_blobs = yield self.storage.get_blobs_for_stream(stream_hash)
        stream_blob_hashes = [b.blob_hash for b in stream_blobs]
        self.assertListEqual(stream_blob_hashes, [blob1, blob2])

        yield self.storage.set_should_announce(sd_hash, 1, 1)
        yield self.storage.set_should_announce(blob1, 1, 1)

        should_announce_count = yield self.storage.count_should_announce_blobs()
        self.assertEqual(should_announce_count, 2)
        should_announce_hashes = yield self.storage.get_blobs_to_announce(FakeAnnouncer())
        self.assertSetEqual(set(should_announce_hashes), {sd_hash, blob1})

        stream_hashes = yield self.storage.get_all_streams()
        self.assertListEqual(stream_hashes, [stream_hash])

    @defer.inlineCallbacks
    def test_delete_stream(self):
        stream_hash = random_lbry_hash()
        yield self.test_store_stream(stream_hash)
        yield self.storage.delete_stream(stream_hash)
        stream_hashes = yield self.storage.get_all_streams()
        self.assertListEqual(stream_hashes, [])

        stream_blobs = yield self.storage.get_blobs_for_stream(stream_hash)
        self.assertListEqual(stream_blobs, [])
        blob_hashes = yield self.storage.get_all_blob_hashes()
        self.assertListEqual(blob_hashes, [])


class FileStorageTests(StorageTest):
    @defer.inlineCallbacks
    def test_setup_output(self):
        file_name = 'encrypted_file_saver_test.tmp'
        self.assertFalse(os.path.isfile(file_name))
        written_to = yield open_file_for_writing(self.db_dir, file_name)
        self.assertTrue(written_to == file_name)
        self.assertTrue(os.path.isfile(os.path.join(self.db_dir, file_name)))

    @defer.inlineCallbacks
    def test_store_file(self):
        session = MocSession(self.storage)
        session.db_dir = self.db_dir
        sd_identifier = StreamDescriptorIdentifier()
        download_directory = self.db_dir
        manager = EncryptedFileManager(session, sd_identifier)
        out = yield manager.session.storage.get_all_lbry_files()
        self.assertEqual(len(out), 0)

        stream_hash = random_lbry_hash()
        sd_hash = random_lbry_hash()
        blob1 = random_lbry_hash()
        blob2 = random_lbry_hash()

        yield self.store_fake_blob(sd_hash)
        yield self.store_fake_blob(blob1)
        yield self.store_fake_blob(blob2)

        yield self.store_fake_stream(stream_hash, sd_hash)
        yield self.store_fake_stream_blob(stream_hash, blob1, 1)
        yield self.store_fake_stream_blob(stream_hash, blob2, 2)

        blob_data_rate = 0
        file_name = "test file"
        out = yield manager.session.storage.save_published_file(
            stream_hash, file_name, download_directory, blob_data_rate
        )
        rowid = yield manager.session.storage.get_rowid_for_stream_hash(stream_hash)
        self.assertEqual(out, rowid)

        files = yield manager.session.storage.get_all_lbry_files()
        self.assertEqual(1, len(files))

        status = yield manager.session.storage.get_lbry_file_status(rowid)
        self.assertEqual(status, ManagedEncryptedFileDownloader.STATUS_STOPPED)

        running = ManagedEncryptedFileDownloader.STATUS_RUNNING
        yield manager.session.storage.change_file_status(rowid, running)
        status = yield manager.session.storage.get_lbry_file_status(rowid)
        self.assertEqual(status, ManagedEncryptedFileDownloader.STATUS_RUNNING)


class ContentClaimStorageTests(StorageTest):
    @defer.inlineCallbacks
    def test_store_content_claim(self):
        session = MocSession(self.storage)
        session.db_dir = self.db_dir
        sd_identifier = StreamDescriptorIdentifier()
        download_directory = self.db_dir
        manager = EncryptedFileManager(session, sd_identifier)
        out = yield manager.session.storage.get_all_lbry_files()
        self.assertEqual(len(out), 0)

        stream_hash = random_lbry_hash()
        sd_hash = fake_claim_info['value']['stream']['source']['source']

        # test that we can associate a content claim to a file
        # use the generated sd hash in the fake claim
        fake_outpoint = "%s:%i" % (fake_claim_info['txid'], fake_claim_info['nout'])

        yield self.make_and_store_fake_stream(blob_count=2, stream_hash=stream_hash, sd_hash=sd_hash)
        blob_data_rate = 0
        file_name = "test file"
        yield manager.session.storage.save_published_file(
            stream_hash, file_name, download_directory, blob_data_rate
        )
        yield self.storage.save_claim(fake_claim_info)
        yield self.storage.save_content_claim(stream_hash, fake_outpoint)
        stored_content_claim = yield self.storage.get_content_claim(stream_hash)
        self.assertDictEqual(stored_content_claim, fake_claim_info)

        stream_hashes = yield self.storage.get_old_stream_hashes_for_claim_id(fake_claim_info['claim_id'],
                                                                              stream_hash)
        self.assertListEqual(stream_hashes, [])

        # test that we can't associate a claim update with a new stream to the file
        second_stream_hash, second_sd_hash = random_lbry_hash(), random_lbry_hash()
        yield self.make_and_store_fake_stream(blob_count=2, stream_hash=second_stream_hash, sd_hash=second_sd_hash)
        try:
            yield self.storage.save_content_claim(second_stream_hash, fake_outpoint)
            raise Exception("test failed")
        except Exception as err:
            self.assertTrue(err.message == "stream mismatch")

        # test that we can associate a new claim update containing the same stream to the file
        update_info = deepcopy(fake_claim_info)
        update_info['txid'] = "beef0000" * 12
        update_info['nout'] = 0
        second_outpoint = "%s:%i" % (update_info['txid'], update_info['nout'])
        yield self.storage.save_claim(update_info)
        yield self.storage.save_content_claim(stream_hash, second_outpoint)
        update_info_result = yield self.storage.get_content_claim(stream_hash)
        self.assertDictEqual(update_info_result, update_info)

        # test that we can't associate an update with a mismatching claim id
        invalid_update_info = deepcopy(fake_claim_info)
        invalid_update_info['txid'] = "beef0001" * 12
        invalid_update_info['nout'] = 0
        invalid_update_info['claim_id'] = "beef0002" * 5
        invalid_update_outpoint = "%s:%i" % (invalid_update_info['txid'], invalid_update_info['nout'])
        yield self.storage.save_claim(invalid_update_info)
        try:
            yield self.storage.save_content_claim(stream_hash, invalid_update_outpoint)
            raise Exception("test failed")
        except Exception as err:
            self.assertTrue(err.message == "invalid stream update")
        current_claim_info = yield self.storage.get_content_claim(stream_hash)
        # this should still be the previous update
        self.assertDictEqual(current_claim_info, update_info)
