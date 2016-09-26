import logging

from lbrynet.metadata.Validator import Validator, skip_validate
from lbrynet.metadata.LBRYFee import LBRYFeeValidator, verify_supported_currency
from lbrynet.conf import SOURCE_TYPES

log = logging.getLogger(__name__)
NAME_ALLOWED_CHARSET = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0987654321-'


def verify_name_characters(name):
    for c in name:
        assert c in NAME_ALLOWED_CHARSET, "Invalid character"
    return True


def validate_sources(sources):
    for source in sources:
        assert source in SOURCE_TYPES, "Unknown source type: %s" % str(source)
    return True


class Metadata(Validator):
    MV001 = "0.0.1"
    MV002 = "0.0.2"
    MV003 = "0.0.3"
    CURRENT_METADATA_VERSION = MV003

    METADATA_REVISIONS = {}

    METADATA_REVISIONS[MV001] = [
        (Validator.REQUIRE, 'title', skip_validate),
        (Validator.REQUIRE, 'description', skip_validate),
        (Validator.REQUIRE, 'author', skip_validate),
        (Validator.REQUIRE, 'language', skip_validate),
        (Validator.REQUIRE, 'license', skip_validate),
        (Validator.REQUIRE, 'content-type', skip_validate),
        (Validator.REQUIRE, 'sources', validate_sources),
        (Validator.OPTIONAL, 'thumbnail', skip_validate),
        (Validator.OPTIONAL, 'preview', skip_validate),
        (Validator.OPTIONAL, 'fee', verify_supported_currency),
        (Validator.OPTIONAL, 'contact', skip_validate),
        (Validator.OPTIONAL, 'pubkey', skip_validate),
    ]

    METADATA_REVISIONS[MV002] = [
        (Validator.REQUIRE, 'nsfw', skip_validate),
        (Validator.REQUIRE, 'ver', skip_validate),
        (Validator.OPTIONAL, 'license_url', skip_validate),
    ]

    METADATA_REVISIONS[MV003] = [
        (Validator.REQUIRE, 'content_type', skip_validate),
        (Validator.SKIP, 'content-type'),
        (Validator.OPTIONAL, 'sig', skip_validate),
        (Validator.IF_KEY, 'sig', (Validator.REQUIRE, 'pubkey', skip_validate), Validator.DO_NOTHING),
        (Validator.IF_KEY, 'pubkey', (Validator.REQUIRE, 'sig', skip_validate), Validator.DO_NOTHING),
    ]

    MIGRATE_MV001_TO_MV002 = [
        (Validator.IF_KEY, 'nsfw', Validator.DO_NOTHING, (Validator.LOAD, 'nsfw', False)),
        (Validator.IF_KEY, 'ver', Validator.DO_NOTHING, (Validator.LOAD, 'ver', MV002)),
    ]

    MIGRATE_MV002_TO_MV003 = [
        (Validator.IF_KEY, 'content-type', (Validator.UPDATE, 'content-type', 'content_type'), Validator.DO_NOTHING),
        (Validator.IF_VAL, 'ver', MV002, (Validator.LOAD, 'ver', MV003), Validator.DO_NOTHING),
    ]

    METADATA_MIGRATIONS = [
        MIGRATE_MV001_TO_MV002,
        MIGRATE_MV002_TO_MV003,
    ]

    current_version = CURRENT_METADATA_VERSION
    versions = METADATA_REVISIONS
    migrations = METADATA_MIGRATIONS

    def __init__(self, metadata, process_now=True):
        Validator.__init__(self, metadata, process_now)
        self.meta_version = self.get('ver', Metadata.MV001)
        self._load_fee()

    def _load_fee(self):
        if 'fee' in self:
            self.update({'fee': LBRYFeeValidator(self['fee'])})
