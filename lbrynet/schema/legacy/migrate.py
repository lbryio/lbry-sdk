"""
migrate claim json schema (0.0.1-3) to protobuf (0.1.0)
"""

from lbrynet.schema.legacy import metadata_schemas
from lbrynet.schema.claim import ClaimDict
from .StructuredDict import StructuredDict


def migrate_001_to_002(metadata):
    metadata['ver'] = '0.0.2'
    metadata['nsfw'] = False


def migrate_002_to_003(metadata):
    metadata['ver'] = '0.0.3'
    if 'content-type' in metadata:
        metadata['content_type'] = metadata['content-type']
        del metadata['content-type']


class LegacyMetadata(StructuredDict):
    current_version = '0.0.3'

    _versions = [
        ('0.0.1', metadata_schemas.VER_001, None),
        ('0.0.2', metadata_schemas.VER_002, migrate_001_to_002),
        ('0.0.3', metadata_schemas.VER_003, migrate_002_to_003)
    ]

    def __init__(self, metadata, migrate=True, target_version=None):
        if not isinstance(metadata, dict):
            raise TypeError("{} is not a dictionary".format(metadata))
        starting_version = metadata.get('ver', '0.0.1')

        StructuredDict.__init__(self, metadata, starting_version, migrate, target_version)


def migrate_003_to_010(value):
    migrated_to_003 = LegacyMetadata(value)
    metadata = {
        "version": "_0_1_0"
    }
    for k in ["author", "description", "language", "license", "nsfw", "thumbnail", "title",
              "preview"]:
        if k in migrated_to_003:
            metadata.update({k: migrated_to_003[k]})

    if 'license_url' in migrated_to_003:
        metadata['licenseUrl'] = migrated_to_003['license_url']

    if "fee" in migrated_to_003:
        fee = migrated_to_003["fee"]
        currency = list(fee.keys())[0]
        amount = fee[currency]['amount']
        address = fee[currency]['address']
        metadata.update(dict(fee={"currency": currency, "version": "_0_0_1",
                                    "amount": amount, "address": address}))
    source = {
        "source": migrated_to_003['sources']['lbry_sd_hash'],
        "contentType": migrated_to_003['content_type'],
        "sourceType": "lbry_sd_hash",
        "version": "_0_0_1"
    }

    migrated = {
        "version": "_0_0_1",
        "claimType": "streamType",
        "stream": {
            "version": "_0_0_1",
            "metadata": metadata,
            "source": source
        }
    }
    return ClaimDict.load_dict(migrated)


def migrate(value):
    return migrate_003_to_010(value)
