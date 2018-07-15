import logging

from ecdsa import BadSignatureError
from binascii import unhexlify

from twisted.internet import defer

from lbrynet.core.Error import UnknownNameError, UnknownClaimID, UnknownURI, UnknownOutpoint
from lbryschema.address import is_address
from lbryschema.claim import ClaimDict
from lbryschema.decode import smart_decode
from lbryschema.error import DecodeError
from lbryschema.uri import parse_lbry_uri

from .claim_proofs import verify_proof, InvalidProofError
log = logging.getLogger(__name__)


class Resolver:

    def __init__(self, claim_trie_root, height, transaction_class, hash160_to_address, network):
        self.claim_trie_root = claim_trie_root
        self.height = height
        self.transaction_class = transaction_class
        self.hash160_to_address = hash160_to_address
        self.network = network

    @defer.inlineCallbacks
    def _handle_resolutions(self, resolutions, requested_uris, page, page_size):
        results = {}
        for uri in requested_uris:
            resolution = (resolutions or {}).get(uri, {})
            if resolution:
                try:
                    results[uri] = _handle_claim_result(
                        (yield self._handle_resolve_uri_response(uri, resolution, page, page_size))
                    )
                except (UnknownNameError, UnknownClaimID, UnknownURI) as err:
                    results[uri] = {'error': err.message}
        defer.returnValue(results)

    @defer.inlineCallbacks
    def _handle_resolve_uri_response(self, uri, resolution, page=0, page_size=10, raw=False):
        result = {}
        claim_trie_root = self.claim_trie_root
        parsed_uri = parse_lbry_uri(uri)
        certificate = None
        # parse an included certificate
        if 'certificate' in resolution:
            certificate_response = resolution['certificate']['result']
            certificate_resolution_type = resolution['certificate']['resolution_type']
            if certificate_resolution_type == "winning" and certificate_response:
                if 'height' in certificate_response:
                    height = certificate_response['height']
                    depth = self.height - height
                    certificate_result = _verify_proof(parsed_uri.name,
                                                       claim_trie_root,
                                                       certificate_response,
                                                       height, depth,
                                                       transaction_class=self.transaction_class,
                                                       hash160_to_address=self.hash160_to_address)
                    result['certificate'] = self.parse_and_validate_claim_result(certificate_result,
                                                                                 raw=raw)
            elif certificate_resolution_type == "claim_id":
                result['certificate'] = self.parse_and_validate_claim_result(certificate_response,
                                                                             raw=raw)
            elif certificate_resolution_type == "sequence":
                result['certificate'] = self.parse_and_validate_claim_result(certificate_response,
                                                                             raw=raw)
            else:
                log.error("unknown response type: %s", certificate_resolution_type)

            if 'certificate' in result:
                certificate = result['certificate']
                if 'unverified_claims_in_channel' in resolution:
                    max_results = len(resolution['unverified_claims_in_channel'])
                    result['claims_in_channel'] = max_results
                else:
                    result['claims_in_channel'] = 0
            else:
                result['error'] = "claim not found"
                result['success'] = False
                result['uri'] = str(parsed_uri)

        else:
            certificate = None

        # if this was a resolution for a name, parse the result
        if 'claim' in resolution:
            claim_response = resolution['claim']['result']
            claim_resolution_type = resolution['claim']['resolution_type']
            if claim_resolution_type == "winning" and claim_response:
                if 'height' in claim_response:
                    height = claim_response['height']
                    depth = self.height - height
                    claim_result = _verify_proof(parsed_uri.name,
                                                 claim_trie_root,
                                                 claim_response,
                                                 height, depth,
                                                 transaction_class=self.transaction_class,
                                                 hash160_to_address=self.hash160_to_address)
                    result['claim'] = self.parse_and_validate_claim_result(claim_result,
                                                                           certificate,
                                                                           raw)
            elif claim_resolution_type == "claim_id":
                result['claim'] = self.parse_and_validate_claim_result(claim_response,
                                                                       certificate,
                                                                       raw)
            elif claim_resolution_type == "sequence":
                result['claim'] = self.parse_and_validate_claim_result(claim_response,
                                                                       certificate,
                                                                       raw)
            else:
                log.error("unknown response type: %s", claim_resolution_type)

        # if this was a resolution for a name in a channel make sure there is only one valid
        # match
        elif 'unverified_claims_for_name' in resolution and 'certificate' in result:
            unverified_claims_for_name = resolution['unverified_claims_for_name']

            channel_info = yield self.get_channel_claims_page(unverified_claims_for_name,
                                                              result['certificate'], page=1)
            claims_in_channel, upper_bound = channel_info

            if len(claims_in_channel) > 1:
                log.error("Multiple signed claims for the same name")
            elif not claims_in_channel:
                log.error("No valid claims for this name for this channel")
            else:
                result['claim'] = claims_in_channel[0]

        # parse and validate claims in a channel iteratively into pages of results
        elif 'unverified_claims_in_channel' in resolution and 'certificate' in result:
            ids_to_check = resolution['unverified_claims_in_channel']
            channel_info = yield self.get_channel_claims_page(ids_to_check, result['certificate'],
                                                              page=page, page_size=page_size)
            claims_in_channel, upper_bound = channel_info

            if claims_in_channel:
                result['claims_in_channel'] = claims_in_channel
        elif 'error' not in result:
            result['error'] = "claim not found"
            result['success'] = False
            result['uri'] = str(parsed_uri)

        defer.returnValue(result)

    def parse_and_validate_claim_result(self, claim_result, certificate=None, raw=False):
        if not claim_result or 'value' not in claim_result:
            return claim_result

        claim_result['decoded_claim'] = False
        decoded = None

        if not raw:
            claim_value = claim_result['value']
            try:
                decoded = smart_decode(claim_value)
                claim_result['value'] = decoded.claim_dict
                claim_result['decoded_claim'] = True
            except DecodeError:
                pass

        if decoded:
            claim_result['has_signature'] = False
            if decoded.has_signature:
                if certificate is None:
                    log.info("fetching certificate to check claim signature")
                    certificate = self.network.get_claims_by_ids(decoded.certificate_id)
                    if not certificate:
                        log.warning('Certificate %s not found', decoded.certificate_id)
                claim_result['has_signature'] = True
                claim_result['signature_is_valid'] = False
                validated, channel_name = validate_claim_signature_and_get_channel_name(
                    decoded, certificate, claim_result['address'])
                claim_result['channel_name'] = channel_name
                if validated:
                    claim_result['signature_is_valid'] = True

        if 'height' in claim_result and claim_result['height'] is None:
            claim_result['height'] = -1

        if 'amount' in claim_result and not isinstance(claim_result['amount'], float):
            claim_result = format_amount_value(claim_result)

        claim_result['permanent_url'] = _get_permanent_url(claim_result)

        return claim_result

    @staticmethod
    def prepare_claim_queries(start_position, query_size, channel_claim_infos):
        queries = [tuple()]
        names = {}
        # a table of index counts for the sorted claim ids, including ignored claims
        absolute_position_index = {}

        block_sorted_infos = sorted(channel_claim_infos.items(), key=lambda x: int(x[1][1]))
        per_block_infos = {}
        for claim_id, (name, height) in block_sorted_infos:
            claims = per_block_infos.get(height, [])
            claims.append((claim_id, name))
            per_block_infos[height] = sorted(claims, key=lambda x: int(x[0], 16))

        abs_position = 0

        for height in sorted(per_block_infos.keys(), reverse=True):
            for claim_id, name in per_block_infos[height]:
                names[claim_id] = name
                absolute_position_index[claim_id] = abs_position
                if abs_position >= start_position:
                    if len(queries[-1]) >= query_size:
                        queries.append(tuple())
                    queries[-1] += (claim_id,)
                abs_position += 1
        return queries, names, absolute_position_index

    @defer.inlineCallbacks
    def iter_channel_claims_pages(self, queries, claim_positions, claim_names, certificate,
                                  page_size=10):
        # lbryum server returns a dict of {claim_id: (name, claim_height)}
        # first, sort the claims by block height (and by claim id int value within a block).

        # map the sorted claims into getclaimsbyids queries of query_size claim ids each

        # send the batched queries to lbryum server and iteratively validate and parse
        # the results, yield a page of results at a time.

        # these results can include those where `signature_is_valid` is False. if they are skipped,
        # page indexing becomes tricky, as the number of results isn't known until after having
        # processed them.
        # TODO: fix ^ in lbryschema

        @defer.inlineCallbacks
        def iter_validate_channel_claims():
            formatted_claims = []
            for claim_ids in queries:
                batch_result = yield self.network.get_claims_by_ids(*claim_ids)
                for claim_id in claim_ids:
                    claim = batch_result[claim_id]
                    if claim['name'] == claim_names[claim_id]:
                        formatted_claim = self.parse_and_validate_claim_result(claim, certificate)
                        formatted_claim['absolute_channel_position'] = claim_positions[
                            claim['claim_id']]
                        formatted_claims.append(formatted_claim)
                    else:
                        log.warning("ignoring claim with name mismatch %s %s", claim['name'],
                                    claim['claim_id'])
                defer.returnValue(formatted_claims)

        yielded_page = False
        results = []

        for claim in (yield iter_validate_channel_claims()):
            results.append(claim)

            # if there is a full page of results, yield it
            if len(results) and len(results) % page_size == 0:
                defer.returnValue(results[-page_size:])
                yielded_page = True

        # if we didn't get a full page of results, yield what results we did get
        if not yielded_page:
            defer.returnValue(results)

    @defer.inlineCallbacks
    def get_channel_claims_page(self, channel_claim_infos, certificate, page, page_size=10):
        page = page or 0
        page_size = max(page_size, 1)
        if page_size > 500:
            raise Exception("page size above maximum allowed")
        start_position = (page - 1) * page_size
        queries, names, claim_positions = self.prepare_claim_queries(start_position, page_size,
                                                                     channel_claim_infos)
        page_generator = yield self.iter_channel_claims_pages(queries, claim_positions, names,
                                                              certificate, page_size=page_size)
        upper_bound = len(claim_positions)
        if not page:
            defer.returnValue((None, upper_bound))
        if start_position > upper_bound:
            raise IndexError("claim %i greater than max %i" % (start_position, upper_bound))
        defer.returnValue((page_generator, upper_bound))


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


def _verify_proof(name, claim_trie_root, result, height, depth, transaction_class, hash160_to_address):
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
                        claim_address = hash160_to_address(claim_output.script.values['pubkey_hash'])
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
