"""Decrypt a single blob"""
import argparse
import binascii
import logging
import os
import sys

from twisted.internet import defer
from twisted.internet import reactor

from lbrynet import conf
from lbrynet.cryptstream import CryptBlob
from lbrynet.blob import BlobFile
from lbrynet.core import log_support


log = logging.getLogger('decrypt_blob')


def main():
    conf.initialize_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument('blob_file')
    parser.add_argument('hex_key')
    parser.add_argument('hex_iv')
    parser.add_argument('output')
    args = parser.parse_args()
    log_support.configure_console()

    d = run(args)
    reactor.run()


@defer.inlineCallbacks
def run(args):
    try:
        yield decrypt_blob(args.blob_file, args.hex_key, args.hex_iv, args.output)
    except Exception:
        log.exception('Failed to decrypt blob')
    finally:
        reactor.callLater(0, reactor.stop)


@defer.inlineCallbacks
def decrypt_blob(blob_file, key, iv, output):
    filename = os.path.abspath(blob_file)
    length = os.path.getsize(filename)
    directory, blob_hash = os.path.split(filename)
    blob = BlobFile(directory, blob_hash, length)
    decryptor = CryptBlob.StreamBlobDecryptor(
        blob, binascii.unhexlify(key), binascii.unhexlify(iv), length)
    with open(output, 'w') as f:
        yield decryptor.decrypt(f.write)


if __name__ == '__main__':
    sys.exit(main())
