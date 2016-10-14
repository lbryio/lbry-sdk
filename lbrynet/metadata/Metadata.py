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

def migrate_001_to_002(metadata):
    metadata['ver'] = '0.0.2'
    metadata['nsfw'] = False

def migrate_002_to_003(metadata):
    metadata['ver'] = '0.0.3'
    if 'content-type' in metadata:
        metadata['content_type'] = metadata['content-type']
        del metadata['content-type']


class Metadata(StructuredDict):
    current_version = '0.0.3'

    _versions = [
        ('0.0.1', metadata_schemas.VER_001, None),
        ('0.0.2', metadata_schemas.VER_002, migrate_001_to_002),
        ('0.0.3', metadata_schemas.VER_003, migrate_002_to_003)
    ]

    def __init__(self, metadata, migrate=True, target_version=None):
        starting_version = metadata.get('ver', '0.0.1')

        StructuredDict.__init__(self, metadata, starting_version, migrate, target_version)