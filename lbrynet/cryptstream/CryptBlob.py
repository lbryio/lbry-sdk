import binascii
import logging
from twisted.internet import defer, threads
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

        Returns:

        deferred that returns after decrypting blob and writing content
        """

        def remove_padding(data):
            return self.unpadder.update(data) + self.unpadder.finalize()

        def write_bytes():
            if self.len_read < self.length:
                num_bytes_to_decrypt = greatest_multiple(len(self.buff), (AES.block_size / 8))
                data_to_decrypt, self.buff = split(self.buff, num_bytes_to_decrypt)
                write_func(self.cipher.update(data_to_decrypt))

        def finish_decrypt():
            bytes_left = len(self.buff) % (AES.block_size / 8)
            if bytes_left != 0:
                log.warning(self.buff[-1 * (AES.block_size / 8):].encode('hex'))
                raise Exception("blob %s has incorrect padding: %i bytes left" %
                                (self.blob.blob_hash, bytes_left))
            data_to_decrypt, self.buff = self.buff, b''
            last_chunk = self.cipher.update(data_to_decrypt) + self.cipher.finalize()
            write_func(remove_padding(last_chunk))


        read_handle = self.blob.open_for_reading()

        def decrypt_bytes():
            data = read_handle.read()
            self.buff += data
            self.len_read += len(data)
            write_bytes()
            finish_decrypt()

        d = threads.deferToThread(decrypt_bytes)
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

    @defer.inlineCallbacks
    def close(self):
        log.debug("closing blob %s with plaintext len %s", str(self.blob_num), str(self.length))
        if self.length != 0:
            self.length += (AES.block_size / 8) - (self.length % (AES.block_size / 8))
            padded_data = self.padder.finalize()
            encrypted_data = self.cipher.update(padded_data) + self.cipher.finalize()
            self.blob.write(encrypted_data)

        blob_hash = yield self.blob.close()
        log.debug("called the finished_callback from CryptStreamBlobMaker.close")
        blob = CryptBlobInfo(blob_hash, self.blob_num, self.length, binascii.hexlify(self.iv))
        defer.returnValue(blob)


def greatest_multiple(a, b):
    """return the largest value `c`, that is a multiple of `b` and is <= `a`"""
    return (a // b) * b


def split(buff, cutoff):
    return buff[:cutoff], buff[cutoff:]
