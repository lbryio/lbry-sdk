import logging
import mimetypes
import os

from twisted.internet import defer
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

    @defer.inlineCallbacks
    def start(self, name, file_path, bid, metadata):
        log.info('Starting publish for %s', name)
        file_name = os.path.basename(file_path)
        with file_utils.get_read_handle(file_path) as read_handle:
            stream_hash = yield create_lbry_file(self.session, self.lbry_file_manager, file_name,
                                                 read_handle)
        prm = self.session.payment_rate_manager
        lbry_file = yield self.lbry_file_manager.add_lbry_file(stream_hash, prm)
        sd_hash = yield publish_sd_blob(self.lbry_file_manager.stream_info_manager,
                            self.session.blob_manager,
                            lbry_file.stream_hash)
        if 'sources' not in metadata:
            metadata['sources'] = {}
        metadata['sources']['lbry_sd_hash'] = sd_hash
        metadata['content_type'] = get_content_type(file_path)
        metadata['ver'] = Metadata.current_version
        validated_metadata = Metadata(metadata)

        claim_out = yield self.wallet.claim_name(name, bid, validated_metadata)
        log.info("Success! Published %s --> lbry://%s txid: %s nout: %d", file_name, name,
                 claim_out['txid'], claim_out['nout'])
        defer.returnValue(claim_out)


def get_content_type(filename):
    return mimetypes.guess_type(filename)[0] or 'application/octet-stream'
