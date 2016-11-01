import logging
from twisted.internet import reactor, defer
from lbrynet.reflector import BlobClientFactory, ClientFactory

log = logging.getLogger(__name__)


def _check_if_reflector_has_stream(lbry_file, reflector_server):
    reflector_address, reflector_port = reflector_server[0], reflector_server[1]
    factory = BlobClientFactory(
        lbry_file.blob_manager,
        [lbry_file.sd_hash]
    )
    d = reactor.resolve(reflector_address)
    d.addCallback(lambda ip: reactor.connectTCP(ip, reflector_port, factory))
    d.addCallback(lambda _: factory.finished_deferred)
    d.addCallback(lambda _: not factory.sent_blobs)
    return d


def _reflect_stream(lbry_file, reflector_server):
    reflector_address, reflector_port = reflector_server[0], reflector_server[1]
    factory = ClientFactory(
        lbry_file.blob_manager,
        lbry_file.stream_info_manager,
        lbry_file.stream_hash
    )
    d = reactor.resolve(reflector_address)
    d.addCallback(lambda ip: reactor.connectTCP(ip, reflector_port, factory))
    d.addCallback(lambda _: factory.finished_deferred)
    return d


def _reflect_if_unavailable(reflector_has_stream, lbry_file, reflector_server):
    if reflector_has_stream:
        log.info("lbry://%s is available", lbry_file.uri)
        return defer.succeed(False)
    log.info("lbry://%s is unavailable, reflecting it", lbry_file.uri)
    return _reflect_stream(lbry_file, reflector_server)


def _catch_error(err, uri):
    log.error("An error occurred while checking availability for lbry://%s : %s", uri, err.message)


def check_and_restore_availability(lbry_file, reflector_server):
    d = _check_if_reflector_has_stream(lbry_file, reflector_server)
    d.addCallbacks(lambda send_stream: _reflect_if_unavailable(send_stream, lbry_file, reflector_server),
                   lambda err: _catch_error(err, lbry_file.uri))
    return d
