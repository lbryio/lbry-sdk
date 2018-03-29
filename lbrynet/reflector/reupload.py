import random

from twisted.internet import reactor, defer
from lbrynet import conf
from lbrynet.reflector import ClientFactory, BlobClientFactory


def _is_ip(host):
    try:
        if len(host.split(".")) == 4 and all([0 <= int(x) <= 255 for x in host.split(".")]):
            return True
        return False
    except ValueError:
        return False


@defer.inlineCallbacks
def resolve(host):
    if _is_ip(host):
        ip = host
    else:
        ip = yield reactor.resolve(host)
    defer.returnValue(ip)


@defer.inlineCallbacks
def _reflect_stream(blob_manager, stream_hash, sd_hash, reflector_server):
    reflector_address, reflector_port = reflector_server[0], reflector_server[1]
    factory = ClientFactory(blob_manager, stream_hash, sd_hash)
    ip = yield resolve(reflector_address)
    yield reactor.connectTCP(ip, reflector_port, factory)
    result = yield factory.finished_deferred
    defer.returnValue(result)


def _reflect_file(lbry_file, reflector_server):
    return _reflect_stream(lbry_file.blob_manager, lbry_file.stream_hash, lbry_file.sd_hash, reflector_server)


@defer.inlineCallbacks
def _reflect_blobs(blob_manager, blob_hashes, reflector_server):
    reflector_address, reflector_port = reflector_server[0], reflector_server[1]
    factory = BlobClientFactory(blob_manager, blob_hashes)
    ip = yield resolve(reflector_address)
    yield reactor.connectTCP(ip, reflector_port, factory)
    result = yield factory.finished_deferred
    defer.returnValue(result)


def reflect_file(lbry_file, reflector_server=None):
    if reflector_server:
        if len(reflector_server.split(":")) == 2:
            host, port = tuple(reflector_server.split(":"))
            reflector_server = host, int(port)
        else:
            reflector_server = reflector_server, 5566
    else:
        reflector_server = random.choice(conf.settings['reflector_servers'])
    return _reflect_file(lbry_file, reflector_server)


@defer.inlineCallbacks
def reflect_stream(blob_manager, stream_hash, reflector_server=None):
    if reflector_server:
        if len(reflector_server.split(":")) == 2:
            host, port = tuple(reflector_server.split(":"))
            reflector_server = host, int(port)
        else:
            reflector_server = reflector_server, 5566
    else:
        reflector_server = random.choice(conf.settings['reflector_servers'])
    sd_hash = yield blob_manager.storage.get_sd_blob_hash_for_stream(stream_hash)
    result = yield _reflect_stream(blob_manager, stream_hash, sd_hash, reflector_server)
    defer.returnValue(result)


def reflect_blob_hashes(blob_hashes, blob_manager, reflector_server=None):
    if reflector_server:
        if len(reflector_server.split(":")) == 2:
            host, port = tuple(reflector_server.split(":"))
            reflector_server = host, int(port)
        else:
            reflector_server = reflector_server, 5566
    else:
        reflector_server = random.choice(conf.settings['reflector_servers'])
    return _reflect_blobs(blob_manager, blob_hashes, reflector_server)
