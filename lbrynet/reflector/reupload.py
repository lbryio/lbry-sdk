import logging
from twisted.internet import reactor
from twisted.internet.error import ConnectionLost, ConnectionDone
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
    d.addCallback(lambda reflected_blobs: log.info("Reflected %i blobs for lbry://%s",
                                                   len(reflected_blobs),
                                                   lbry_file.uri))
    return d


def _catch_error(err, uri):
    msg = "An error occurred while checking availability for lbry://%s: %s"
    log.error(msg, uri, err.getTraceback())


def check_and_restore_availability(lbry_file, reflector_server):
    d = _reflect_stream(lbry_file, reflector_server)
    d.addErrback(lambda err: err.trap(ConnectionDone, ConnectionLost))
    d.addErrback(_catch_error, lbry_file.uri)
    return d
