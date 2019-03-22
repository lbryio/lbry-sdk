import json
import binascii
from google.protobuf import json_format  # pylint: disable=no-name-in-module

from lbrynet.schema.error import DecodeError, InvalidAddress
from lbrynet.schema.legacy.migrate import migrate as schema_migrator
from lbrynet.schema.claim import ClaimDict


def migrate_legacy_protobuf(old_proto_bytes: bytes):
    # TODO: where to put this?
    from lbrynet.schema.proto2.legacy_claim_pb2 import Claim as OldClaimPB
    from google.protobuf import json_format  # pylint: disable=no-name-in-module
    from lbrynet.schema.encoding import decode_b64_fields
    from lbrynet.schema.current_schema.claim import Claim as CurrentClaim
    old_msg = OldClaimPB()
    old_msg.ParseFromString(old_proto_bytes)
    old_json = json.loads(json_format.MessageToJson(old_msg, True))
    return CurrentClaim.load(decode_b64_fields(old_json))



def migrate_json_claim_value(decoded_json):
    try:
        if 'fee' in decoded_json:
            old_fee = decoded_json['fee']
            if not old_fee[list(old_fee.keys())[0]]['amount']:
                del decoded_json['fee']
                return migrate_json_claim_value(decoded_json)
    except (TypeError, AttributeError, InvalidAddress):
        raise DecodeError("Failed to decode claim")
    try:
        pb_migrated = schema_migrator(decoded_json)
        return pb_migrated
    except json_format.ParseError as parse_error:
        raise DecodeError("Failed to parse protobuf: %s" % parse_error)
    except Exception as err:
        raise DecodeError("Failed to migrate claim: %s" % err)


def smart_decode(claim_value):
    """
    Decode a claim value

    Try decoding claim protobuf, if this fails try decoding json and migrating it.
    If unable to decode or migrate, raise DecodeError
    """

    # if already decoded, return
    if isinstance(claim_value, ClaimDict):
        return claim_value
    elif isinstance(claim_value, dict):
        return ClaimDict.load_dict(claim_value)

    try:
        claim_value = binascii.unhexlify(claim_value)
    except (TypeError, ValueError):
        pass

    if claim_value[0] in ['{', ord('{')]:
        try:
            if isinstance(claim_value, bytes):
                claim_value = claim_value.decode()
            decoded_json = json.loads(claim_value)
            return migrate_json_claim_value(decoded_json)
        except (ValueError, TypeError):
            pass
    try:
        if isinstance(claim_value, str):
            claim_value = claim_value.encode()
        return ClaimDict.deserialize(claim_value)
    except (DecodeError, InvalidAddress, KeyError, TypeError):
        raise DecodeError(claim_value)
