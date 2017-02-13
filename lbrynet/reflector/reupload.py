import random

from twisted.internet import reactor, defer
from lbrynet import conf
from lbrynet.reflector import ClientFactory, BlobClientFactory


@defer.inlineCallbacks
def _reflect_stream(lbry_file, reflector_server):
    reflector_address, reflector_port = reflector_server[0], reflector_server[1]
    factory = ClientFactory(lbry_file)
    ip = yield reactor.resolve(reflector_address)
    yield reactor.connectTCP(ip, reflector_port, factory)
    yield factory.finished_deferred


@defer.inlineCallbacks
def _reflect_blobs(blob_manager, blob_hashes, reflector_server):
    reflector_address, reflector_port = reflector_server[0], reflector_server[1]
    factory = BlobClientFactory(blob_manager, blob_hashes)
    ip = yield reactor.resolve(reflector_address)
    yield reactor.connectTCP(ip, reflector_port, factory)
    yield factory.finished_deferred


def reflect_stream(lbry_file):
    reflector_server = random.choice(conf.settings['reflector_servers'])
    return _reflect_stream(lbry_file, reflector_server)


def reflect_blob_hashes(blob_hashes, blob_manager):
    reflector_server = random.choice(conf.settings['reflector_servers'])
    return _reflect_blobs(blob_manager, blob_hashes, reflector_server)
