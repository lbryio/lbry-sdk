import binascii
import logging
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from cryptography.hazmat.primitives.ciphers.algorithms import AES
from cryptography.hazmat.primitives.padding import PKCS7
from cryptography.hazmat.backends import default_backend
from lbrynet import conf
from lbrynet.core.BlobInfo import BlobInfo


log = logging.getLogger(__name__)
backend = default_backend()


class CryptBlobInfo(BlobInfo):
    def __init__(self, blob_hash, blob_num, length, iv):
        BlobInfo.__init__(self, blob_hash, blob_num, length)
        self.iv = iv


class StreamBlobDecryptor(object):
    def __init__(self, blob, key, iv, length):
        """
        This class decrypts blob

        blob - object which implements read() function.
        key = encryption_key
        iv = initialization vector
        blob_num = blob number (has no effect on encryption)
        length = length in bytes of blob
        """
        self.blob = blob
        self.key = key
        self.iv = iv
        self.length = length
        self.buff = b''
        self.len_read = 0
        cipher = Cipher(AES(self.key), modes.CBC(self.iv), backend=backend)
        self.unpadder = PKCS7(AES.block_size).unpadder()
        self.cipher = cipher.decryptor()

    def decrypt(self, write_func):
        """
        Decrypt blob and write its content useing write_func

        write_func - function that takes decrypted string as
            arugment and writes it somewhere
        """

        def remove_padding(data):
            return self.unpadder.update(data) + self.unpadder.finalize()

        def write_bytes():
            if self.len_read < self.length:
                num_bytes_to_decrypt = greatest_multiple(len(self.buff), (AES.block_size / 8))
                data_to_decrypt, self.buff = split(self.buff, num_bytes_to_decrypt)
                write_func(self.cipher.update(data_to_decrypt))

        def finish_decrypt():
            assert len(self.buff) % (AES.block_size / 8) == 0
            data_to_decrypt, self.buff = self.buff, b''
            last_chunk = self.cipher.update(data_to_decrypt) + self.cipher.finalize()
            write_func(remove_padding(last_chunk))

        def decrypt_bytes(data):
            self.buff += data
            self.len_read += len(data)
            write_bytes()

        d = self.blob.read(decrypt_bytes)
        d.addCallback(lambda _: finish_decrypt())
        return d


class CryptStreamBlobMaker(object):
    def __init__(self, key, iv, blob_num, blob):
        """
        This class encrypts data and writes it to a new blob

        key = encryption_key
        iv = initialization vector
        blob_num = blob number (has no effect on encryption)
        blob = object which implements write(), close() function , close() function must
            be a deferred. (Will generally be of HashBlobCreator type)
        """
        self.key = key
        self.iv = iv
        self.blob_num = blob_num
        self.blob = blob
        cipher = Cipher(AES(self.key), modes.CBC(self.iv), backend=backend)
        self.padder = PKCS7(AES.block_size).padder()
        self.cipher = cipher.encryptor()
        self.length = 0

    def write(self, data):
        """
        encrypt and write string data

        Returns:
        tuple (done, num_bytes_to_write) where done is True if
        max bytes are written. num_bytes_to_write is the number
        of bytes that will be written from data in this call
        """
        max_bytes_to_write = conf.settings['BLOB_SIZE'] - self.length - 1
        done = False
        if max_bytes_to_write <= len(data):
            num_bytes_to_write = max_bytes_to_write
            done = True
        else:
            num_bytes_to_write = len(data)
        data_to_write = data[:num_bytes_to_write]
        self.length += len(data_to_write)
        padded_data = self.padder.update(data_to_write)
        encrypted_data = self.cipher.update(padded_data)
        self.blob.write(encrypted_data)
        return done, num_bytes_to_write

    def close(self):
        log.debug("closing blob %s with plaintext len %s", str(self.blob_num), str(self.length))
        if self.length != 0:
            self._close_buffer()
        d = self.blob.close()
        d.addCallback(self._return_info)
        log.debug("called the finished_callback from CryptStreamBlobMaker.close")
        return d

    def _close_buffer(self):
        self.length += (AES.block_size / 8) - (self.length % (AES.block_size / 8))
        padded_data = self.padder.finalize()
        encrypted_data = self.cipher.update(padded_data) + self.cipher.finalize()
        self.blob.write(encrypted_data)

    def _return_info(self, blob_hash):
        return CryptBlobInfo(blob_hash, self.blob_num, self.length, binascii.hexlify(self.iv))


def greatest_multiple(a, b):
    """return the largest value `c`, that is a multiple of `b` and is <= `a`"""
    return (a // b) * b


def split(buff, cutoff):
    return buff[:cutoff], buff[cutoff:]
