import os.path
from twisted.trial import unittest
from twisted.internet import defer
from lbrynet.lbryfile.client.EncryptedFileDownloader import EncryptedFileSaver



class TestEncryptedFileSaver(unittest.TestCase):

    @defer.inlineCallbacks
    def test_setup_output(self):
        file_name = 'encrypted_file_saver_test.tmp'
        self.assertFalse(os.path.isfile(file_name))

        # create file in the temporary trial folder
        stream_hash = ''
        peer_finder = None
        rate_limiter = None
        blob_manager = None
        stream_info_manager = None
        payment_rate_manager = None
        wallet = None
        download_directory = '.'
        upload_allowed = False
        saver = EncryptedFileSaver(stream_hash, peer_finder, rate_limiter, blob_manager, stream_info_manager,
                         payment_rate_manager, wallet, download_directory, file_name)

        yield saver._setup_output()
        self.assertTrue(os.path.isfile(file_name))
        saver._close_output()


