"""Encrypt a single file using the given key and iv"""
import argparse
import binascii
import logging
import StringIO
import sys

from twisted.internet import defer
from twisted.internet import reactor

from lbrynet import conf
from lbrynet.cryptstream import CryptBlob
from lbrynet.core import log_support
from lbrynet.core import cryptoutils


log = logging.getLogger('decrypt_blob')


def main():
    conf.initialize_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument('filename')
    parser.add_argument('hex_key')
    parser.add_argument('hex_iv')
    args = parser.parse_args()
    log_support.configure_console(level='DEBUG')

    d = run(args)
    reactor.run()


@defer.inlineCallbacks
def run(args):
    try:
        yield encrypt_blob(args.filename, args.hex_key, args.hex_iv)
    except Exception:
        log.exception('Failed to encrypt blob')
    finally:
        reactor.callLater(0, reactor.stop)


def encrypt_blob(filename, key, iv):
    blob = Blob()
    blob_maker = CryptBlob.CryptStreamBlobMaker(
        binascii.unhexlify(key), binascii.unhexlify(iv), 0, blob)
    with open(filename) as fin:
        blob_maker.write(fin.read())
    blob_maker.close()


class Blob(object):
    def __init__(self):
        self.data = StringIO.StringIO()

    def write(self, data):
        self.data.write(data)

    def close(self):
        hashsum = cryptoutils.get_lbry_hash_obj()
        buffer = self.data.getvalue()
        hashsum.update(buffer)
        with open(hashsum.hexdigest(), 'w') as fout:
            fout.write(buffer)
        return defer.succeed(True)


if __name__ == '__main__':
    sys.exit(main())
