import binascii
from twisted.internet import defer
from lbrynet.cryptstream.CryptBlob import StreamBlobDecryptor


class CryptBlobHandler(object):
    #implements(IBlobHandler)

    def __init__(self, key, write_func):
        self.key = key
        self.write_func = write_func

    ######## IBlobHandler #########

    def handle_blob(self, blob, blob_info):
        try:
            blob_decryptor = StreamBlobDecryptor(blob, self.key, binascii.unhexlify(blob_info.iv),
                                                 blob_info.length)
        except ValueError as err:
            return defer.fail(err)
        d = blob_decryptor.decrypt(self.write_func)
        return d
