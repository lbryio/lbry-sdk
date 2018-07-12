import logging

from ecdsa import BadSignatureError
from binascii import unhexlify

from lbrynet.core.Error import UnknownNameError, UnknownClaimID, UnknownURI, UnknownOutpoint
from lbryschema.address import is_address
from lbryschema.claim import ClaimDict
from lbryschema.decode import smart_decode
from lbryschema.error import DecodeError

from .claim_proofs import verify_proof, InvalidProofError
log = logging.getLogger(__name__)


# Format amount to be decimal encoded string
# Format value to be hex encoded string
# TODO: refactor. Came from lbryum, there could be another part of torba doing it
def format_amount_value(obj):
    COIN = 100000000
    if isinstance(obj, dict):
        for k, v in obj.iteritems():
            if k == 'amount' or k == 'effective_amount':
                if not isinstance(obj[k], float):
                    obj[k] = float(obj[k]) / float(COIN)
            elif k == 'supports' and isinstance(v, list):
                obj[k] = [{'txid': txid, 'nout': nout, 'amount': float(amount) / float(COIN)}
                          for (txid, nout, amount) in v]
            elif isinstance(v, (list, dict)):
                obj[k] = format_amount_value(v)
    elif isinstance(obj, list):
        obj = [format_amount_value(o) for o in obj]
    return obj


def _get_permanent_url(claim_result):
    if claim_result.get('has_signature') and claim_result.get('channel_name'):
        return "{0}#{1}/{2}".format(
            claim_result['channel_name'],
            claim_result['value']['publisherSignature']['certificateId'],
            claim_result['name']
        )
    else:
        return "{0}#{1}".format(
            claim_result['name'],
            claim_result['claim_id']
        )


def _verify_proof(ledger, name, claim_trie_root, result, height, depth, transaction_class):
    """
    Verify proof for name claim
    """

    def _build_response(name, value, claim_id, txid, n, amount, effective_amount,
                        claim_sequence, claim_address, supports):
        r = {
            'name': name,
            'value': value.encode('hex'),
            'claim_id': claim_id,
            'txid': txid,
            'nout': n,
            'amount': amount,
            'effective_amount': effective_amount,
            'height': height,
            'depth': depth,
            'claim_sequence': claim_sequence,
            'address': claim_address,
            'supports': supports
        }
        return r

    def _parse_proof_result(name, result):
        support_amount = sum([amt for (stxid, snout, amt) in result['supports']])
        supports = result['supports']
        if 'txhash' in result['proof'] and 'nOut' in result['proof']:
            if 'transaction' in result:
                tx = transaction_class(raw=unhexlify(result['transaction']))
                nOut = result['proof']['nOut']
                if result['proof']['txhash'] == tx.hex_id:
                    if 0 <= nOut < len(tx.outputs):
                        claim_output = tx.outputs[nOut]
                        effective_amount = claim_output.amount + support_amount
                        claim_address = ledger.hash160_to_address(claim_output.script.values['pubkey_hash'])
                        claim_id = result['claim_id']
                        claim_sequence = result['claim_sequence']
                        claim_script = claim_output.script
                        decoded_name, decoded_value = claim_script.values['claim_name'], claim_script.values['claim']
                        if decoded_name == name:
                            return _build_response(name, decoded_value, claim_id,
                                                   tx.hex_id, nOut, claim_output.amount,
                                                   effective_amount, claim_sequence,
                                                   claim_address, supports)
                        return {'error': 'name in proof did not match requested name'}
                    outputs = len(tx['outputs'])
                    return {'error': 'invalid nOut: %d (let(outputs): %d' % (nOut, outputs)}
                return {'error': "computed txid did not match given transaction: %s vs %s" %
                                 (tx.hex_id, result['proof']['txhash'])
                        }
            return {'error': "didn't receive a transaction with the proof"}
        return {'error': 'name is not claimed'}

    if 'proof' in result:
        try:
            verify_proof(result['proof'], claim_trie_root, name)
        except InvalidProofError:
            return {'error': "Proof was invalid"}
        return _parse_proof_result(name, result)
    else:
        return {'error': "proof not in result"}


def validate_claim_signature_and_get_channel_name(claim, certificate_claim,
                                                  claim_address, decoded_certificate=None):
    if not certificate_claim:
        return False, None
    certificate = decoded_certificate or smart_decode(certificate_claim['value'])
    if not isinstance(certificate, ClaimDict):
        raise TypeError("Certificate is not a ClaimDict: %s" % str(type(certificate)))
    if _validate_signed_claim(claim, claim_address, certificate):
        return True, certificate_claim['name']
    return False, None


def _validate_signed_claim(claim, claim_address, certificate):
    if not claim.has_signature:
        raise Exception("Claim is not signed")
    if not is_address(claim_address):
        raise Exception("Not given a valid claim address")
    try:
        if claim.validate_signature(claim_address, certificate.protobuf):
            return True
    except BadSignatureError:
        # print_msg("Signature for %s is invalid" % claim_id)
        return False
    except Exception as err:
        log.error("Signature for %s is invalid, reason: %s - %s", claim_address,
                  str(type(err)), err)
        return False
    return False


# TODO: The following came from code handling lbryum results. Now that it's all in one place a refactor should unify it.
def _decode_claim_result(claim):
    if 'has_signature' in claim and claim['has_signature']:
        if not claim['signature_is_valid']:
            log.warning("lbry://%s#%s has an invalid signature",
                        claim['name'], claim['claim_id'])
    try:
        decoded = smart_decode(claim['value'])
        claim_dict = decoded.claim_dict
        claim['value'] = claim_dict
        claim['hex'] = decoded.serialized.encode('hex')
    except DecodeError:
        claim['hex'] = claim['value']
        claim['value'] = None
        claim['error'] = "Failed to decode value"
    return claim

def _handle_claim_result(results):
    if not results:
        #TODO: cannot determine what name we searched for here
        # we should fix lbryum commands that return None
        raise UnknownNameError("")

    if 'error' in results:
        if results['error'] in ['name is not claimed', 'claim not found']:
            if 'claim_id' in results:
                raise UnknownClaimID(results['claim_id'])
            elif 'name' in results:
                raise UnknownNameError(results['name'])
            elif 'uri' in results:
                raise UnknownURI(results['uri'])
            elif 'outpoint' in results:
                raise UnknownOutpoint(results['outpoint'])
        raise Exception(results['error'])

    # case where return value is {'certificate':{'txid', 'value',...},...}
    if 'certificate' in results:
        results['certificate'] = _decode_claim_result(results['certificate'])

    # case where return value is {'claim':{'txid','value',...},...}
    if 'claim' in results:
        results['claim'] = _decode_claim_result(results['claim'])

    # case where return value is {'txid','value',...}
    # returned by queries that are not name resolve related
    # (getclaimbyoutpoint, getclaimbyid, getclaimsfromtx)
    elif 'value' in results:
        results = _decode_claim_result(results)

    # case where there is no 'certificate', 'value', or 'claim' key
    elif 'certificate' not in results:
        msg = 'result in unexpected format:{}'.format(results)
        assert False, msg

    return results
