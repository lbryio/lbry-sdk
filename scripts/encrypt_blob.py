"""Encrypt a single file using the given key and iv"""
import argparse
import logging
import sys

from twisted.internet import defer
from twisted.internet import reactor
from twisted.protocols import basic
from twisted.web.client import FileBodyProducer

from lbrynet import conf
from lbrynet.core import log_support
from lbrynet.core.HashAnnouncer import DummyHashAnnouncer
from lbrynet.core.BlobManager import DiskBlobManager
from lbrynet.cryptstream.CryptStreamCreator import CryptStreamCreator


log = logging.getLogger('decrypt_blob')


def main():
    conf.initialize_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument('filename')
    parser.add_argument('hex_key')
    parser.add_argument('hex_iv')
    args = parser.parse_args()
    log_support.configure_console(level='DEBUG')

    run(args)
    reactor.run()


@defer.inlineCallbacks
def run(args):
    try:
        yield encrypt_blob(args.filename, args.hex_key, args.hex_iv)
    except Exception:
        log.exception('Failed to encrypt blob')
    finally:
        reactor.callLater(0, reactor.stop)


@defer.inlineCallbacks
def encrypt_blob(filename, key, iv):
    dummy_announcer = DummyHashAnnouncer()
    manager = DiskBlobManager(dummy_announcer, '.', '.')
    yield manager.setup()
    creator = CryptStreamCreator(manager, filename, key, iv_generator(iv))
    with open(filename, 'r') as infile:
        producer = FileBodyProducer(infile, readSize=2**22)
        yield producer.startProducing(creator)
    yield creator.stop()


def iv_generator(iv):
    iv = int(iv, 16)
    while 1:
        iv += 1
        yield ("%016d" % iv)[-16:]


if __name__ == '__main__':
    sys.exit(main())
