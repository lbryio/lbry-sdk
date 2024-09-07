import shutil
import tempfile
import unittest
import asyncio
import logging
import hashlib
from lbry.testcase import AsyncioTestCase
from lbry.conf import Config
from lbry.extras.daemon.storage import SQLiteStorage
from lbry.blob.blob_info import BlobInfo
from lbry.blob.blob_manager import BlobManager
from lbry.stream.descriptor import StreamDescriptor
from tests.test_utils import random_lbry_hash
from lbry.dht.peer import make_kademlia_peer

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


class StorageTest(AsyncioTestCase):
    async def asyncSetUp(self):
        self.conf = Config()
        self.storage = SQLiteStorage(self.conf, ':memory:')
        self.blob_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.blob_dir)
        self.blob_manager = BlobManager(asyncio.get_event_loop(), self.blob_dir, self.storage, self.conf)
        await self.storage.open()

    async def asyncTearDown(self):
        await self.storage.close()

    async def store_fake_blob(self, blob_hash, length=100):
        await self.storage.add_blobs((blob_hash, length, 0, 0), finished=True)

    async def store_fake_stream(self, stream_hash, blobs=None, file_name="fake_file", key="DEADBEEF"):
        blobs = blobs or [BlobInfo(1, 100, "DEADBEEF", 0, random_lbry_hash())]
        descriptor = StreamDescriptor(
            asyncio.get_event_loop(), self.blob_manager, file_name, key, file_name, blobs, stream_hash
        )
        sd_blob = await descriptor.make_sd_blob()
        await self.storage.store_stream(sd_blob, descriptor)
        return descriptor

    async def make_and_store_fake_stream(self, blob_count=2, stream_hash=None):
        stream_hash = stream_hash or random_lbry_hash()
        blobs = [
            BlobInfo(i + 1, 100, "DEADBEEF", 0, random_lbry_hash())
            for i in range(blob_count)
        ]
        await self.store_fake_stream(stream_hash, blobs)


class TestSQLiteStorage(StorageTest):
    async def test_setup(self):
        files = await self.storage.get_all_lbry_files()
        self.assertEqual(len(files), 0)
        blobs = await self.storage.get_all_blob_hashes()
        self.assertEqual(len(blobs), 0)

    async def test_store_blob(self):
        blob_hash = random_lbry_hash()
        await self.store_fake_blob(blob_hash)
        blob_hashes = await self.storage.get_all_blob_hashes()
        self.assertEqual(blob_hashes, [blob_hash])

    async def test_delete_blob(self):
        blob_hash = random_lbry_hash()
        await self.store_fake_blob(blob_hash)
        blob_hashes = await self.storage.get_all_blob_hashes()
        self.assertEqual(blob_hashes, [blob_hash])
        await self.storage.delete_blobs_from_db(blob_hashes)
        blob_hashes = await self.storage.get_all_blob_hashes()
        self.assertEqual(blob_hashes, [])

    async def test_supports_storage(self):
        claim_ids = [random_lbry_hash() for _ in range(10)]
        random_supports = [{
            "txid": random_lbry_hash(),
            "nout": i,
            "address": f"addr{i}",
            "amount": f"{i}.0"
        } for i in range(20)]
        expected_supports = {}
        for idx, claim_id in enumerate(claim_ids):
            await self.storage.save_supports({claim_id: random_supports[idx*2:idx*2+2]})
            for random_support in random_supports[idx*2:idx*2+2]:
                random_support['claim_id'] = claim_id
                expected_supports.setdefault(claim_id, []).append(random_support)

        supports = await self.storage.get_supports(claim_ids[0])
        self.assertEqual(supports, expected_supports[claim_ids[0]])
        all_supports = await self.storage.get_supports(*claim_ids)
        for support in all_supports:
            self.assertIn(support, expected_supports[support['claim_id']])


class StreamStorageTests(StorageTest):
    async def test_store_and_delete_stream(self):
        stream_hash = random_lbry_hash()
        descriptor = await self.store_fake_stream(stream_hash)
        files = await self.storage.get_all_lbry_files()
        self.assertListEqual(files, [])
        stream_hashes = await self.storage.get_all_stream_hashes()
        self.assertListEqual(stream_hashes, [stream_hash])
        await self.storage.delete_stream(descriptor)
        files = await self.storage.get_all_lbry_files()
        self.assertListEqual(files, [])
        stream_hashes = await self.storage.get_all_stream_hashes()
        self.assertListEqual(stream_hashes, [])


@unittest.SkipTest
class FileStorageTests(StorageTest):
    async def test_store_file(self):
        download_directory = self.db_dir
        out = await self.storage.get_all_lbry_files()
        self.assertEqual(len(out), 0)

        stream_hash = random_lbry_hash()
        sd_hash = random_lbry_hash()
        blob1 = random_lbry_hash()
        blob2 = random_lbry_hash()

        await self.store_fake_blob(sd_hash)
        await self.store_fake_blob(blob1)
        await self.store_fake_blob(blob2)

        await self.store_fake_stream(stream_hash, sd_hash)
        await self.store_fake_stream_blob(stream_hash, blob1, 1)
        await self.store_fake_stream_blob(stream_hash, blob2, 2)

        blob_data_rate = 0
        file_name = "test file"
        await self.storage.save_published_file(
            stream_hash, file_name, download_directory, blob_data_rate
        )

        files = await self.storage.get_all_lbry_files()
        self.assertEqual(1, len(files))


@unittest.SkipTest
class ContentClaimStorageTests(StorageTest):
    async def test_store_content_claim(self):
        download_directory = self.db_dir
        out = await self.storage.get_all_lbry_files()
        self.assertEqual(len(out), 0)

        stream_hash = random_lbry_hash()
        sd_hash = fake_claim_info['value']['stream']['source']['source']

        # test that we can associate a content claim to a file
        # use the generated sd hash in the fake claim
        fake_outpoint = "%s:%i" % (fake_claim_info['txid'], fake_claim_info['nout'])

        await self.make_and_store_fake_stream(blob_count=2, stream_hash=stream_hash, sd_hash=sd_hash)
        blob_data_rate = 0
        file_name = "test file"
        await self.storage.save_published_file(
            stream_hash, file_name, download_directory, blob_data_rate
        )
        await self.storage.save_claims([fake_claim_info])
        await self.storage.save_content_claim(stream_hash, fake_outpoint)
        stored_content_claim = await self.storage.get_content_claim(stream_hash)
        self.assertDictEqual(stored_content_claim, fake_claim_info)

        stream_hashes = await self.storage.get_old_stream_hashes_for_claim_id(fake_claim_info['claim_id'],
                                                                              stream_hash)
        self.assertListEqual(stream_hashes, [])

        # test that we can't associate a claim update with a new stream to the file
        second_stream_hash, second_sd_hash = random_lbry_hash(), random_lbry_hash()
        await self.make_and_store_fake_stream(blob_count=2, stream_hash=second_stream_hash, sd_hash=second_sd_hash)
        with self.assertRaisesRegex(Exception, "stream mismatch"):
            await self.storage.save_content_claim(second_stream_hash, fake_outpoint)

        # test that we can associate a new claim update containing the same stream to the file
        update_info = deepcopy(fake_claim_info)
        update_info['txid'] = "beef0000" * 12
        update_info['nout'] = 0
        second_outpoint = "%s:%i" % (update_info['txid'], update_info['nout'])
        await self.storage.save_claims([update_info])
        await self.storage.save_content_claim(stream_hash, second_outpoint)
        update_info_result = await self.storage.get_content_claim(stream_hash)
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
            await self.storage.save_claims([invalid_update_info])
            await self.storage.save_content_claim(stream_hash, invalid_update_outpoint)
        current_claim_info = await self.storage.get_content_claim(stream_hash)
        # this should still be the previous update
        self.assertDictEqual(current_claim_info, update_info)


class UpdatePeersTest(StorageTest):
    async def test_update_get_peers(self):
        node_id = hashlib.sha384("1234".encode()).digest()
        args = (node_id, '73.186.148.72', 4444, None)
        fake_peer = make_kademlia_peer(*args)
        await self.storage.save_kademlia_peers([fake_peer])
        peers = await self.storage.get_persisted_kademlia_peers()
        self.assertTupleEqual(args, peers[0])
