# import tempfile
# import shutil
# import os
# import random
# import string
# from twisted.trial import unittest
# from twisted.internet import defer
#
# from tests.test_utils import random_lbry_hash
# from lbrynet.blob.blob_manager import BlobFileManager
# from lbrynet.storage import SQLiteStorage
# from lbrynet.peer import Peer
# from lbrynet import conf
# from lbrynet.cryptoutils import get_lbry_hash_obj
#
#
# class BlobManagerTest(unittest.TestCase):
#
#     @defer.inlineCallbacks
#     def setUp(self):
#         conf.initialize_settings(False)
#         self.blob_dir = tempfile.mkdtemp()
#         self.db_dir = tempfile.mkdtemp()
#         self.bm = BlobFileManager(self.blob_dir, SQLiteStorage(self.db_dir))
#         self.peer = Peer('somehost', 22)
#         yield self.bm.storage.setup()
#
#     @defer.inlineCallbacks
#     def tearDown(self):
#         yield self.bm.stop()
#         yield self.bm.storage.stop()
#         shutil.rmtree(self.blob_dir)
#         shutil.rmtree(self.db_dir)
#
#     @defer.inlineCallbacks
#     def _create_and_add_blob(self, should_announce=False):
#         # create and add blob to blob manager
#         data_len = random.randint(1, 1000)
#         data = b''.join(random.choice(string.ascii_lowercase).encode() for _ in range(data_len))
#
#         hashobj = get_lbry_hash_obj()
#         hashobj.update(data)
#         out = hashobj.hexdigest()
#         blob_hash = out
#
#         # create new blob
#         yield self.bm.setup()
#         blob = yield self.bm.get_blob(blob_hash, len(data))
#
#         writer, finished_d = yield blob.open_for_writing(self.peer)
#         yield writer.write(data)
#         yield self.bm.blob_completed(blob, should_announce)
#
#         # check to see if blob is there
#         self.assertTrue(os.path.isfile(os.path.join(self.blob_dir, blob_hash)))
#         blobs = yield self.bm.get_all_verified_blobs()
#         self.assertIn(blob_hash, blobs)
#         defer.returnValue(blob_hash)
#
#     @defer.inlineCallbacks
#     def test_create_blob(self):
#         blob_hashes = []
#
#         # create a bunch of blobs
#         for i in range(0, 10):
#             blob_hash = yield self._create_and_add_blob()
#             blob_hashes.append(blob_hash)
#         blobs = yield self.bm.get_all_verified_blobs()
#         self.assertEqual(10, len(blobs))
#
#     @defer.inlineCallbacks
#     def test_delete_blob(self):
#         # create blob
#         blob_hash = yield self._create_and_add_blob()
#         blobs = yield self.bm.get_all_verified_blobs()
#         self.assertEqual(len(blobs), 1)
#
#         # delete blob
#         yield self.bm.delete_blobs([blob_hash])
#         self.assertFalse(os.path.isfile(os.path.join(self.blob_dir, blob_hash)))
#         blobs = yield self.bm.get_all_verified_blobs()
#         self.assertEqual(len(blobs), 0)
#         blobs = yield self.bm.storage.get_all_blob_hashes()
#         self.assertEqual(len(blobs), 0)
#         self.assertNotIn(blob_hash, self.bm.blobs)
#
#         # delete blob that was already deleted once
#         yield self.bm.delete_blobs([blob_hash])
#
#         # delete blob that does not exist, nothing will
#         # happen
#         blob_hash = random_lbry_hash()
#         yield self.bm.delete_blobs([blob_hash])
#
#     @defer.inlineCallbacks
#     def test_delete_open_blob(self):
#         # Test that a blob that is opened for writing will not be deleted
#
#         # create blobs
#         blob_hashes = []
#         for i in range(0, 10):
#             blob_hash = yield self._create_and_add_blob()
#             blob_hashes.append(blob_hash)
#         blobs = yield self.bm.get_all_verified_blobs()
#         self.assertEqual(len(blobs), 10)
#
#         # open the last blob
#         blob = yield self.bm.get_blob(blob_hashes[-1])
#         w, finished_d = yield blob.open_for_writing(self.peer)
#
#         # schedule a close, just to leave the reactor clean
#         finished_d.addBoth(lambda x:None)
#         self.addCleanup(w.close)
#
#         # delete the last blob and check if it still exists
#         yield self.bm.delete_blobs([blob_hash])
#         blobs = yield self.bm.get_all_verified_blobs()
#         self.assertEqual(len(blobs), 10)
#         self.assertIn(blob_hashes[-1], blobs)
#         self.assertTrue(os.path.isfile(os.path.join(self.blob_dir, blob_hashes[-1])))
#
#     @defer.inlineCallbacks
#     def test_should_announce(self):
#         # create blob with should announce
#         blob_hash = yield self._create_and_add_blob(should_announce=True)
#         out = yield self.bm.get_should_announce(blob_hash)
#         self.assertTrue(out)
#         count = yield self.bm.count_should_announce_blobs()
#         self.assertEqual(1, count)
#
#         # set should announce to False
#         yield self.bm.set_should_announce(blob_hash, should_announce=False)
#         out = yield self.bm.get_should_announce(blob_hash)
#         self.assertFalse(out)
#         count = yield self.bm.count_should_announce_blobs()
#         self.assertEqual(0, count)
