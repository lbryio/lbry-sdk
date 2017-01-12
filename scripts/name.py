import logging
import random

from twisted.internet import defer
from twisted.internet import reactor

from lbrynet.core import Error
from lbrynet.core import StreamDescriptor
from lbrynet.metadata import Metadata


log = logging.getLogger(__name__)


class Name(object):
    def __init__(self, name):
        self.name = name
        self.sd_hash = None
        self.sd_blob = None

    @defer.inlineCallbacks
    def setSdHash(self, wallet):
        try:
            stream = yield wallet.get_stream_info_for_name(self.name)
            metadata = Metadata.Metadata(stream)
            self.sd_hash = _getSdHash(metadata)
        except (Error.InvalidStreamInfoError, AssertionError):
            pass
        except Exception:
            log.exception('What happened')

    @defer.inlineCallbacks
    def download_sd_blob(self, session):
        print('Trying to get sd_blob for {} using {}'.format(self.name, self.sd_hash))
        try:
            blob = yield download_sd_blob_with_timeout(
                session, self.sd_hash, session.payment_rate_manager)

            self.sd_blob = blob
            yield self._after_download(blob)
            print('Downloaded sd_blob for {} using {}'.format(self.name, self.sd_hash))
        except defer.TimeoutError:
            print('Downloading sd_blob for {} timed-out'.format(self.name))
            # swallow errors from the timeout
            pass
        except Exception:
            log.exception('Failed to download {}'.format(self.name))

    def _after_download(self, blob):
        pass

def _getSdHash(metadata):
    return metadata['sources']['lbry_sd_hash']


def download_sd_blob_with_timeout(session, sd_hash, payment_rate_manager):
    d = StreamDescriptor.download_sd_blob(session, sd_hash, payment_rate_manager)
    d.addTimeout(random.randint(10, 30), reactor)
    return d
