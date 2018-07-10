import binascii
import unittest

from lbrynet.wallet.claim_proofs import get_hash_for_outpoint, verify_proof
from lbryschema.hashing import double_sha256


class ClaimProofsTestCase(unittest.TestCase):
    def test_verify_proof(self):
        claim1_name = 97  # 'a'
        claim1_txid = 'bd9fa7ffd57d810d4ce14de76beea29d847b8ac34e8e536802534ecb1ca43b68'
        claim1_outpoint = 0
        claim1_height = 10
        claim1_node_hash = get_hash_for_outpoint(
            binascii.unhexlify(claim1_txid)[::-1], claim1_outpoint, claim1_height)

        claim2_name = 98  # 'b'
        claim2_txid = 'ad9fa7ffd57d810d4ce14de76beea29d847b8ac34e8e536802534ecb1ca43b68'
        claim2_outpoint = 1
        claim2_height = 5
        claim2_node_hash = get_hash_for_outpoint(
            binascii.unhexlify(claim2_txid)[::-1], claim2_outpoint, claim2_height)
        to_hash1 = claim1_node_hash
        hash1 = double_sha256(to_hash1)
        to_hash2 = chr(claim1_name) + hash1 + chr(claim2_name) + claim2_node_hash

        root_hash = double_sha256(to_hash2)

        proof = {
            'last takeover height': claim1_height, 'txhash': claim1_txid, 'nOut': claim1_outpoint,
            'nodes': [
                {'children': [
                    {'character': 97},
                    {
                        'character': 98,
                        'nodeHash': claim2_node_hash[::-1].encode('hex')
                    }
                ]},
                {'children': []},
            ]
        }
        out = verify_proof(proof, root_hash[::-1].encode('hex'), 'a')
        self.assertEqual(out, True)
