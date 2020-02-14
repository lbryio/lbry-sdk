import unittest
from binascii import hexlify, unhexlify

from lbry.wallet.claim_proofs import get_hash_for_outpoint, is_proof_valid, verify_proof_old
from lbry.crypto.hash import double_sha256


class TestVerifyProof(unittest.TestCase):
    def current_algo(self):
        # nameclaimroot from block 716110
        claimtrie_root_hash = "09b4bb94d26e256111c176d744cc26e5dc13bc00f24c3b14bab414aaafd92ee3"

        # winning claim for 'lbry' at block 716110
        claim = {
            "txId": "a2c060a316bd56b3bc8f3d9d6997bf03f66625cda51347465ba88ccfac9ef3d7",
            "n": 0,
            "lastTakeoverHeight": 608276,
        }

        # proof for the above claim at block 716110
        proof = {
            "pairs": [
                {"odd": False, "hash": "5685300f64d691f1e47115c0e5fe9690e3fa3128bbf5e940db0aedb6270aef8d"},
                {"odd": False, "hash": "64c90cc399288e2c4404cb30344ba1ce575e2598bef2e7971633f50898122cb8"},
                {"odd": False, "hash": "7b777bed2d14e443f2323f7a7b3cd5d1072419c3bb4113441706455dbd119981"},
                {"odd": False, "hash": "66fc7f9a0920e7f8ece40642b0d29493db2489ca9b2e78da33cbb56ca3104745"},
                {"odd": False, "hash": "5172bcdbed3c2b4be5761375538ff0773e53d894fc280c7061624c02bf7ab08d"},
                {"odd": False, "hash": "4e5692b23763c4e1d071cb2dd63270c2c63023f071cb31f37944f8657c104dc5"},
                {"odd": False, "hash": "1fa2806b0ea26a719bb972af27e68beee2548402752713d9d3b52c1688dd6222"},
                {"odd": True, "hash": "144ab44b808d36e98daf698ab07b7631a10bd7db5eef3c1d9d25291036a67463"},
                {"odd": False, "hash": "183789ee0dc723b3b3afcfe421b3ff723c99862520429e1cc7e3e7234c304fc5"},
                {"odd": False, "hash": "701c7848b9cb33a68f84c164b0bec18fc6e5dfd8b09041e3b66cb26501b2b8e6"},
                {"odd": False, "hash": "fdaefcbb0fcf0e12063ee2f32d391c9e5324707c9c62a35a81f90d0d09c8770e"},
                {"odd": True, "hash": "df6828f2c8c6168d91f4d0ea898ddef42d067403fe30425f9782c01d081db64e"},
                {"odd": False, "hash": "8549d8a2dd3e7130da5629ca3bb7f06667c1a7551146d37931c4fc9d33631ba8"},
                {"odd": False, "hash": "489c2eb0f85f96ecae8295822152311b2cfd49781bf88bfc41d2233dc4eb37f4"},
                {"odd": False, "hash": "48f49966410e85025f82a45252fa83e0c71047da5638bfb2f234c58d021ccdde"},
                {"odd": True, "hash": "2dc6c9095320a3a252c996fd0ef3a833cf3b0370be331d312a302b814d5c74d2"},
                {"odd": True, "hash": "291b0e110845b26af972c67bbb5e12d62f6eab10872bf17685dbf776446ce98d"},
                {"odd": True, "hash": "830ec7fb0c87757fc9dd5340cb84f0fc5b09bfddd2f1f8d26c87dbef39e4dc32"},
                {"odd": False, "hash": "c0bfef3ae77acb8cf6b80520e21db51b3f22992ae3c10330405a371393cab9e1"},
                {"odd": False, "hash": "0000000000000000000000000000000000000000000000000000000000000003"},
                {"odd": False, "hash": "9914a968e24e06559c06f970066aac9efa29a66285981f2af9979ce0490124ae"},
                {"odd": True, "hash": "99ab44076946395c6f4cabdec2686b5aa6e0bfac91d4cdcbc759a2231e80b017"},
                {"odd": True, "hash": "49666ed318e0f0101be64ecee4794e5ce016d4d737fad5d61c6a7e703c01b0b4"},
                {"odd": True, "hash": "cccb7ffc80c98caae3cdb61deb89e6ee04a864221c42ed4c8eab43a9b94f17a7"},
                {"odd": False, "hash": "b03cda27b4fb2cd5c112de17e359d83de24530a500173aec58a2e752a3968025"},
                {"odd": False, "hash": "041f4b3b8a16e2bd3bd674715b51ed9e59df27f40de8e7c55bda069c6cb6cc6f"},
                {"odd": False, "hash": "6c17e88bb3d2a0cae5454f07cb56d09e192ef5c351b0316b1f342674bbb3031d"},
                {"odd": False, "hash": "ce01ad2296363eb7e928cf034c3c0dfb9fb2a164f91bc2e70dc3ace21109b73b"},
                {"odd": True, "hash": "2b70d527fd4019e31e7dacbc42bcad2e46172d4290ff8d23090d666559479dbb"},
                {"odd": False, "hash": "27d5eb878fce2145c1903ba84f81cffa2d789c34fa784fbfe2ecae812aab6890"},
                {"odd": False, "hash": "665b34a7e1b2578f2418823f702901f01ece537c96fe7e4d5d7b357e8d90e8d5"},
                {"odd": True, "hash": "18268d3e1dd64a6aca06c688538c365e2e113a057d4a2dd0b629c20d79a74eb5"},
                {"odd": False, "hash": "3e03c59427a569ccb5f8fcd36b3b38da044af981d9996ec94769f1f5458f7a7e"},
                {"odd": True, "hash": "f6c9440b20ad6903c08c21b4b3e7073ac53d10a74bcf2b46081a9b8e00fb4eaf"},
                {"odd": False, "hash": "084b8a05b60968476269e7e95fad736a4c2fb333273ac631d57ef807c7528a2b"},
                {"odd": False, "hash": "0000000000000000000000000000000000000000000000000000000000000003"},
            ],
            "txId": "a2c060a316bd56b3bc8f3d9d6997bf03f66625cda51347465ba88ccfac9ef3d7",
            "n": 0,
            "lastTakeoverHeight": 608276
        }

        self.assertTrue(is_proof_valid(claim, proof, claimtrie_root_hash))

    def old_algo(self):
        claim1_name = 97  # 'a'
        claim1_txid = 'bd9fa7ffd57d810d4ce14de76beea29d847b8ac34e8e536802534ecb1ca43b68'
        claim1_outpoint = 0
        claim1_height = 10
        claim1_node_hash = get_hash_for_outpoint(
            unhexlify(claim1_txid)[::-1], claim1_outpoint, claim1_height)

        claim2_name = 98  # 'b'
        claim2_txid = 'ad9fa7ffd57d810d4ce14de76beea29d847b8ac34e8e536802534ecb1ca43b68'
        claim2_outpoint = 1
        claim2_height = 5
        claim2_node_hash = get_hash_for_outpoint(
            unhexlify(claim2_txid)[::-1], claim2_outpoint, claim2_height)
        to_hash1 = claim1_node_hash
        hash1 = double_sha256(to_hash1)
        to_hash2 = bytes((claim1_name,)) + hash1 + bytes((claim2_name,)) + claim2_node_hash

        root_hash = double_sha256(to_hash2)

        proof = {
            'last takeover height': claim1_height, 'txhash': claim1_txid, 'nOut': claim1_outpoint,
            'nodes': [
                {'children': [
                    {'character': 97},
                    {
                        'character': 98,
                        'nodeHash': hexlify(claim2_node_hash[::-1])
                    }
                ]},
                {'children': []},
            ]
        }
        out = verify_proof_old(proof, hexlify(root_hash[::-1]), 'a')
        self.assertTrue(out)
