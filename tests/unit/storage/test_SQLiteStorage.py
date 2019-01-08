import os
import shutil
import tempfile
import logging
from copy import deepcopy
from twisted.internet import defer
from twisted.trial import unittest
from lbrynet import conf
from lbrynet.storage import SQLiteStorage, open_file_for_writing
from tests.test_utils import random_lbry_hash

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
    'amount': '1.0',
    'effective_amount': '1.0',
    'nout': 0,
    'txid': "deadbeef" * 8,
    'supports': [],
    'channel_claim_id': None,
    'channel_name': None
}


class FakeAnnouncer:
    def __init__(self):
        self._queue_size = 0

    def hash_queue_size(self):
        return self._queue_size


class MocSession:
    def __init__(self, storage):
        self.storage = storage


class StorageTest(unittest.TestCase):
    maxDiff = 5000

    @defer.inlineCallbacks
    def setUp(self):
        conf.initialize_settings(False)
        self.db_dir = tempfile.mkdtemp()
        self.storage = SQLiteStorage(':memory:')
        yield f2d(self.storage.open())

    @defer.inlineCallbacks
    def tearDown(self):
        yield f2d(self.storage.close())
        shutil.rmtree(self.db_dir)

    @defer.inlineCallbacks
    def store_fake_blob(self, blob_hash):
        yield f2d(self.storage.add_completed_blob(blob_hash))
    def store_fake_blob(self, blob_hash):
        yield self.storage.add_completed_blob(blob_hash)

    @defer.inlineCallbacks
    def store_fake_stream_blob(self, stream_hash, blob_hash, blob_num, length=100, iv="DEADBEEF"):
        blob_info = {
            'blob_hash': blob_hash, 'blob_num': blob_num, 'iv': iv
        }
        if length:
            blob_info['length'] = length
        yield f2d(self.storage.add_blobs_to_stream(stream_hash, [blob_info]))

    @defer.inlineCallbacks
    def store_fake_stream(self, stream_hash, sd_hash, file_name="fake_file", key="DEADBEEF",
                          blobs=[]):
        yield f2d(self.storage.store_stream(stream_hash, sd_hash, file_name, key,
                                           file_name, blobs))

    @defer.inlineCallbacks
    def make_and_store_fake_stream(self, blob_count=2, stream_hash=None, sd_hash=None):
        stream_hash = stream_hash or random_lbry_hash()
        sd_hash = sd_hash or random_lbry_hash()
        blobs = {
            i + 1: random_lbry_hash() for i in range(blob_count)
        }

        yield self.store_fake_blob(sd_hash)

        for blob in blobs.values():
            yield self.store_fake_blob(blob)

        yield self.store_fake_stream(stream_hash, sd_hash)

        for pos, blob in sorted(blobs.items(), key=lambda x: x[0]):
            yield self.store_fake_stream_blob(stream_hash, blob, pos)


class TestSetup(StorageTest):
    @defer.inlineCallbacks
    def test_setup(self):
        files = yield f2d(self.storage.get_all_lbry_files())
        self.assertEqual(len(files), 0)
        blobs = yield f2d(self.storage.get_all_blob_hashes())
        self.assertEqual(len(blobs), 0)


class BlobStorageTests(StorageTest):
    @defer.inlineCallbacks
    def test_store_blob(self):
        blob_hash = random_lbry_hash()
        yield self.store_fake_blob(blob_hash)
        blob_hashes = yield f2d(self.storage.get_all_blob_hashes())
        self.assertEqual(blob_hashes, [blob_hash])

    @defer.inlineCallbacks
    def test_delete_blob(self):
        blob_hash = random_lbry_hash()
        yield self.store_fake_blob(blob_hash)
        blob_hashes = yield f2d(self.storage.get_all_blob_hashes())
        self.assertEqual(blob_hashes, [blob_hash])
        yield f2d(self.storage.delete_blobs_from_db(blob_hashes))
        blob_hashes = yield f2d(self.storage.get_all_blob_hashes())
        self.assertEqual(blob_hashes, [])


class SupportsStorageTests(StorageTest):
    @defer.inlineCallbacks
    def test_supports_storage(self):
        claim_ids = [random_lbry_hash() for _ in range(10)]
        random_supports = [{
            "txid": random_lbry_hash(),
            "nout": i,
            "address": f"addr{i}",
            "amount": f"{i}.0"
        } for i in range(20)]
        expected_supports = {}
        for idx, claim_id in enumerate(claim_ids):
            yield f2d(self.storage.save_supports(claim_id, random_supports[idx*2:idx*2+2]))
            for random_support in random_supports[idx*2:idx*2+2]:
                random_support['claim_id'] = claim_id
                expected_supports.setdefault(claim_id, []).append(random_support)
        supports = yield f2d(self.storage.get_supports(claim_ids[0]))
        self.assertEqual(supports, expected_supports[claim_ids[0]])
        all_supports = yield f2d(self.storage.get_supports(*claim_ids))
        for support in all_supports:
            self.assertIn(support, expected_supports[support['claim_id']])


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

        stream_blobs = yield f2d(self.storage.get_blobs_for_stream(stream_hash))
        stream_blob_hashes = [b.blob_hash for b in stream_blobs]
        self.assertListEqual(stream_blob_hashes, [blob1, blob2])

        blob_hashes = yield f2d(self.storage.get_all_blob_hashes())
        self.assertSetEqual(set(blob_hashes), {sd_hash, blob1, blob2})

        stream_blobs = yield f2d(self.storage.get_blobs_for_stream(stream_hash))
        stream_blob_hashes = [b.blob_hash for b in stream_blobs]
        self.assertListEqual(stream_blob_hashes, [blob1, blob2])

        yield f2d(self.storage.set_should_announce(sd_hash, 1, 1))
        yield f2d(self.storage.set_should_announce(blob1, 1, 1))

        should_announce_count = yield f2d(self.storage.count_should_announce_blobs())
        self.assertEqual(should_announce_count, 2)
        should_announce_hashes = yield f2d(self.storage.get_blobs_to_announce())
        self.assertSetEqual(set(should_announce_hashes), {sd_hash, blob1})

        stream_hashes = yield f2d(self.storage.get_all_streams())
        self.assertListEqual(stream_hashes, [stream_hash])

    @defer.inlineCallbacks
    def test_delete_stream(self):
        stream_hash = random_lbry_hash()
        yield self.test_store_stream(stream_hash)
        yield f2d(self.storage.delete_stream(stream_hash))
        stream_hashes = yield f2d(self.storage.get_all_streams())
        self.assertListEqual(stream_hashes, [])

        stream_blobs = yield f2d(self.storage.get_blobs_for_stream(stream_hash))
        self.assertListEqual(stream_blobs, [])
        blob_hashes = yield f2d(self.storage.get_all_blob_hashes())
        self.assertListEqual(blob_hashes, [])


class FileStorageTests(StorageTest):

    @defer.inlineCallbacks
    def test_setup_output(self):
        file_name = 'encrypted_file_saver_test.tmp'
        self.assertFalse(os.path.isfile(file_name))
        written_to = yield f2d(open_file_for_writing(self.db_dir, file_name))
        self.assertEqual(written_to, file_name)
        self.assertTrue(os.path.isfile(os.path.join(self.db_dir, file_name)))

    @defer.inlineCallbacks
    def test_store_file(self):
        download_directory = self.db_dir
        out = yield f2d(self.storage.get_all_lbry_files())
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
        yield self.storage.save_published_file(
            stream_hash, file_name, download_directory, blob_data_rate
        )

        files = yield f2d(self.storage.get_all_lbry_files())
        self.assertEqual(1, len(files))


class ContentClaimStorageTests(StorageTest):

    @defer.inlineCallbacks
    def test_store_content_claim(self):
        download_directory = self.db_dir
        out = yield f2d(self.storage.get_all_lbry_files())
        self.assertEqual(len(out), 0)

        stream_hash = random_lbry_hash()
        sd_hash = fake_claim_info['value']['stream']['source']['source']

        # test that we can associate a content claim to a file
        # use the generated sd hash in the fake claim
        fake_outpoint = "%s:%i" % (fake_claim_info['txid'], fake_claim_info['nout'])

        yield self.make_and_store_fake_stream(blob_count=2, stream_hash=stream_hash, sd_hash=sd_hash)
        blob_data_rate = 0
        file_name = "test file"
        yield f2d(self.storage.save_published_file(
            stream_hash, file_name, download_directory, blob_data_rate
        ))
        yield f2d(self.storage.save_claims([fake_claim_info]))
        yield f2d(self.storage.save_content_claim(stream_hash, fake_outpoint))
        stored_content_claim = yield f2d(self.storage.get_content_claim(stream_hash))
        self.assertDictEqual(stored_content_claim, fake_claim_info)

        stream_hashes = yield f2d(self.storage.get_old_stream_hashes_for_claim_id(fake_claim_info['claim_id'],
                                                                              stream_hash))
        self.assertListEqual(stream_hashes, [])

        # test that we can't associate a claim update with a new stream to the file
        second_stream_hash, second_sd_hash = random_lbry_hash(), random_lbry_hash()
        yield self.make_and_store_fake_stream(blob_count=2, stream_hash=second_stream_hash, sd_hash=second_sd_hash)
        with self.assertRaisesRegex(Exception, "stream mismatch"):
            yield f2d(self.storage.save_content_claim(second_stream_hash, fake_outpoint))

        # test that we can associate a new claim update containing the same stream to the file
        update_info = deepcopy(fake_claim_info)
        update_info['txid'] = "beef0000" * 12
        update_info['nout'] = 0
        second_outpoint = "%s:%i" % (update_info['txid'], update_info['nout'])
        yield f2d(self.storage.save_claims([update_info]))
        yield f2d(self.storage.save_content_claim(stream_hash, second_outpoint))
        update_info_result = yield f2d(self.storage.get_content_claim(stream_hash))
        self.assertDictEqual(update_info_result, update_info)

        # test that we can't associate an update with a mismatching claim id
        invalid_update_info = deepcopy(fake_claim_info)
        invalid_update_info['txid'] = "beef0001" * 12
        invalid_update_info['nout'] = 0
        invalid_update_info['claim_id'] = "beef0002" * 5
        invalid_update_outpoint = "%s:%i" % (invalid_update_info['txid'], invalid_update_info['nout'])
        with self.assertRaisesRegex(Exception, "mismatching claim ids when updating stream "
                                               "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef "
                                               "vs beef0002beef0002beef0002beef0002beef0002"):
            yield f2d(self.storage.save_claims([invalid_update_info]))
            yield f2d(self.storage.save_content_claim(stream_hash, invalid_update_outpoint))
        current_claim_info = yield f2d(self.storage.get_content_claim(stream_hash))
        # this should still be the previous update
        self.assertDictEqual(current_claim_info, update_info)
