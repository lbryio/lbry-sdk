import json
import os
import shutil
import tempfile

from twisted.trial import unittest
import mock

from lbrynet.lbrynet_daemon import UIManager


class BundledUIManagerTest(unittest.TestCase):
    def setUp(self):
        self.active_dir = tempfile.mkdtemp()
        self.bundled_dir = tempfile.mkdtemp()
        self.manager = UIManager.BundledUIManager(mock.Mock(), self.active_dir, self.bundled_dir)

    def tearDown(self):
        shutil.rmtree(self.active_dir)
        shutil.rmtree(self.bundled_dir)

    def test_when_bundle_is_not_available(self):
        result = self.manager.setup()
        self.assertFalse(result)
        expected = []
        self.assertEqual(os.listdir(self.active_dir), expected)

    def test_when_already_bundled(self):
        make_data_file(self.active_dir)
        make_data_file(self.bundled_dir)
        result = self.manager.setup()
        self.assertTrue(result)
        expected = ['data.json']
        self.assertEqual(os.listdir(self.active_dir), expected)

    def test_bundled_files_are_copied(self):
        make_data_file(self.active_dir)
        make_data_file(self.bundled_dir, 'BARFOO')
        touch(os.path.join(self.bundled_dir, 'test.html'))
        result = self.manager.setup()
        self.assertTrue(result)
        self.assertEqual('BARFOO', self.manager.version())
        expected = ['data.json', 'test.html']
        self.assertItemsEqual(os.listdir(self.active_dir), expected)


def make_data_file(directory, sha='FOOBAR'):
    with open(os.path.join(directory, 'data.json'), 'w') as f:
        json.dump({'sha': sha}, f)


def touch(filename):
    with open(filename, 'a') as f:
        pass
