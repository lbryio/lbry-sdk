from twisted.trial import unittest
from twisted.internet import defer
from lbrynet.cryptstream import CryptBlob
from lbrynet import conf

from tests.mocks import mock_conf_settings

from Crypto import Random
from Crypto.Cipher import AES
import tempfile
import random
import string
import StringIO
import time

class MocBlob(object):
    def __init__(self):
        self.data = ''

    def read(self, write_func):
        data = self.data
        write_func(data)
        return defer.succeed(True)

    def write(self, data):
        self.data += data

    def close(self):
        return defer.succeed(True)


def random_string(length):
   return ''.join(random.choice(string.lowercase) for i in range(length))


class TestCryptBlob(unittest.TestCase):
    def setUp(self):
        mock_conf_settings(self)


    @defer.inlineCallbacks
    def _test_encrypt_decrypt(self, size_of_data):
        # max blob size is 2*2**20 -1 ( -1 due to required padding in the end )
        blob = MocBlob()
        blob_num = 0
        key = Random.new().read(AES.block_size)
        iv = Random.new().read(AES.block_size)
        maker = CryptBlob.CryptStreamBlobMaker(key, iv, blob_num, blob)
        write_size = size_of_data
        string_to_encrypt = random_string(size_of_data)

        # encrypt string
        done,num_bytes = maker.write(string_to_encrypt)
        yield maker.close()
        self.assertEqual(size_of_data,num_bytes)
        expected_encrypted_blob_size = ((size_of_data / AES.block_size) + 1) * AES.block_size
        self.assertEqual(expected_encrypted_blob_size, len(blob.data))

        if size_of_data < conf.settings['BLOB_SIZE']-1:
            self.assertFalse(done)
        else:
            self.assertTrue(done)
        self.data_buf = ''

        def write_func(data):
            self.data_buf += data

        # decrypt string
        decryptor = CryptBlob.StreamBlobDecryptor(blob, key, iv, size_of_data)
        decryptor.decrypt(write_func)
        self.assertEqual(self.data_buf,string_to_encrypt)

    @defer.inlineCallbacks
    def test_encrypt_decrypt(self):
        yield self._test_encrypt_decrypt(1)
        yield self._test_encrypt_decrypt(16*2)
        yield self._test_encrypt_decrypt(2000)
        yield self._test_encrypt_decrypt(2*2**20-1)
