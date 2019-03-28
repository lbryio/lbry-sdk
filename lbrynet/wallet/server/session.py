import math
import unicodedata as uda
from binascii import unhexlify, hexlify

from torba.rpc.jsonrpc import RPCError
from torba.server.hash import hash_to_hex_str
from torba.server.session import ElectrumX
from torba.server import util

from lbrynet.schema.uri import parse_lbry_uri, CLAIM_ID_MAX_LENGTH, URIParseError
from lbrynet.wallet.server.block_processor import LBRYBlockProcessor
from lbrynet.wallet.server.db import LBRYDB


class LBRYElectrumX(ElectrumX):
    PROTOCOL_MIN = (0, 0)  # temporary, for supporting 0.10 protocol
    max_errors = math.inf  # don't disconnect people for errors! let them happen...

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # fixme: this is a rebase hack, we need to go through ChainState instead later
        self.daemon = self.session_mgr.daemon
        self.bp: LBRYBlockProcessor = self.session_mgr.bp
        self.db: LBRYDB = self.bp.db
        # fixme: lbryum specific subscribe
        self.subscribe_height = False

    def set_request_handlers(self, ptuple):
        super().set_request_handlers(ptuple)
        handlers = {
            'blockchain.transaction.get_height': self.transaction_get_height,
            'blockchain.claimtrie.getclaimbyid': self.claimtrie_getclaimbyid,
            'blockchain.claimtrie.getclaimsforname': self.claimtrie_getclaimsforname,
            'blockchain.claimtrie.getclaimsbyids': self.claimtrie_getclaimsbyids,
            'blockchain.claimtrie.getvalue': self.claimtrie_getvalue,
            'blockchain.claimtrie.getnthclaimforname': self.claimtrie_getnthclaimforname,
            'blockchain.claimtrie.getclaimsintx': self.claimtrie_getclaimsintx,
            'blockchain.claimtrie.getclaimssignedby': self.claimtrie_getclaimssignedby,
            'blockchain.claimtrie.getclaimssignedbynthtoname': self.claimtrie_getclaimssignedbynthtoname,
            'blockchain.claimtrie.getvalueforuri': self.claimtrie_getvalueforuri,
            'blockchain.claimtrie.getvaluesforuris': self.claimtrie_getvalueforuris,
            'blockchain.claimtrie.getclaimssignedbyid': self.claimtrie_getclaimssignedbyid,
            'blockchain.block.get_server_height': self.get_server_height,
        }
        # fixme: methods we use but shouldnt be using anymore. To be removed when torba goes out
        handlers.update({
            'blockchain.numblocks.subscribe': self.numblocks_subscribe,
            'blockchain.utxo.get_address': self.utxo_get_address,
            'blockchain.transaction.broadcast':
                self.transaction_broadcast_1_0,
            'blockchain.transaction.get': self.transaction_get,
        })
        self.request_handlers.update(handlers)

    async def utxo_get_address(self, tx_hash, index):
        # fixme: lbryum
        # Used only for electrum client command-line requests.  We no
        # longer index by address, so need to request the raw
        # transaction.  So it works for any TXO not just UTXOs.
        self.assert_tx_hash(tx_hash)
        try:
            index = int(index)
            if index < 0:
                raise ValueError
        except ValueError:
            raise RPCError(1, "index has to be >= 0 and integer")
        raw_tx = await self.daemon_request('getrawtransaction', tx_hash)
        if not raw_tx:
            return None
        raw_tx = util.hex_to_bytes(raw_tx)
        tx = self.coin.DESERIALIZER(raw_tx).read_tx()
        if index >= len(tx.outputs):
            return None
        return self.coin.address_from_script(tx.outputs[index].pk_script)

    async def transaction_broadcast_1_0(self, raw_tx):
        # fixme: lbryum
        # An ugly API: current Electrum clients only pass the raw
        # transaction in hex and expect error messages to be returned in
        # the result field.  And the server shouldn't be doing the client's
        # user interface job here.
        try:
            return await self.transaction_broadcast(raw_tx)
        except RPCError as e:
            return e.message

    async def numblocks_subscribe(self):
        # fixme workaround for lbryum
        '''Subscribe to get height of new blocks.'''
        self.subscribe_height = True
        return self.bp.height

    async def notify(self, height, touched):
        # fixme workaround for lbryum
        await super().notify(height, touched)
        if self.subscribe_height and height != self.notified_height:
            self.send_notification('blockchain.numblocks.subscribe', (height,))

    async def transaction_get(self, tx_hash, verbose=False):
        # fixme: workaround for lbryum sending the height instead of True/False.
        # fixme: lbryum_server ignored that and always used False, but this is out of spec
        if verbose not in (True, False):
            verbose = False
        return await self.daemon_request('getrawtransaction', tx_hash, verbose)

    async def get_server_height(self):
        return self.bp.height

    async def transaction_get_height(self, tx_hash):
        self.assert_tx_hash(tx_hash)
        transaction_info = await self.daemon.getrawtransaction(tx_hash, True)
        if transaction_info and 'hex' in transaction_info and 'confirmations' in transaction_info:
            # an unconfirmed transaction from lbrycrdd will not have a 'confirmations' field
            height = self.db.db_height
            height = height - transaction_info['confirmations']
            return height
        elif transaction_info and 'hex' in transaction_info:
            return -1
        return None

    async def claimtrie_getclaimssignedby(self, name):
        winning_claim = await self.daemon.getvalueforname(name)
        if winning_claim:
            return await self.claimtrie_getclaimssignedbyid(winning_claim['claimId'])

    async def claimtrie_getclaimssignedbyid(self, certificate_id):
        claim_ids = self.get_claim_ids_signed_by(certificate_id)
        return await self.batched_formatted_claims_from_daemon(claim_ids)

    def claimtrie_getclaimssignedbyidminimal(self, certificate_id):
        claim_ids = self.get_claim_ids_signed_by(certificate_id)
        ret = []
        for claim_id in claim_ids:
            raw_claim_id = unhexlify(claim_id)[::-1]
            info = self.db.get_claim_info(raw_claim_id)
            if info:
                ret.append({
                    'claim_id': claim_id,
                    'height': info.height,
                    'name': info.name.decode()
                })
        return ret

    def get_claim_ids_signed_by(self, certificate_id):
        raw_certificate_id = unhexlify(certificate_id)[::-1]
        raw_claim_ids = self.db.get_signed_claim_ids_by_cert_id(raw_certificate_id)
        return list(map(hash_to_hex_str, raw_claim_ids))

    async def claimtrie_getclaimssignedbynthtoname(self, name, n):
        claim = self.claimtrie_getnthclaimforname(name, n)
        if claim and 'claim_id' in claim:
            return await self.claimtrie_getclaimssignedbyid(hash_to_hex_str(claim['claim_id']))

    async def claimtrie_getclaimsintx(self, txid):
        # TODO: this needs further discussion.
        # Code on lbryum-server is wrong and we need to gather what we clearly expect from this command
        claim_ids = [claim['claimId'] for claim in (await self.daemon.getclaimsfortx(txid)) if 'claimId' in claim]
        return await self.batched_formatted_claims_from_daemon(claim_ids)

    async def claimtrie_getvalue(self, name, block_hash=None):
        proof = await self.daemon.getnameproof(name, block_hash)
        result = {'proof': proof, 'supports': []}

        if proof_has_winning_claim(proof):
            tx_hash, nout = proof['txhash'], int(proof['nOut'])
            transaction_info = await self.daemon.getrawtransaction(tx_hash, True)
            result['transaction'] = transaction_info['hex']  # should have never included this (or the call to get it)
            raw_claim_id = self.db.get_claim_id_from_outpoint(unhexlify(tx_hash)[::-1], nout)
            claim_id = hexlify(raw_claim_id[::-1]).decode()
            claim = await self.claimtrie_getclaimbyid(claim_id)
            result.update(claim)

        return result

    async def claimtrie_getnthclaimforname(self, name, n):
        n = int(n)
        result = await self.claimtrie_getclaimsforname(name)
        if 'claims' in result and len(result['claims']) > n >= 0:
            # TODO: revist this after lbrycrd_#209 to see if we can sort by claim_sequence at this point
            result['claims'].sort(key=lambda c: (int(c['height']), int(c['nout'])))
            result['claims'][n]['claim_sequence'] = n
            return result['claims'][n]

    async def claimtrie_getpartialmatch(self, name, part):
        result = await self.claimtrie_getclaimsforname(name)
        if 'claims' in result:
            return next(filter(lambda x: x['claim_id'].starts_with(part), result['claims']), None)

    async def claimtrie_getclaimsforname(self, name):
        claims = await self.daemon.getclaimsforname(name)
        if claims:
            claims['claims'] = [self.format_claim_from_daemon(claim, name) for claim in claims['claims']]
            claims['supports_without_claims'] = claims['supports without claims']
            del claims['supports without claims']
            claims['last_takeover_height'] = claims['nLastTakeoverHeight']
            del claims['nLastTakeoverHeight']
            return claims
        return {}

    async def batched_formatted_claims_from_daemon(self, claim_ids):
        claims = await self.daemon.getclaimsbyids(claim_ids)
        result = []
        for claim in claims:
            if claim and claim.get('value'):
                result.append(self.format_claim_from_daemon(claim))
        return result

    def format_claim_from_daemon(self, claim, name=None):
        """Changes the returned claim data to the format expected by lbrynet and adds missing fields."""

        if not claim:
            return {}

        # this ISO-8859 nonsense stems from a nasty form of encoding extended characters in lbrycrd
        # it will be fixed after the lbrycrd upstream merge to v17 is done
        # it originated as a fear of terminals not supporting unicode. alas, they all do

        if 'name' in claim:
            name = claim['name'].encode('ISO-8859-1').decode()
        claim_id = claim['claimId']
        raw_claim_id = unhexlify(claim_id)[::-1]
        info = self.db.get_claim_info(raw_claim_id)
        if not info:
            #  raise RPCError("Lbrycrd has {} but not lbryumx, please submit a bug report.".format(claim_id))
            return {}
        address = info.address.decode()
        supports = self.format_supports_from_daemon(claim.get('supports', []))

        amount = get_from_possible_keys(claim, 'amount', 'nAmount')
        height = get_from_possible_keys(claim, 'height', 'nHeight')
        effective_amount = get_from_possible_keys(claim, 'effective amount', 'nEffectiveAmount')
        valid_at_height = get_from_possible_keys(claim, 'valid at height', 'nValidAtHeight')
        canonical_url = self.construct_canonical_url(name, claim_id)

        result = {
            "name": name,
            "claim_id": claim['claimId'],
            "txid": claim['txid'],
            "nout": claim['n'],
            "amount": amount,
            "depth": self.db.db_height - height + 1,
            "height": height,
            "value": hexlify(claim['value'].encode('ISO-8859-1')).decode(),
            "address": address,  # from index
            "supports": supports,
            "effective_amount": effective_amount,
            "valid_at_height": valid_at_height,
            "canonical_url": canonical_url,
        }
        if 'claim_sequence' in claim:
            # TODO: ensure that lbrycrd #209 fills in this value
            result['claim_sequence'] = claim['claim_sequence']
        else:
            result['claim_sequence'] = -1
        if 'normalized_name' in claim:
            result['normalized_name'] = claim['normalized_name'].encode('ISO-8859-1').decode()
        return result

    def format_supports_from_daemon(self, supports):
        return [[support['txid'], support['n'], get_from_possible_keys(support, 'amount', 'nAmount')] for
                 support in supports]

    async def claimtrie_getclaimbyid(self, claim_id):
        self.assert_claim_id(claim_id)
        claim = await self.daemon.getclaimbyid(claim_id)
        return self.format_claim_from_daemon(claim)

    async def claimtrie_getclaimsbyids(self, *claim_ids):
        claims = await self.batched_formatted_claims_from_daemon(claim_ids)
        return dict(zip(claim_ids, claims))

    def assert_tx_hash(self, value):
        '''Raise an RPCError if the value is not a valid transaction
        hash.'''
        try:
            if len(util.hex_to_bytes(value)) == 32:
                return
        except Exception:
            pass
        raise RPCError(1, f'{value} should be a transaction hash')

    def assert_claim_id(self, value):
        '''Raise an RPCError if the value is not a valid claim id
        hash.'''
        try:
            if len(util.hex_to_bytes(value)) == 20:
                return
        except Exception:
            pass
        raise RPCError(1, f'{value} should be a claim id hash')

    def normalize_name(self, name):
        # this is designed to match lbrycrd; change it here if it changes there
        return uda.normalize('NFD', name).casefold()

    def claim_matches_name(self, claim, name):
        if not name:
            return False
        if 'normalized_name' in claim:
            return self.normalize_name(name) == claim['normalized_name']
        return name == claim['name']

    def construct_canonical_url(self, claim_name, claim_id):
        for i in range(len(claim_id)):
            full_id = self.db.get_full_claim_id_from_canonical(claim_name, claim_id[:i+1]).decode()
            if full_id == claim_id:
                return "{}#{}".format(claim_name, claim_id[:i+1])

    async def claimtrie_getvalueforuri(self, block_hash, uri, known_certificates=None):
        # TODO: this thing is huge, refactor
        CLAIM_ID = "claim_id"
        WINNING = "winning"
        SEQUENCE = "sequence"
        uri = uri
        block_hash = block_hash
        try:
            parsed_uri = parse_lbry_uri(uri)
        except URIParseError as err:
            return {'error': err.message}
        result = {}

        if parsed_uri.contains_channel:
            certificate = None

            # TODO: this is also done on the else, refactor
            if parsed_uri.claim_id:
                full_claim_id = parsed_uri.claim_id
                if len(parsed_uri.claim_id) < CLAIM_ID_MAX_LENGTH:
                    full_claim_id = self.db.get_full_claim_id_from_canonical(
                        parsed_uri.channel_name, parsed_uri.claim_id
                    ).decode()
                    # certificate_info = self.claimtrie_getpartialmatch(parsed_uri.name, parsed_uri.claim_id)

                certificate_info = await self.claimtrie_getclaimbyid(full_claim_id)
                if certificate_info and self.claim_matches_name(certificate_info, parsed_uri.name):
                    certificate = {'resolution_type': CLAIM_ID, 'result': certificate_info}
            elif parsed_uri.claim_sequence:
                certificate_info = await self.claimtrie_getnthclaimforname(parsed_uri.name, parsed_uri.claim_sequence)
                if certificate_info:
                    certificate = {'resolution_type': SEQUENCE, 'result': certificate_info}
            else:
                certificate_info = await self.claimtrie_getvalue(parsed_uri.name, block_hash)
                if certificate_info:
                    certificate = {'resolution_type': WINNING, 'result': certificate_info}

            if certificate and 'claim_id' not in certificate['result']:
                return result

            if certificate:
                result['certificate'] = certificate
                channel_id = certificate['result']['claim_id']
                claims_in_channel = self.claimtrie_getclaimssignedbyidminimal(channel_id)
                if not parsed_uri.path:
                    result['unverified_claims_in_channel'] = {claim['claim_id']: (claim['name'], claim['height'])
                                                              for claim in claims_in_channel}
                else:
                    # making an assumption that there aren't case conflicts on an existing channel
                    norm_path = self.normalize_name(parsed_uri.path)
                    result['unverified_claims_for_name'] = {claim['claim_id']: (claim['name'], claim['height'])
                                                            for claim in claims_in_channel
                                                            if self.normalize_name(claim['name']) == norm_path}

        else:
            claim = None
            if parsed_uri.claim_id:
                full_claim_id = parsed_uri.claim_id
                if len(parsed_uri.claim_id) < CLAIM_ID_MAX_LENGTH:
                    full_claim_id = self.db.get_full_claim_id_from_canonical(
                        parsed_uri.claim_name, parsed_uri.claim_id
                    ).decode()
                    # claim_info = self.claimtrie_getpartialmatch(parsed_uri.name, parsed_uri.claim_id)

                claim_info = await self.claimtrie_getclaimbyid(full_claim_id)
                if claim_info and self.claim_matches_name(claim_info, parsed_uri.name):
                    claim = {'resolution_type': CLAIM_ID, 'result': claim_info}
            elif parsed_uri.claim_sequence:
                claim_info = await self.claimtrie_getnthclaimforname(parsed_uri.name, parsed_uri.claim_sequence)
                if claim_info:
                    claim = {'resolution_type': SEQUENCE, 'result': claim_info}
            else:
                claim_info = await self.claimtrie_getvalue(parsed_uri.name, block_hash)
                if claim_info:
                    claim = {'resolution_type': WINNING, 'result': claim_info}

            if (claim and
                    # is not an unclaimed winning name
                    (claim['resolution_type'] != WINNING or proof_has_winning_claim(claim['result']['proof']))):
                raw_claim_id = unhexlify(claim['result']['claim_id'])[::-1]
                raw_certificate_id = self.db.get_claim_info(raw_claim_id).cert_id
                if raw_certificate_id:
                    certificate_id = hash_to_hex_str(raw_certificate_id)
                    certificate = await self.claimtrie_getclaimbyid(certificate_id)
                    if certificate:
                        certificate = {'resolution_type': CLAIM_ID,
                                       'result': certificate}
                        result['certificate'] = certificate
                result['claim'] = claim

        return result

    async def claimtrie_getvalueforuris(self, block_hash, *uris):
        MAX_BATCH_URIS = 500
        if len(uris) > MAX_BATCH_URIS:
            raise Exception("Exceeds max batch uris of {}".format(MAX_BATCH_URIS))

        return {uri: await self.claimtrie_getvalueforuri(block_hash, uri) for uri in uris}

        # TODO: get it all concurrently when lbrycrd pending changes goes into a stable release
        #async def getvalue(uri):
        #    value = await self.claimtrie_getvalueforuri(block_hash, uri)
        #    return uri, value,
        #return dict([await asyncio.gather(*tuple(getvalue(uri) for uri in uris))][0])


def proof_has_winning_claim(proof):
    return {'txhash', 'nOut'}.issubset(proof.keys())


def get_from_possible_keys(dictionary, *keys):
    for key in keys:
        if key in dictionary:
            return dictionary[key]
