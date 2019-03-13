def migrate_001_to_002(metadata):
    metadata['ver'] = '0.0.2'
    metadata['nsfw'] = False


def migrate_002_to_003(metadata):
    metadata['ver'] = '0.0.3'
    if 'content-type' in metadata:
        metadata['content_type'] = metadata['content-type']
        del metadata['content-type']


def migrate_003_to_010(value):
    metadata = {
        "version": "_0_1_0",
        "title": value.get('title', ''),
        "description": value.get('description', ''),
        "thumbnail": value.get('thumbnail', ''),
        "preview": value.get('preview', ''),
        "author": value.get('author', ''),
        "license": value.get('license', ''),
        "licenseUrl": value.get('license_url', ''),
        "language": value.get('language', ''),
        "nsfw": value.get('nsfw', False),
    }
    if "fee" in value:
        fee = value["fee"]
        currency = list(fee.keys())[0]
        metadata['fee'] = {
            "version": "_0_0_1",
            "currency": currency,
            "amount": fee[currency]['amount'],
            "address": fee[currency]['address']
        }
    source = {
        "source": value['sources']['lbry_sd_hash'],
        "contentType": value['content_type'],
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
    return migrated


def migrate(value):
    if value.get('ver', '0.0.1') == '0.0.1':
        migrate_001_to_002(value)
    if value['ver'] == '0.0.2':
        migrate_002_to_003(value)
    if value['ver'] == '0.0.3':
        value = migrate_003_to_010(value)
    return value
