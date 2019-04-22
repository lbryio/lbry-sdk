import logging

import asyncio
from functools import lru_cache

from cryptography.exceptions import InvalidSignature
from binascii import unhexlify, hexlify

from lbrynet.wallet.account import validate_claim_id
from lbrynet.wallet.dewies import dewies_to_lbc
from lbrynet.error import UnknownNameError, UnknownClaimID, UnknownURI, UnknownOutpoint
from lbrynet.schema.claim import Claim
from google.protobuf.message import DecodeError
from lbrynet.schema.uri import parse_lbry_uri, URIParseError
from lbrynet.wallet.claim_proofs import verify_proof, InvalidProofError

log = logging.getLogger(__name__)


class Resolver:

    def __init__(self, ledger):
        self.transaction_class = ledger.transaction_class
        self.network = ledger.network
        self.ledger = ledger

    async def resolve(self, page, page_size, *uris):
        uris = set(uris)
        try:
            for uri in uris:
                parsed_uri = parse_lbry_uri(uri)
                if parsed_uri.claim_id:
                    validate_claim_id(parsed_uri.claim_id)
            claim_trie_root = self.ledger.headers.claim_trie_root
            resolutions = await self.network.get_values_for_uris(self.ledger.headers.hash().decode(), *uris)
            if len(uris) > 1:
                return await self._batch_handle(resolutions, uris, page, page_size, claim_trie_root)
            return await self._handle_resolutions(resolutions, uris, page, page_size, claim_trie_root)
        except URIParseError as err:
            return {'error': err.args[0]}
        except Exception as e:
            log.exception(e)
            return {'error': str(e)}

    async def _batch_handle(self, resolutions, uris, page, page_size, claim_trie_root):
        futs = []
        for uri in uris:
            futs.append(
                asyncio.ensure_future(self._handle_resolutions(resolutions, [uri], page, page_size, claim_trie_root))
            )
        results = await asyncio.gather(*futs)
        return dict(list(map(lambda result: list(result.items())[0], results)))

    @lru_cache(256)
    def _fetch_tx(self, txid):
        async def __fetch_parse(txid):
            return self.transaction_class(unhexlify(await self.network.get_transaction(txid)))
        return asyncio.ensure_future(__fetch_parse(txid))

    async def _handle_resolutions(self, resolutions, requested_uris, page, page_size, claim_trie_root):
        results = {}
        for uri in requested_uris:
            resolution = (resolutions or {}).get(uri, {})
            if resolution:
                try:
                    results[uri] = _handle_claim_result(
                        await self._handle_resolve_uri_response(uri, resolution, claim_trie_root, page, page_size),
                        uri
                    )
                except (UnknownNameError, UnknownClaimID, UnknownURI) as err:
                    log.exception(err)
                    results[uri] = {'error': str(err)}
            else:
                results[uri] = {'error': "URI lbry://{} cannot be resolved".format(uri.replace("lbry://", ""))}
        return results

    async def _handle_resolve_uri_response(self, uri, resolution, claim_trie_root, page=0, page_size=10):
        result = {}
        parsed_uri = parse_lbry_uri(uri)
        certificate_response = None
        # parse an included certificate
        if 'certificate' in resolution:
            certificate_response = resolution['certificate']['result']
            certificate_resolution_type = resolution['certificate']['resolution_type']
            if certificate_resolution_type == "winning" and certificate_response:
                if 'height' in certificate_response:
                    certificate_response = _verify_proof(parsed_uri.name,
                                                       claim_trie_root,
                                                       certificate_response,
                                                       ledger=self.ledger)
            elif certificate_resolution_type not in ['winning', 'claim_id', 'sequence']:
                raise Exception(f"unknown response type: {certificate_resolution_type}")
            result['certificate'] = await self.parse_and_validate_claim_result(certificate_response)
            result['claims_in_channel'] = len(resolution.get('unverified_claims_in_channel', []))

        # if this was a resolution for a name, parse the result
        if 'claim' in resolution:
            claim_response = resolution['claim']['result']
            claim_resolution_type = resolution['claim']['resolution_type']
            if claim_resolution_type == "winning" and claim_response:
                if 'height' in claim_response:
                    claim_response = _verify_proof(parsed_uri.name,
                                                   claim_trie_root,
                                                   claim_response,
                                                   ledger=self.ledger)
            elif claim_resolution_type not in ["sequence", "winning", "claim_id"]:
                raise Exception(f"unknown response type: {claim_resolution_type}")
            result['claim'] = await self.parse_and_validate_claim_result(claim_response,
                                                                         certificate_response)

        # if this was a resolution for a name in a channel make sure there is only one valid
        # match
        elif 'unverified_claims_for_name' in resolution and 'certificate' in result:
            unverified_claims_for_name = resolution['unverified_claims_for_name']

            channel_info = await self.get_channel_claims_page(unverified_claims_for_name,
                                                              result['certificate'], page=1)
            claims_in_channel, upper_bound = channel_info

            if not claims_in_channel:
                log.error("No valid claims for this name for this channel")
            elif len(claims_in_channel) > 1:
                log.warning("Multiple signed claims for the same name.")
                winner = pick_winner_from_channel_path_collision(claims_in_channel)
                if winner:
                    result['claim'] = winner
                else:
                    log.error("No valid claims for this name for this channel")
            else:
                result['claim'] = claims_in_channel[0]

        # parse and validate claims in a channel iteratively into pages of results
        elif 'unverified_claims_in_channel' in resolution and 'certificate' in result:
            ids_to_check = resolution['unverified_claims_in_channel']
            channel_info = await self.get_channel_claims_page(ids_to_check, result['certificate'],
                                                              page=page, page_size=page_size)
            claims_in_channel, upper_bound = channel_info

            if claims_in_channel:
                result['total_claims'] = upper_bound
                result['claims_in_channel'] = claims_in_channel
        elif 'error' not in result:
            return {'error': 'claim not found', 'success': False, 'uri': str(parsed_uri)}

        # invalid signatures can only return outside a channel
        if result.get('claim', {}).get('has_signature', False):
            if parsed_uri.path and not result['claim']['signature_is_valid']:
                return {'error': 'claim not found', 'success': False, 'uri': str(parsed_uri)}
        return result

    async def parse_and_validate_claim_result(self, claim_result, certificate=None):
        if not claim_result or 'value' not in claim_result:
            return claim_result
        claim_result = _decode_claim_result(claim_result)

        if claim_result['value']:
            claim_result['has_signature'] = False
            if claim_result['value'].is_signed:
                claim_result['has_signature'] = True
                claim_tx = await self._fetch_tx(claim_result['txid'])
                if certificate is None:
                    log.info("fetching certificate to check claim signature")
                    channel_id = claim_result['value'].signing_channel_id
                    certificate = (await self.network.get_claims_by_ids(channel_id)).get(channel_id)
                    if not certificate:
                        log.warning('Certificate %s not found', channel_id)
                claim_result['channel_name'] = certificate['name'] if certificate else None
                cert_tx = await self._fetch_tx(certificate['txid']) if certificate else None
                claim_result['signature_is_valid'] = validate_claim_signature_and_get_channel_name(
                    claim_result, certificate, self.ledger, claim_tx=claim_tx, cert_tx=cert_tx
                )
                # fixme: workaround while json encoder isnt used here
                if cert_tx:
                    channel_txo = cert_tx.outputs[certificate['nout']]
                    claim_result['signing_channel'] = {
                        'name': channel_txo.claim_name,
                        'claim_id': channel_txo.claim_id,
                        'value': channel_txo.claim
                    }
                    claim_result['is_channel_signature_valid'] = claim_result['signature_is_valid']

        if 'amount' in claim_result:
            claim_result['amount'] = dewies_to_lbc(claim_result['amount'])
            claim_result['effective_amount'] = dewies_to_lbc(claim_result['effective_amount'])
            claim_result['supports'] = [
                {'txid': txid, 'nout': nout, 'amount': dewies_to_lbc(amount)}
                for (txid, nout, amount) in claim_result['supports']
            ]

        claim_result['height'] = claim_result.get('height', -1) or -1
        claim_result['permanent_url'] = f"lbry://{claim_result['name']}#{claim_result['claim_id']}"

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

    async def iter_channel_claims_pages(self, queries, claim_positions, claim_names, certificate,
                                  page_size=10):
        # lbryum server returns a dict of {claim_id: (name, claim_height)}
        # first, sort the claims by block height (and by claim id int value within a block).

        # map the sorted claims into getclaimsbyids queries of query_size claim ids each

        # send the batched queries to lbryum server and iteratively validate and parse
        # the results, yield a page of results at a time.

        # these results can include those where `signature_is_valid` is False. if they are skipped,
        # page indexing becomes tricky, as the number of results isn't known until after having
        # processed them.
        # TODO: fix ^ in lbrynet.schema

        async def iter_validate_channel_claims():
            formatted_claims = []
            for claim_ids in queries:
                batch_result = await self.network.get_claims_by_ids(*claim_ids)
                for claim_id in claim_ids:
                    claim = batch_result[claim_id]
                    if claim['name'] == claim_names[claim_id]:
                        formatted_claim = await self.parse_and_validate_claim_result(claim, certificate)
                        formatted_claim['absolute_channel_position'] = claim_positions[
                            claim['claim_id']]
                        formatted_claims.append(formatted_claim)
                    else:
                        log.warning("ignoring claim with name mismatch %s %s", claim['name'],
                                    claim['claim_id'])
                return formatted_claims

        results = []

        for claim in await iter_validate_channel_claims():
            results.append(claim)

            # if there is a full page of results, yield it
            if len(results) and len(results) % page_size == 0:
                return results[-page_size:]

        return results

    async def get_channel_claims_page(self, channel_claim_infos, certificate, page, page_size=10):
        page = page or 0
        page_size = max(page_size, 1)
        if page_size > 500:
            raise Exception("page size above maximum allowed")
        start_position = (page - 1) * page_size
        queries, names, claim_positions = self.prepare_claim_queries(start_position, page_size,
                                                                     channel_claim_infos)
        upper_bound = len(claim_positions)
        if not page:
            return None, upper_bound
        if start_position > upper_bound:
            raise IndexError("claim %i greater than max %i" % (start_position, upper_bound))
        page_generator = await self.iter_channel_claims_pages(queries, claim_positions, names,
                                                              certificate, page_size=page_size)
        return page_generator, upper_bound


def _verify_proof(name, claim_trie_root, result, ledger):
    """
    Verify proof for name claim
    """
    support_amount = sum([amt for (stxid, snout, amt) in result['supports']])

    def _build_response(name, tx, nOut):
        output = tx.outputs[nOut]
        r = {
            'name': name,
            'value': hexlify(output.script.values['claim']),
            'claim_id': output.claim_id,
            'txid': tx.id,
            'nout': nOut,
            'amount': output.amount,
            'effective_amount': output.amount + support_amount,
            'height': result['height'],
            'depth': result['depth'],
            'claim_sequence': result['claim_sequence'],
            'address': output.get_address(ledger),
            'valid_at_height': result['valid_at_height'],
            'supports': result['supports']
        }
        return r

    def _parse_proof_result(name, result):
        if 'txhash' in result['proof'] and 'nOut' in result['proof']:
            if 'transaction' in result:
                tx = ledger.transaction_class(raw=unhexlify(result['transaction']))
                nOut = result['proof']['nOut']
                if result['proof']['txhash'] == tx.id:
                    if 0 <= nOut < len(tx.outputs):
                        if tx.outputs[nOut].claim_name == name:
                            return _build_response(name, tx, nOut)
                        return {'error': 'name in proof did not match requested name'}
                    outputs = len(tx['outputs'])
                    return {'error': 'invalid nOut: %d (let(outputs): %d' % (nOut, outputs)}
                return {'error': "computed txid did not match given transaction: %s vs %s" %
                                 (tx.id, result['proof']['txhash'])
                        }
            return {'error': "didn't receive a transaction with the proof"}
        return {'error': 'name is not claimed'}

    if 'proof' in result:
        name = result.get('name', name)
        proof_name = result.get('normalized_name', name)
        try:
            verify_proof(result['proof'], claim_trie_root, proof_name)
        except InvalidProofError:
            return {'error': "Proof was invalid"}
        return _parse_proof_result(name, result)
    else:
        return {'error': "proof not in result"}


def validate_claim_signature_and_get_channel_name(claim_result, certificate_claim, ledger,
                                                  claim_tx=None, cert_tx=None):
    valid_signature = False
    if cert_tx and certificate_claim and claim_tx and claim_result:
        try:
            valid_signature = claim_tx.outputs[claim_result['nout']].is_signed_by(
                cert_tx.outputs[certificate_claim['nout']], ledger
            )
        except InvalidSignature:
            pass
        if not valid_signature:
            log.warning("lbry://%s#%s has an invalid signature",
                        claim_result['name'], claim_result['claim_id'])
    return valid_signature


# TODO: The following came from code handling lbryum results. Now that it's all in one place a refactor should unify it.
def _decode_claim_result(claim):
    if 'decoded_claim' in claim:
        return claim
    if 'value' not in claim:
        log.warning('Got an invalid claim while parsing, please report: %s', claim)
        claim['protobuf'] = None
        claim['value'] = None
        backend_message = ' SDK message: ' + claim.get('error', '')
        claim['error'] = "Failed to parse: missing value." + backend_message
        return claim
    try:
        if not isinstance(claim['value'], Claim):
            claim['value'] = Claim.from_bytes(unhexlify(claim['value']))
        claim['protobuf'] = hexlify(claim['value'].to_bytes())
        claim['decoded_claim'] = True
    except DecodeError:
        claim['decoded_claim'] = False
        claim['protobuf'] = claim['value']
        claim['value'] = None
    return claim


def _handle_claim_result(results, uri):
    if not results:
        raise UnknownURI(uri)

    if 'error' in results:
        if results['error'] in ['name is not claimed', 'claim not found']:
            if 'claim_id' in results:
                raise UnknownClaimID(results['claim_id'])
            if 'name' in results:
                raise UnknownNameError(results['name'])
            if 'uri' in results:
                raise UnknownURI(results['uri'])
            if 'outpoint' in results:
                raise UnknownOutpoint(results['outpoint'])
        raise Exception(results['error'])
    if not {'value', 'claim', 'certificate'}.intersection(results.keys()):
        raise Exception(f'result in unexpected format:{results}')
    return results


def pick_winner_from_channel_path_collision(claims_in_channel):
    # we should be doing this by effective amount so we pick the controlling claim, however changing the resolved
    # claim triggers another issue where 2 claims cant be saved for the same file. This code picks the oldest, so it
    # stays the same. Using effective amount would change the resolved claims for a channel path on takeovers,
    # potentially triggering that.
    winner = {}
    for claim in claims_in_channel:
        if not winner or claim['height'] < winner['height'] or \
                (claim['height'] == winner['height'] and claim['nout'] < winner['nout']):
            winner = claim if claim['signature_is_valid'] else winner
    return winner or None
