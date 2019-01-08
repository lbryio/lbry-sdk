from unittest.mock import MagicMock

from twisted.trial import unittest
from twisted.internet import defer

from lbrynet.blob.blob_file import BlobFile
from lbrynet.extras.http_blob_downloader import HTTPBlobDownloader
from tests.test_utils import mk_db_and_blob_dir, rm_db_and_blob_dir


class HTTPBlobDownloaderTest(unittest.TestCase):
    def setUp(self):
        self.db_dir, self.blob_dir = mk_db_and_blob_dir()
        self.blob_manager = MagicMock()
        self.client = MagicMock()
        self.blob_hash = ('d17272b17a1ad61c4316ac13a651c2b0952063214a81333e'
                          '838364b01b2f07edbd165bb7ec60d2fb2f337a2c02923852')
        self.blob = BlobFile(self.blob_dir, self.blob_hash)
        self.blob_manager.get_blob.side_effect = lambda _: self.blob
        self.response = MagicMock(code=200, length=400)
        self.client.get.side_effect = lambda uri: defer.succeed(self.response)
        self.downloader = HTTPBlobDownloader(self.blob_manager, [self.blob_hash], ['server1'], self.client, retry=False)
        self.downloader.interval = 0

    def tearDown(self):
        self.downloader.stop()
        rm_db_and_blob_dir(self.db_dir, self.blob_dir)

    @defer.inlineCallbacks
    def test_download_successful(self):
        self.client.collect.side_effect = collect
        yield self.downloader.start()
        self.blob_manager.get_blob.assert_called_with(self.blob_hash)
        self.client.get.assert_called_with('http://{}/{}'.format('server1', self.blob_hash))
        self.client.collect.assert_called()
        self.assertEqual(self.blob.get_length(), self.response.length)
        self.assertTrue(self.blob.get_is_verified())
        self.assertEqual(self.blob.writers, {})

    @defer.inlineCallbacks
    def test_download_invalid_content(self):
        self.client.collect.side_effect = bad_collect
        yield self.downloader.start()
        self.assertEqual(self.blob.get_length(), self.response.length)
        self.assertFalse(self.blob.get_is_verified())
        self.assertEqual(self.blob.writers, {})

    @defer.inlineCallbacks
    def test_peer_finished_first_causing_a_write_on_closed_handle(self):
        self.client.collect.side_effect = lambda response, write: defer.fail(IOError('I/O operation on closed file'))
        yield self.downloader.start()
        self.blob_manager.get_blob.assert_called_with(self.blob_hash)
        self.client.get.assert_called_with('http://{}/{}'.format('server1', self.blob_hash))
        self.client.collect.assert_called()
        self.assertEqual(self.blob.get_length(), self.response.length)
        self.assertEqual(self.blob.writers, {})

    @defer.inlineCallbacks
    def test_download_transfer_failed(self):
        self.client.collect.side_effect = lambda response, write: defer.fail(Exception())
        yield self.downloader.start()
        self.assertEqual(len(self.client.collect.mock_calls), self.downloader.max_failures)
        self.blob_manager.get_blob.assert_called_with(self.blob_hash)
        self.assertEqual(self.blob.get_length(), self.response.length)
        self.assertFalse(self.blob.get_is_verified())
        self.assertEqual(self.blob.writers, {})

    @defer.inlineCallbacks
    def test_blob_not_found(self):
        self.response.code = 404
        yield self.downloader.start()
        self.blob_manager.get_blob.assert_called_with(self.blob_hash)
        self.client.get.assert_called_with('http://{}/{}'.format('server1', self.blob_hash))
        self.client.collect.assert_not_called()
        self.assertFalse(self.blob.get_is_verified())
        self.assertEqual(self.blob.writers, {})

    def test_stop(self):
        self.client.collect.side_effect = lambda response, write: defer.Deferred()
        self.downloader.start()  # hangs if yielded, as intended, to simulate a long ongoing write while we call stop
        self.downloader.stop()
        self.blob_manager.get_blob.assert_called_with(self.blob_hash)
        self.client.get.assert_called_with('http://{}/{}'.format('server1', self.blob_hash))
        self.client.collect.assert_called()
        self.assertEqual(self.blob.get_length(), self.response.length)
        self.assertFalse(self.blob.get_is_verified())
        self.assertEqual(self.blob.writers, {})


def collect(response, write):
    write(b'f' * response.length)


def bad_collect(response, write):
    write('0' * response.length)
