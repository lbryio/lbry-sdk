from twisted.trial import unittest
from twisted.internet import defer
from lbrynet.blob import CryptBlob
from lbrynet.blob.blob_file import MAX_BLOB_SIZE

from tests.mocks import mock_conf_settings

from cryptography.hazmat.primitives.ciphers.algorithms import AES
import random
import string
from six import BytesIO
import os

AES_BLOCK_SIZE_BYTES = int(AES.block_size / 8)

class MocBlob:
    def __init__(self):
        self.data = b''

    def read(self, write_func):
        data = self.data
        write_func(data)
        return defer.succeed(True)

    def open_for_reading(self):
        return BytesIO(self.data)

    def write(self, data):
        if not isinstance(data, bytes):
            data = data.encode()
        self.data += data

    def close(self):
        return defer.succeed(True)


def random_string(length):
    return ''.join(random.choice(string.ascii_lowercase) for i in range(length))


class TestCryptBlob(unittest.TestCase):
    def setUp(self):
        mock_conf_settings(self)


    @defer.inlineCallbacks
    def _test_encrypt_decrypt(self, size_of_data):
        # max blob size is 2*2**20 -1 ( -1 due to required padding in the end )
        blob = MocBlob()
        blob_num = 0
        key = os.urandom(AES_BLOCK_SIZE_BYTES)
        iv = os.urandom(AES_BLOCK_SIZE_BYTES)
        maker = CryptBlob.CryptStreamBlobMaker(key, iv, blob_num, blob)
        write_size = size_of_data
        string_to_encrypt = random_string(size_of_data).encode()

        # encrypt string
        done, num_bytes = maker.write(string_to_encrypt)
        yield maker.close()
        self.assertEqual(size_of_data, num_bytes)
        expected_encrypted_blob_size = int((size_of_data / AES_BLOCK_SIZE_BYTES) + 1) * AES_BLOCK_SIZE_BYTES
        self.assertEqual(expected_encrypted_blob_size, len(blob.data))

        if size_of_data < MAX_BLOB_SIZE-1:
            self.assertFalse(done)
        else:
            self.assertTrue(done)
        self.data_buf = b''

        def write_func(data):
            self.data_buf += data

        # decrypt string
        decryptor = CryptBlob.StreamBlobDecryptor(blob, key, iv, size_of_data)
        yield decryptor.decrypt(write_func)
        self.assertEqual(self.data_buf, string_to_encrypt)

    @defer.inlineCallbacks
    def test_encrypt_decrypt(self):
        yield self._test_encrypt_decrypt(1)
        yield self._test_encrypt_decrypt(16*2)
        yield self._test_encrypt_decrypt(2000)
        yield self._test_encrypt_decrypt(2*2**20-1)
