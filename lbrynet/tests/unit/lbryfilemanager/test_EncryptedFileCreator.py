# -*- coding: utf-8 -*-
from Crypto.Cipher import AES
import mock
from twisted.trial import unittest
from twisted.internet import defer

from lbrynet.core import BlobManager
from lbrynet.core import Session
from lbrynet.core.server import DHTHashAnnouncer
from lbrynet.file_manager import EncryptedFileCreator
from lbrynet.file_manager import EncryptedFileManager
from lbrynet.tests import mocks
from lbrynet.tests.util import mk_db_and_blob_dir, rm_db_and_blob_dir

MB = 2**20

def iv_generator():
    while True:
        yield '3' * AES.block_size


class CreateEncryptedFileTest(unittest.TestCase):
    timeout = 5
    def setUp(self):
        mocks.mock_conf_settings(self)
        self.tmp_db_dir, self.tmp_blob_dir = mk_db_and_blob_dir()

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.blob_manager.stop()
        rm_db_and_blob_dir(self.tmp_db_dir, self.tmp_blob_dir)

    @defer.inlineCallbacks
    def create_file(self, filename):
        session = mock.Mock(spec=Session.Session)(None, None)
        hash_announcer = DHTHashAnnouncer.DHTHashAnnouncer(None, None)
        self.blob_manager = BlobManager.DiskBlobManager(
            hash_announcer, self.tmp_blob_dir, self.tmp_db_dir)
        session.blob_manager = self.blob_manager
        yield session.blob_manager.setup()
        session.db_dir = self.tmp_db_dir
        manager = mock.Mock(spec=EncryptedFileManager.EncryptedFileManager)()
        handle = mocks.GenFile(3*MB, '1')
        key = '2'*AES.block_size
        out = yield EncryptedFileCreator.create_lbry_file(
            session, manager, filename, handle, key, iv_generator())
        defer.returnValue(out)

    @defer.inlineCallbacks
    def test_can_create_file(self):
        expected_stream_hash = ('41e6b247d923d191b154fb6f1b8529d6ddd6a73d65c357b1acb7'
                                '42dd83151fb66393a7709e9f346260a4f4db6de10c25')
        filename = 'test.file'
        stream_hash = yield self.create_file(filename)
        self.assertEqual(expected_stream_hash, stream_hash)

        blobs = yield self.blob_manager.get_all_verified_blobs()
        self.assertEqual(2, len(blobs))
        num_should_announce_blobs = yield self.blob_manager.count_should_announce_blobs()
        self.assertEqual(1, num_should_announce_blobs)

    @defer.inlineCallbacks
    def test_can_create_file_with_unicode_filename(self):
        expected_stream_hash = ('d1da4258f3ce12edb91d7e8e160d091d3ab1432c2e55a6352dce0'
                                '2fd5adb86fe144e93e110075b5865fff8617776c6c0')
        filename = u'☃.file'
        stream_hash = yield self.create_file(filename)
        self.assertEqual(expected_stream_hash, stream_hash)
