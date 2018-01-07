import logging
import mimetypes
import os

from twisted.internet import defer

from lbrynet.core import file_utils
from lbrynet.file_manager.EncryptedFileCreator import create_lbry_file
from lbrynet.file_manager.EncryptedFileDownloader import ManagedEncryptedFileDownloader
from lbrynet.lbry_file.StreamDescriptor import publish_sd_blob


log = logging.getLogger(__name__)


class Publisher(object):
    def __init__(self, session, lbry_file_manager, wallet, certificate_id):
        self.session = session
        self.lbry_file_manager = lbry_file_manager
        self.wallet = wallet
        self.certificate_id = certificate_id
        self.lbry_file = None

    @defer.inlineCallbacks
    def create_and_publish_stream(self, name, bid, claim_dict, file_path, claim_address=None,
                                  change_address=None):
        """Create lbry file and make claim"""
        log.info('Starting publish for %s', name)
        if not os.path.isfile(file_path):
            raise Exception("File {} not found".format(file_path))
        if os.path.getsize(file_path) == 0:
            raise Exception("Cannot publish empty file {}".format(file_path))

        file_name = os.path.basename(file_path)
        with file_utils.get_read_handle(file_path) as read_handle:
            stream_hash = yield create_lbry_file(self.session, self.lbry_file_manager, file_name,
                                                 read_handle)
        sd_hash = yield publish_sd_blob(self.lbry_file_manager.stream_info_manager,
                            self.session.blob_manager, stream_hash)
        status = ManagedEncryptedFileDownloader.STATUS_FINISHED
        self.lbry_file = yield self.lbry_file_manager.add_lbry_file(stream_hash, sd_hash,
                                                                    status=status)
        if 'source' not in claim_dict['stream']:
            claim_dict['stream']['source'] = {}
        claim_dict['stream']['source']['source'] = sd_hash
        claim_dict['stream']['source']['sourceType'] = 'lbry_sd_hash'
        claim_dict['stream']['source']['contentType'] = get_content_type(file_path)
        claim_dict['stream']['source']['version'] = "_0_0_1"  # need current version here

        claim_out = yield self.make_claim(name, bid, claim_dict, claim_address, change_address)
        self.lbry_file.completed = True
        yield self.lbry_file.save_status()
        defer.returnValue(claim_out)

    @defer.inlineCallbacks
    def publish_stream(self, name, bid, claim_dict, claim_address=None, change_address=None):
        """Make a claim without creating a lbry file"""
        claim_out = yield self.make_claim(name, bid, claim_dict, claim_address, change_address)
        defer.returnValue(claim_out)

    @defer.inlineCallbacks
    def make_claim(self, name, bid, claim_dict, claim_address=None, change_address=None):
        claim_out = yield self.wallet.claim_name(name, bid, claim_dict,
                                                 certificate_id=self.certificate_id,
                                                 claim_address=claim_address,
                                                 change_address=change_address)
        defer.returnValue(claim_out)


def get_content_type(filename):
    return mimetypes.guess_type(filename)[0] or 'application/octet-stream'
