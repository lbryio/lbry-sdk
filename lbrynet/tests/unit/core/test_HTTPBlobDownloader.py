from mock import MagicMock

from twisted.trial import unittest
from twisted.internet import defer

from lbrynet.blob import BlobFile
from lbrynet.core.HTTPBlobDownloader import HTTPBlobDownloader
from lbrynet.tests.util import mk_db_and_blob_dir, rm_db_and_blob_dir


class HTTPBlobDownloaderTest(unittest.TestCase):
    def setUp(self):
        self.db_dir, self.blob_dir = mk_db_and_blob_dir()
        self.blob_manager = MagicMock()
        self.client = MagicMock()
        self.blob_hash = ('d17272b17a1ad61c4316ac13a651c2b0952063214a81333e'
                          '838364b01b2f07edbd165bb7ec60d2fb2f337a2c02923852')
        self.blob = BlobFile(self.blob_dir, self.blob_hash)
        self.blob_manager.get_blob.side_effect = lambda _: defer.succeed(self.blob)
        self.response = MagicMock(code=200, length=400)
        self.client.get.side_effect = lambda uri: defer.succeed(self.response)
        self.downloader = HTTPBlobDownloader(self.blob_manager, [self.blob_hash], ['server1'], self.client)
        self.downloader.interval = 0

    def tearDown(self):
        rm_db_and_blob_dir(self.db_dir, self.blob_dir)

    @defer.inlineCallbacks
    def test_download_successful(self):
        self.client.collect.side_effect = collect
        yield self.downloader.start()
        self.blob_manager.get_blob.assert_called_with(self.blob_hash)
        self.client.get.assert_called_with('http://{}/{}'.format('server1', self.blob_hash))
        self.client.collect.assert_called()
        self.assertEqual(self.blob.get_length(), self.response.length)
        self.assertEqual(self.blob.get_is_verified(), True)
        self.assertEqual(self.blob.writers, {})

    @defer.inlineCallbacks
    def test_download_transfer_failed(self):
        self.client.collect.side_effect = lambda response, write: defer.fail(Exception())
        yield self.downloader.start()
        self.assertEqual(len(self.client.collect.mock_calls), self.downloader.max_failures)
        self.blob_manager.get_blob.assert_called_with(self.blob_hash)
        self.assertEqual(self.blob.get_length(), self.response.length)
        self.assertEqual(self.blob.get_is_verified(), False)
        self.assertEqual(self.blob.writers, {})

    @defer.inlineCallbacks
    def test_blob_not_found(self):
        self.response.code = 404
        yield self.downloader.start()
        self.blob_manager.get_blob.assert_called_with(self.blob_hash)
        self.client.get.assert_called_with('http://{}/{}'.format('server1', self.blob_hash))
        self.client.collect.assert_not_called()
        self.assertEqual(self.blob.get_is_verified(), False)
        self.assertEqual(self.blob.writers, {})


def collect(response, write):
    write('f' * response.length)
    defer.succeed(None)
