import logging
import struct

from six import int2byte
from binascii import unhexlify

from twisted.internet import defer

from lbrynet.core.Error import UnknownNameError, UnknownClaimID, UnknownURI
from .resolve import format_amount_value, _get_permanent_url, validate_claim_signature_and_get_channel_name
from .resolve import _verify_proof, _handle_claim_result
from lbryschema.decode import smart_decode
from lbryschema.error import URIParseError, DecodeError
from lbryschema.uri import parse_lbry_uri
from torba.baseledger import BaseLedger
from torba.baseheader import BaseHeaders, _ArithUint256
from torba.util import int_to_hex, rev_hex, hash_encode

from .account import Account
from .network import Network
from .database import WalletDatabase
from .transaction import Transaction


log = logging.getLogger(__name__)


class Headers(BaseHeaders):

    header_size = 112

    @staticmethod
    def _serialize(header):
        return b''.join([
            int_to_hex(header['version'], 4),
            rev_hex(header['prev_block_hash']),
            rev_hex(header['merkle_root']),
            rev_hex(header['claim_trie_root']),
            int_to_hex(int(header['timestamp']), 4),
            int_to_hex(int(header['bits']), 4),
            int_to_hex(int(header['nonce']), 4)
        ])

    @staticmethod
    def _deserialize(height, header):
        version, = struct.unpack('<I', header[:4])
        timestamp, bits, nonce = struct.unpack('<III', header[100:112])
        return {
            'version': version,
            'prev_block_hash': hash_encode(header[4:36]),
            'merkle_root': hash_encode(header[36:68]),
            'claim_trie_root': hash_encode(header[68:100]),
            'timestamp': timestamp,
            'bits': bits,
            'nonce': nonce,
            'block_height': height,
        }

    @property
    def claim_trie_root(self, height=None):
        height = self.height if height is None else height
        return self[height]['claim_trie_root']

    def _calculate_next_work_required(self, height, first, last):
        """ See: lbrycrd/src/lbry.cpp """

        if height == 0:
            return self.ledger.genesis_bits, self.ledger.max_target

        if self.verify_bits_to_target:
            bits = last['bits']
            bitsN = (bits >> 24) & 0xff
            assert 0x03 <= bitsN <= 0x1f, \
                "First part of bits should be in [0x03, 0x1d], but it was {}".format(hex(bitsN))
            bitsBase = bits & 0xffffff
            assert 0x8000 <= bitsBase <= 0x7fffff, \
                "Second part of bits should be in [0x8000, 0x7fffff] but it was {}".format(bitsBase)

        # new target
        retargetTimespan = self.ledger.target_timespan
        nActualTimespan = last['timestamp'] - first['timestamp']

        nModulatedTimespan = retargetTimespan + (nActualTimespan - retargetTimespan) // 8

        nMinTimespan = retargetTimespan - (retargetTimespan // 8)
        nMaxTimespan = retargetTimespan + (retargetTimespan // 2)

        # Limit adjustment step
        if nModulatedTimespan < nMinTimespan:
            nModulatedTimespan = nMinTimespan
        elif nModulatedTimespan > nMaxTimespan:
            nModulatedTimespan = nMaxTimespan

        # Retarget
        bnPowLimit = _ArithUint256(self.ledger.max_target)
        bnNew = _ArithUint256.SetCompact(last['bits'])
        bnNew *= nModulatedTimespan
        bnNew //= nModulatedTimespan
        if bnNew > bnPowLimit:
            bnNew = bnPowLimit

        return bnNew.GetCompact(), bnNew._value


class MainNetLedger(BaseLedger):
    name = 'LBRY Credits'
    symbol = 'LBC'
    network_name = 'mainnet'

    account_class = Account
    database_class = WalletDatabase
    headers_class = Headers
    network_class = Network
    transaction_class = Transaction

    secret_prefix = int2byte(0x1c)
    pubkey_address_prefix = int2byte(0x55)
    script_address_prefix = int2byte(0x7a)
    extended_public_key_prefix = unhexlify('0488b21e')
    extended_private_key_prefix = unhexlify('0488ade4')

    max_target = 0x0000ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = '9c89283ba0f3227f6c03b70216b9f665f0118d5e0fa729cedf4fb34d6a34f463'
    genesis_bits = 0x1f00ffff
    target_timespan = 150

    default_fee_per_byte = 50
    default_fee_per_name_char = 200000

    def __init__(self, *args, **kwargs):
        super(MainNetLedger, self).__init__(*args, **kwargs)
        self.fee_per_name_char = self.config.get('fee_per_name_char', self.default_fee_per_name_char)

    def get_transaction_base_fee(self, tx):
        """ Fee for the transaction header and all outputs; without inputs. """
        return max(
            super(MainNetLedger, self).get_transaction_base_fee(tx),
            self.get_transaction_claim_name_fee(tx)
        )

    def get_transaction_claim_name_fee(self, tx):
        fee = 0
        for output in tx.outputs:
            if output.script.is_claim_name:
                fee += len(output.script.values['claim_name']) * self.fee_per_name_char
        return fee

    @defer.inlineCallbacks
    def resolve(self, page, page_size, *uris):
        for uri in uris:
            try:
                parse_lbry_uri(uri)
            except URIParseError as err:
                defer.returnValue({'error': err.message})
        resolutions = yield self.network.get_values_for_uris(self.headers.hash(), *uris)
        defer.returnValue(self._handle_resolutions(resolutions, uris, page, page_size))

    def _handle_resolutions(self, resolutions, requested_uris, page, page_size):
        results = {}
        for uri in requested_uris:
            resolution = (resolutions or {}).get(uri, {})
            if resolution:
                try:
                    results[uri] = _handle_claim_result(
                        self._handle_resolve_uri_response(uri, resolution, page, page_size)
                    )
                except (UnknownNameError, UnknownClaimID, UnknownURI) as err:
                    results[uri] = {'error': err.message}
        return results


    def _handle_resolve_uri_response(self, uri, resolution, page=0, page_size=10, raw=False):
        result = {}
        claim_trie_root = self.headers.claim_trie_root
        parsed_uri = parse_lbry_uri(uri)
        # parse an included certificate
        if 'certificate' in resolution:
            certificate_response = resolution['certificate']['result']
            certificate_resolution_type = resolution['certificate']['resolution_type']
            if certificate_resolution_type == "winning" and certificate_response:
                if 'height' in certificate_response:
                    height = certificate_response['height']
                    depth = self.headers.height - height
                    certificate_result = _verify_proof(self, parsed_uri.name,
                                                       claim_trie_root,
                                                       certificate_response,
                                                       height, depth,
                                                       transaction_class=self.transaction_class)
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
                    depth = self.headers.height - height
                    claim_result = _verify_proof(self, parsed_uri.name,
                                                          claim_trie_root,
                                                          claim_response,
                                                          height, depth)
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

            channel_info = self.get_channel_claims_page(unverified_claims_for_name,
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
            channel_info = self.get_channel_claims_page(ids_to_check, result['certificate'],
                                                        page=page, page_size=page_size)
            claims_in_channel, upper_bound = channel_info

            if claims_in_channel:
                result['claims_in_channel'] = claims_in_channel
        elif 'error' not in result:
            result['error'] = "claim not found"
            result['success'] = False
            result['uri'] = str(parsed_uri)

        return result

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
                    certificate = self.getclaimbyid(decoded.certificate_id)
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

        block_sorted_infos = sorted(channel_claim_infos.iteritems(), key=lambda x: int(x[1][1]))
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

        def iter_validate_channel_claims():
            for claim_ids in queries:
                log.info(claim_ids)
                batch_result = yield self.network.get_claims_by_ids(*claim_ids)
                for claim_id in claim_ids:
                    claim = batch_result[claim_id]
                    if claim['name'] == claim_names[claim_id]:
                        formatted_claim = self.parse_and_validate_claim_result(claim, certificate)
                        formatted_claim['absolute_channel_position'] = claim_positions[
                            claim['claim_id']]
                        yield formatted_claim
                    else:
                        log.warning("ignoring claim with name mismatch %s %s", claim['name'],
                                    claim['claim_id'])

        yielded_page = False
        results = []
        for claim in iter_validate_channel_claims():
            results.append(claim)

            # if there is a full page of results, yield it
            if len(results) and len(results) % page_size == 0:
                yield results[-page_size:]
                yielded_page = True

        # if we didn't get a full page of results, yield what results we did get
        if not yielded_page:
            yield results

    def get_channel_claims_page(self, channel_claim_infos, certificate, page, page_size=10):
        page = page or 0
        page_size = max(page_size, 1)
        if page_size > 500:
            raise Exception("page size above maximum allowed")
        start_position = (page - 1) * page_size
        queries, names, claim_positions = self.prepare_claim_queries(start_position, page_size,
                                                                     channel_claim_infos)
        page_generator = self.iter_channel_claims_pages(queries, claim_positions, names,
                                                        certificate, page_size=page_size)
        upper_bound = len(claim_positions)
        if not page:
            return None, upper_bound
        if start_position > upper_bound:
            raise IndexError("claim %i greater than max %i" % (start_position, upper_bound))
        return next(page_generator), upper_bound

    @defer.inlineCallbacks
    def start(self):
        yield super(MainNetLedger, self).start()
        yield defer.DeferredList([
            a.maybe_migrate_certificates() for a in self.accounts
        ])


class TestNetLedger(MainNetLedger):
    network_name = 'testnet'
    pubkey_address_prefix = int2byte(111)
    script_address_prefix = int2byte(196)
    extended_public_key_prefix = unhexlify('043587cf')
    extended_private_key_prefix = unhexlify('04358394')


class UnverifiedHeaders(Headers):
    verify_bits_to_target = False


class RegTestLedger(MainNetLedger):
    network_name = 'regtest'
    headers_class = UnverifiedHeaders
    pubkey_address_prefix = int2byte(111)
    script_address_prefix = int2byte(196)
    extended_public_key_prefix = unhexlify('043587cf')
    extended_private_key_prefix = unhexlify('04358394')

    max_target = 0x7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = '6e3fcf1299d4ec5d79c3a4c91d624a4acf9e2e173d95a1a0504f677669687556'
    genesis_bits = 0x207fffff
    target_timespan = 1
