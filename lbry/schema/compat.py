import json
from decimal import Decimal

from google.protobuf.message import DecodeError

from lbry_types.v1.legacy_claim_pb2 import Claim as OldClaimMessage
from lbry_types.v1.certificate_pb2 import KeyType
from lbry_types.v1.fee_pb2 import Fee as FeeMessage


def from_old_json_schema(claim, payload: bytes):
    try:
        value = json.loads(payload)
    except:
        raise DecodeError('Could not parse JSON.')
    stream = claim.stream
    stream.source.sd_hash = value['sources']['lbry_sd_hash']
    stream.source.media_type = (
            value.get('content_type', value.get('content-type')) or
            'application/octet-stream'
    )
    stream.title = value.get('title', '')
    stream.description = value.get('description', '')
    if value.get('thumbnail', ''):
        stream.thumbnail.url = value.get('thumbnail', '')
    stream.author = value.get('author', '')
    stream.license = value.get('license', '')
    stream.license_url = value.get('license_url', '')
    language = value.get('language', '')
    if language:
        if language.lower() == 'english':
            language = 'en'
        try:
            stream.languages.append(language)
        except:
            pass
    if value.get('nsfw', False):
        stream.tags.append('mature')
    if "fee" in value and isinstance(value['fee'], dict):
        fee = value["fee"]
        currency = list(fee.keys())[0]
        if currency == 'LBC':
            stream.fee.lbc = Decimal(fee[currency]['amount'])
        elif currency == 'USD':
            stream.fee.usd = Decimal(fee[currency]['amount'])
        elif currency == 'BTC':
            stream.fee.btc = Decimal(fee[currency]['amount'])
        else:
            raise DecodeError(f'Unknown currency: {currency}')
        stream.fee.address = fee[currency]['address']
    return claim


def from_types_v1(claim, payload: bytes):
    old = OldClaimMessage()
    old.ParseFromString(payload)
    if old.claimType == 2:
        channel = claim.channel
        channel.public_key_bytes = old.certificate.publicKey
    else:
        stream = claim.stream
        stream.title = old.stream.metadata.title
        stream.description = old.stream.metadata.description
        stream.author = old.stream.metadata.author
        stream.license = old.stream.metadata.license
        stream.license_url = old.stream.metadata.licenseUrl
        stream.thumbnail.url = old.stream.metadata.thumbnail
        if old.stream.metadata.HasField('language'):
            stream.languages.add().message.language = old.stream.metadata.language
        stream.source.media_type = old.stream.source.contentType
        stream.source.sd_hash_bytes = old.stream.source.source
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
            elif currency == 'BTC':
                stream.fee.btc = Decimal(fee.amount)
            else:
                raise DecodeError(f'Unsupported currency: {currency}')
        if old.HasField('publisherSignature'):
            sig = old.publisherSignature
            claim.signature = sig.signature
            claim.signature_type = KeyType.Name(sig.signatureType)
            claim.signing_channel_hash = sig.certificateId[::-1]
            old.ClearField("publisherSignature")
            claim.unsigned_payload = old.SerializeToString()
    return claim
