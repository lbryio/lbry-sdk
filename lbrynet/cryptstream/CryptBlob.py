import binascii
import logging
from Crypto.Cipher import AES
from lbrynet import conf
from lbrynet.core.BlobInfo import BlobInfo


log = logging.getLogger(__name__)


class CryptBlobInfo(BlobInfo):
    def __init__(self, blob_hash, blob_num, length, iv):
        BlobInfo.__init__(self, blob_hash, blob_num, length)
        self.iv = iv


class StreamBlobDecryptor(object):
    def __init__(self, blob, key, iv, length):
        self.blob = blob
        self.key = key
        self.iv = iv
        self.length = length
        self.buff = b''
        self.len_read = 0
        self.cipher = AES.new(self.key, AES.MODE_CBC, self.iv)

    def decrypt(self, write_func):

        def remove_padding(data):
            pad_len = ord(data[-1])
            data, padding = data[:-1 * pad_len], data[-1 * pad_len:]
            for c in padding:
                assert ord(c) == pad_len
            return data

        def write_bytes():
            if self.len_read < self.length:
                num_bytes_to_decrypt = greatest_multiple(len(self.buff), self.cipher.block_size)
                data_to_decrypt, self.buff = split(self.buff, num_bytes_to_decrypt)
                write_func(self.cipher.decrypt(data_to_decrypt))

        def finish_decrypt():
            assert len(self.buff) % self.cipher.block_size == 0
            data_to_decrypt, self.buff = self.buff, b''
            write_func(remove_padding(self.cipher.decrypt(data_to_decrypt)))

        def decrypt_bytes(data):
            self.buff += data
            self.len_read += len(data)
            write_bytes()

        d = self.blob.read(decrypt_bytes)
        d.addCallback(lambda _: finish_decrypt())
        return d


class CryptStreamBlobMaker(object):
    """This class encrypts data and writes it to a new blob"""
    def __init__(self, key, iv, blob_num, blob):
        self.key = key
        self.iv = iv
        self.blob_num = blob_num
        self.blob = blob
        self.cipher = AES.new(self.key, AES.MODE_CBC, self.iv)
        self.buff = b''
        self.length = 0

    def write(self, data):
        max_bytes_to_write = conf.settings['BLOB_SIZE'] - self.length - 1
        done = False
        if max_bytes_to_write <= len(data):
            num_bytes_to_write = max_bytes_to_write
            done = True
        else:
            num_bytes_to_write = len(data)
        self.length += num_bytes_to_write
        data_to_write = data[:num_bytes_to_write]
        self.buff += data_to_write
        self._write_buffer()
        return done, num_bytes_to_write

    def close(self):
        log.debug("closing blob %s with plaintext len %s", str(self.blob_num), str(self.length))
        if self.length != 0:
            self._close_buffer()
        d = self.blob.close()
        d.addCallback(self._return_info)
        log.debug("called the finished_callback from CryptStreamBlobMaker.close")
        return d

    def _write_buffer(self):
        num_bytes_to_encrypt = (len(self.buff) // AES.block_size) * AES.block_size
        data_to_encrypt, self.buff = split(self.buff, num_bytes_to_encrypt)
        encrypted_data = self.cipher.encrypt(data_to_encrypt)
        self.blob.write(encrypted_data)

    def _close_buffer(self):
        data_to_encrypt, self.buff = self.buff, b''
        assert len(data_to_encrypt) < AES.block_size
        pad_len = AES.block_size - len(data_to_encrypt)
        padded_data = data_to_encrypt + chr(pad_len) * pad_len
        self.length += pad_len
        assert len(padded_data) == AES.block_size
        encrypted_data = self.cipher.encrypt(padded_data)
        self.blob.write(encrypted_data)

    def _return_info(self, blob_hash):
        return CryptBlobInfo(blob_hash, self.blob_num, self.length, binascii.hexlify(self.iv))


def greatest_multiple(a, b):
    """return the largest value `c`, that is a multiple of `b` and is <= `a`"""
    return (a // b) * b


def split(buff, cutoff):
    return buff[:cutoff], buff[cutoff:]
