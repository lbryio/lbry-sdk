import logging

from lbrynet.metadata.StructuredDict import StructuredDict
import channel_metadata_schemas

log = logging.getLogger(__name__)


class ChannelMetadata(StructuredDict):
    current_version = '0.0.1'

    _versions = [
        ('0.0.1', channel_metadata_schemas.VER_001, None),
    ]

    def __init__(self, metadata, migrate=True, target_version=None):
        StructuredDict.__init__(self, metadata, metadata['ver'], migrate, target_version)