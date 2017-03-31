import logging
import mimetypes
import os

from twisted.internet import defer

from lbryschema.claim import ClaimDict

from lbrynet.core import file_utils
from lbrynet.lbryfilemanager.EncryptedFileCreator import create_lbry_file
from lbrynet.lbryfile.StreamDescriptor import publish_sd_blob
from lbrynet.metadata.Metadata import Metadata


log = logging.getLogger(__name__)


class Publisher(object):
    def __init__(self, session, lbry_file_manager, wallet):
        self.session = session
        self.lbry_file_manager = lbry_file_manager
        self.wallet = wallet
        self.lbry_file = None

    """
    Create lbry file and make claim
    """
    @defer.inlineCallbacks
    def create_and_publish_stream(self, name, bid, claim_dict, file_path):
        log.info('Starting publish for %s', name)
        file_name = os.path.basename(file_path)
        with file_utils.get_read_handle(file_path) as read_handle:
            stream_hash = yield create_lbry_file(self.session, self.lbry_file_manager, file_name,
                                                 read_handle)
        prm = self.session.payment_rate_manager
        self.lbry_file = yield self.lbry_file_manager.add_lbry_file(stream_hash, prm)
        sd_hash = yield publish_sd_blob(self.lbry_file_manager.stream_info_manager,
                            self.session.blob_manager, self.lbry_file.stream_hash)
        if 'source' not in claim_dict['stream']:
            claim_dict['stream']['source'] = {}
        claim_dict['stream']['source']['source'] = sd_hash
        claim_dict['stream']['source']['sourceType'] = 'lbry_sd_hash'
        claim_dict['stream']['source']['contentType'] = get_content_type(file_path)
        claim_dict['stream']['source']['version'] = "_0_0_1" # need current version here

        claim_out = yield self.make_claim(name, bid, claim_dict)
        self.lbry_file.completed = True
        yield self.lbry_file.load_file_attributes()
        yield self.lbry_file.save_status()
        defer.returnValue(claim_out)

    """
    Make a claim without creating a lbry file
    """
    @defer.inlineCallbacks
    def publish_stream(self, name, bid, claim_dict):
        claim_out = yield self.make_claim(name, bid, claim_dict)
        defer.returnValue(claim_out)

    @defer.inlineCallbacks
    def make_claim(self, name, bid, claim_dict):
        claim_out = yield self.wallet.claim_name(name, bid, claim_dict)
        defer.returnValue(claim_out)


def get_content_type(filename):
    return mimetypes.guess_type(filename)[0] or 'application/octet-stream'
