import base64, binascii
from copy import deepcopy
from lbrynet.schema.address import decode_address, encode_address
from lbrynet.schema.legacy_schema_v1 import CLAIM_TYPES, CLAIM_TYPE, STREAM_TYPE, CERTIFICATE_TYPE
from lbrynet.schema.legacy_schema_v1 import SIGNATURE
from lbrynet.schema.error import DecodeError, InvalidAddress
from lbrynet.schema.signature import Signature


def encode_fields(claim_dictionary, detached_signature: Signature):
    """Encode bytes to hex and b58 for return by ClaimDict"""
    claim_dictionary = deepcopy(claim_dictionary)
    claim_type = CLAIM_TYPES[claim_dictionary[CLAIM_TYPE]]
    claim_value = claim_dictionary[claim_type]
    if claim_type == CLAIM_TYPES[STREAM_TYPE]:
        claim_value['source']['source'] = binascii.hexlify(claim_value['source']['source']).decode()
        if 'fee' in claim_value['metadata']:
            try:
                address = encode_address(claim_value['metadata']['fee']['address'])
            except InvalidAddress as err:
                raise DecodeError("Invalid fee address: %s" % err)
            claim_value['metadata']['fee']['address'] = address
    elif claim_type == CLAIM_TYPES[CERTIFICATE_TYPE]:
        public_key = claim_value["publicKey"]
        claim_value["publicKey"] = binascii.hexlify(public_key).decode()
    if SIGNATURE in claim_dictionary:
        encoded_sig = binascii.hexlify(claim_dictionary[SIGNATURE]['signature']).decode()
        encoded_cert_id = binascii.hexlify(claim_dictionary[SIGNATURE]['certificateId']).decode()
        claim_dictionary[SIGNATURE]['signature'] = encoded_sig
        claim_dictionary[SIGNATURE]['certificateId'] = encoded_cert_id
    elif detached_signature and detached_signature.raw_signature:
        claim_dictionary[SIGNATURE] = {
            'detached_signature': binascii.hexlify(detached_signature.serialized).decode(),
            'certificateId': binascii.hexlify(detached_signature.certificate_id).decode()
        }

    claim_dictionary[claim_type] = claim_value
    return claim_dictionary


def decode_fields(claim_dictionary):
    """Decode hex and b58 encoded bytes in dictionaries given to ClaimDict"""
    detached_signature = None
    claim_dictionary = deepcopy(claim_dictionary)
    claim_type = CLAIM_TYPES[claim_dictionary[CLAIM_TYPE]]
    claim_value = claim_dictionary[claim_type]
    if claim_type == CLAIM_TYPES[STREAM_TYPE]:
        claim_value['source']['source'] = binascii.unhexlify(claim_value['source']['source'])
        if 'fee' in claim_value['metadata']:
            try:
                address = decode_address(claim_value['metadata']['fee']['address'])
            except InvalidAddress as err:
                raise DecodeError("Invalid fee address: %s" % err)
            claim_value['metadata']['fee']['address'] = address
    elif claim_type == CLAIM_TYPES[CERTIFICATE_TYPE]:
        public_key = binascii.unhexlify(claim_value["publicKey"])
        claim_value["publicKey"] = public_key
    if SIGNATURE in claim_dictionary and not claim_dictionary[SIGNATURE].get('detached_signature'):
        decoded_sig = binascii.unhexlify(claim_dictionary[SIGNATURE]['signature'])
        decoded_cert_id = binascii.unhexlify(claim_dictionary[SIGNATURE]['certificateId'])
        claim_dictionary[SIGNATURE]['signature'] = decoded_sig
        claim_dictionary[SIGNATURE]['certificateId'] = decoded_cert_id
    elif claim_dictionary.get(SIGNATURE, {}).get('detached_signature'):
        hex_detached_signature = claim_dictionary[SIGNATURE]['detached_signature']
        detached_signature = Signature.flagged_parse(binascii.unhexlify(hex_detached_signature))
        del claim_dictionary[SIGNATURE]
    claim_dictionary[claim_type] = claim_value
    return claim_dictionary, detached_signature


def decode_b64_fields(claim_dictionary):
    """Decode b64 encoded bytes in protobuf generated dictionary to be given to ClaimDict"""
    claim_dictionary = deepcopy(claim_dictionary)
    claim_type = CLAIM_TYPES[claim_dictionary[CLAIM_TYPE]]
    claim_value = claim_dictionary[claim_type]
    if claim_type == CLAIM_TYPES[STREAM_TYPE]:
        claim_value['source']['source'] = base64.b64decode(claim_value['source']['source'])
        if 'fee' in claim_value['metadata']:
            address = base64.b64decode(claim_value['metadata']['fee']['address'])
            claim_value['metadata']['fee']['address'] = address
    elif claim_type == CLAIM_TYPES[CERTIFICATE_TYPE]:
        public_key = base64.b64decode(claim_value["publicKey"])
        claim_value["publicKey"] = public_key
    if SIGNATURE in claim_dictionary:
        encoded_sig = base64.b64decode(claim_dictionary[SIGNATURE]['signature'])
        encoded_cert_id = base64.b64decode(claim_dictionary[SIGNATURE]['certificateId'])
        claim_dictionary[SIGNATURE]['signature'] = encoded_sig
        claim_dictionary[SIGNATURE]['certificateId'] = encoded_cert_id
    claim_dictionary[claim_type] = claim_value
    return claim_dictionary
