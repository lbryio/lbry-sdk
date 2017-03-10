# -*- coding: utf-8 -*-
import shutil
import tempfile

from Crypto.Cipher import AES
import mock
from twisted.trial import unittest

from lbrynet.core import BlobManager
from lbrynet.core import Session
from lbrynet.lbryfile.EncryptedFileMetadataManager import EncryptedFileMetadataManager
from lbrynet.core import StreamDescriptor
from lbrynet.core import Storage
from lbrynet.core.server import DHTHashAnnouncer
from lbrynet.lbryfilemanager import EncryptedFileCreator
from lbrynet.lbryfilemanager import EncryptedFileManager

from tests import mocks


MB = 2**20


def iv_generator():
    while True:
        yield '3' * AES.block_size


class CreateEncryptedFileTest(unittest.TestCase):
    timeout = 5

    def setUp(self):
        mocks.mock_conf_settings(self)
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def create_file(self, filename):
        storage = Storage.FileStorage(self.tmp_dir)
        session = mock.Mock(spec=Session.Session)(None, None)
        session.storage = storage
        hash_announcer = DHTHashAnnouncer.DHTHashAnnouncer(None, None)
        session.db_dir = self.tmp_dir
        session.blob_manager = BlobManager.BlobManager(hash_announcer, self.tmp_dir, session.storage)
        stream_info_manager = EncryptedFileMetadataManager(session.storage)
        sd_identifier = StreamDescriptor.StreamDescriptorIdentifier()
        manager = EncryptedFileManager.EncryptedFileManager(session, stream_info_manager, sd_identifier)
        handle = mocks.GenFile(3*MB, '1')
        key = '2'*AES.block_size
        return EncryptedFileCreator.create_lbry_file(
            session, manager, filename, handle, key, iv_generator())

    def test_can_create_file(self):
        expected_stream_hash = ('41e6b247d923d191b154fb6f1b8529d6ddd6a73d65c357b1acb7'
                                '42dd83151fb66393a7709e9f346260a4f4db6de10c25')
        filename = 'test.file'
        d = self.create_file(filename)
        d.addCallback(self.assertEqual, expected_stream_hash)
        return d

    def test_can_create_file_with_unicode_filename(self):
        expected_stream_hash = ('d1da4258f3ce12edb91d7e8e160d091d3ab1432c2e55a6352dce0'
                                '2fd5adb86fe144e93e110075b5865fff8617776c6c0')
        filename = u'☃.file'
        d = self.create_file(filename)
        d.addCallback(self.assertEqual, expected_stream_hash)
        return d
