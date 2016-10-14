import logging

from lbrynet.metadata.StructuredDict import StructuredDict
from lbrynet.conf import SOURCE_TYPES
import metadata_schemas

log = logging.getLogger(__name__)
NAME_ALLOWED_CHARSET = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0987654321-'


def verify_name_characters(name):
    for c in name:
        assert c in NAME_ALLOWED_CHARSET, "Invalid character"
    return True


class Metadata(StructuredDict):
    current_version = '0.0.3'

    def __init__(self, metadata, migrate=True, target_version=None):
        self._versions = [
            ('0.0.1', metadata_schemas.VER_001, None),
            ('0.0.2', metadata_schemas.VER_002, self._migrate_001_to_002),
            ('0.0.3', metadata_schemas.VER_003, self._migrate_002_to_003)
        ]

        starting_version = metadata.get('ver', '0.0.1')

        StructuredDict.__init__(self, metadata, starting_version, migrate, target_version)


    def _migrate_001_to_002(self):
        self['ver'] = '0.0.2'

    def _migrate_002_to_003(self):
        self['ver'] = '0.0.3'

        if 'content-type' in self:
            self['content_type'] = self['content-type']
            del self['content-type']