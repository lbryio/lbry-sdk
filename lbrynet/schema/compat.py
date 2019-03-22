import json
from decimal import Decimal

from lbrynet.schema.types.v1.legacy_claim_pb2 import Claim as OldClaimMessage
from lbrynet.schema.types.v1.metadata_pb2 import Metadata as MetadataMessage
from lbrynet.schema.types.v1.certificate_pb2 import KeyType
from lbrynet.schema.types.v1.fee_pb2 import Fee as FeeMessage


def from_old_json_schema(claim, payload: bytes):
    value = json.loads(payload)
    stream = claim.stream
    stream.media_type = value.get('content_type', value.get('content-type', 'application/octet-stream'))
    stream.title = value.get('title', '')
    stream.description = value.get('description', '')
    stream.thumbnail_url = value.get('thumbnail', '')
    stream.author = value.get('author', '')
    stream.license = value.get('license', '')
    stream.license_url = value.get('license_url', '')
    stream.language = value.get('language', '')
    stream.hash = value['sources']['lbry_sd_hash']
    if value.get('nsfw', False):
        stream.tags.append('mature')
    if "fee" in value:
        fee = value["fee"]
        currency = list(fee.keys())[0]
        if currency == 'LBC':
            stream.fee.lbc = Decimal(fee[currency]['amount'])
        elif currency == 'USD':
            stream.fee.usd = Decimal(fee[currency]['amount'])
        else:
            raise ValueError(f'Unknown currency: {currency}')
        stream.fee.address = fee[currency]['address']
    return claim


def from_types_v1(claim, payload: bytes):
    old = OldClaimMessage()
    old.ParseFromString(payload)
    if old.claimType == 1:
        stream = claim.stream
        stream.title = old.stream.metadata.title
        stream.description = old.stream.metadata.description
        stream.author = old.stream.metadata.author
        stream.license = old.stream.metadata.license
        stream.license_url = old.stream.metadata.licenseUrl
        stream.thumbnail_url = old.stream.metadata.thumbnail
        stream.language = MetadataMessage.Language.Name(old.stream.metadata.language)
        stream.media_type = old.stream.source.contentType
        stream.hash_bytes = old.stream.source.source
        if old.stream.metadata.nsfw:
            stream.tags.append('mature')
        if old.stream.metadata.HasField('fee'):
            fee = old.stream.metadata.fee
            stream.fee.address_bytes = fee.address
            currency = FeeMessage.Currency.Name(fee.currency)
            if currency == 'LBC':
                stream.fee.lbc = Decimal(fee.amount)
            elif currency == 'USD':
                stream.fee.usd = Decimal(fee.amount)
            else:
                raise ValueError(f'Unsupported currency: {currency}')
        if old.HasField('publisherSignature'):
            sig = old.publisherSignature
            claim.signature = sig.signature
            claim.signature_type = KeyType.Name(sig.signatureType)
            claim.signing_channel_hash = sig.certificateId
            old.ClearField("publisherSignature")
            claim.unsigned_payload = old.SerializeToString()
    elif old.claimType == 2:
        channel = claim.channel
        channel.public_key_bytes = old.certificate.publicKey
    else:
        raise ValueError('claimType must be 1 for Streams and 2 for Channel')
    return claim
