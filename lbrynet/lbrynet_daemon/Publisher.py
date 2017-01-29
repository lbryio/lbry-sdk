import logging
import mimetypes
import os
import random

from twisted.internet import defer, reactor

from lbrynet.lbryfilemanager.EncryptedFileCreator import create_lbry_file
from lbrynet.lbryfile.StreamDescriptor import publish_sd_blob
from lbrynet.metadata.Metadata import Metadata
from lbrynet.lbryfilemanager.EncryptedFileDownloader import ManagedEncryptedFileDownloader
from lbrynet import reflector
from lbrynet import conf


log = logging.getLogger(__name__)


class Publisher(object):
    def __init__(self, session, lbry_file_manager, wallet, reflector_servers=None):
        self.session = session
        self.lbry_file_manager = lbry_file_manager
        self.wallet = wallet
        self.received_file_name = False
        self.file_path = None
        self.file_name = None
        self.publish_name = None
        self.bid_amount = None
        self.verified = False
        self.lbry_file = None
        self.txid = None
        self.nout = None
        self.claim_id = None
        self.fee = None
        self.stream_hash = None
        self.reflector_servers = reflector_servers or conf.settings['reflector_servers']
        self.metadata = {}

    @defer.inlineCallbacks
    def start(self, name, file_path, bid, metadata):
        log.info('Starting publish for %s', name)

        self.publish_name = name
        self.file_path = file_path
        self.bid_amount = bid
        self.metadata = metadata
        self.file_name = os.path.basename(self.file_path)

        try:
            lbry_file = yield self._create_lbry_file()
            yield self._add_to_lbry_files(lbry_file)
            yield self._create_sd_blob()
            yield self._set_file_status_finished()
            yield self._push_file_to_reflector()
            yield self._claim_name()
        except Exception:
            log.exception(
                "An error occurred publishing %s to %s", self.file_name, self.publish_name)
            # TODO: I'm not a fan of the log and re-throw, especially when
            #       the new exception is more generic. Look over this to
            #       see if there is a reason not to remove the errback
            #       handler and allow the original exception to move up
            #       the stack.
            raise Exception("Publish Failed")
        else:
            log.info(
                "Success! Published %s --> lbry://%s txid: %s nout: %d",
                self.file_name, self.publish_name, self.txid, self.nout
            )
            defer.returnValue({
                'nout': self.nout,
                'txid': self.txid,
                'claim_id': self.claim_id,
                'fee': self.fee,
            })

    @defer.inlineCallbacks
    def _create_lbry_file(self):
        # TODO: we cannot have this sort of code scattered throughout
        #       our code base. Use polymorphism instead
        if os.name == "nt":
            file_mode = 'rb'
        else:
            file_mode = 'r'
        with open(self.file_path, file_mode) as fin:
            lbry_file = yield create_lbry_file(
                self.session, self.lbry_file_manager, self.file_name, fin)
        defer.returnValue(lbry_file)

    @defer.inlineCallbacks
    def _push_file_to_reflector(self):
        max_tries = 3
        tries = 1
        while tries <= max_tries:
            reflector_server = random.choice(self.reflector_servers)
            log.info(
                'Making attempt %s / %s to push published file %s to reflector server %s',
                tries, max_tries, self.publish_name, reflector_server)
            reflector_address, reflector_port = reflector_server
            factory = reflector.ClientFactory(
                self.session.blob_manager,
                self.lbry_file_manager.stream_info_manager,
                self.stream_hash
            )
            ip = yield reactor.resolve(reflector_address)
            yield reactor.connectTCP(ip, reflector_port, factory)
            result = yield factory.finished_deferred
            if result:
                break
            else:
                tries += 1

    @defer.inlineCallbacks
    def _add_to_lbry_files(self, stream_hash):
        self.stream_hash = stream_hash
        prm = self.session.payment_rate_manager
        self.lbry_file = yield self.lbry_file_manager.add_lbry_file(stream_hash, prm)

    @defer.inlineCallbacks
    def _create_sd_blob(self):
        log.debug('Creating stream descriptor blob')
        sd_hash = yield publish_sd_blob(self.lbry_file_manager.stream_info_manager,
                                        self.session.blob_manager,
                                        self.lbry_file.stream_hash)
        log.debug('stream descriptor hash: %s', sd_hash)
        self._set_sd_hash(sd_hash)

    def _set_sd_hash(self, sd_hash):
        if 'sources' not in self.metadata:
            self.metadata['sources'] = {}
        self.metadata['sources']['lbry_sd_hash'] = sd_hash

    @defer.inlineCallbacks
    def _set_file_status_finished(self):
        yield self.lbry_file_manager.change_lbry_file_status(
            self.lbry_file, ManagedEncryptedFileDownloader.STATUS_FINISHED)
        yield self.lbry_file.restore()

    def _claim_name(self):
        log.debug('Claiming name: %s', self.published_name)
        self._update_metadata()
        m = Metadata(self.metadata)
        claim_out = yield self.wallet.claim_name(self.publish_name, self.bid_amount, m)
        log.debug('Name claimed using txid: %s, nout: %d, claim_id: %s, fee :%f',
                  claim_out['txid'], claim_out['nout'],
                  claim_out['claim_id'], claim_out['fee'])
        self.txid = claim_out['txid']
        self.nout = claim_out['nout']
        self.claim_id = claim_out['claim_id']
        self.fee = claim_out['fee']

    def _update_metadata(self):
        filename = os.path.join(self.lbry_file.download_directory, self.lbry_file.file_name)
        self.metadata['content_type'] = get_content_type(filename)
        self.metadata['ver'] = Metadata.current_version


def get_content_type(filename):
    return mimetypes.guess_type(filename)[0] or 'application/octet-stream'
