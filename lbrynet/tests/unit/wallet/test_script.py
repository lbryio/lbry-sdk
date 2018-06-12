from binascii import hexlify, unhexlify
from twisted.trial import unittest

from lbrynet.wallet.script import OutputScript


class TestPayClaimNamePubkeyHash(unittest.TestCase):

    def pay_claim_name_pubkey_hash(self, name, claim, pubkey_hash):
        # this checks that factory function correctly sets up the script
        src1 = OutputScript.pay_claim_name_pubkey_hash(
            name, unhexlify(claim), unhexlify(pubkey_hash))
        self.assertEqual(src1.template.name, 'claim_name+pay_pubkey_hash')
        self.assertEqual(src1.values['claim_name'], name)
        self.assertEqual(hexlify(src1.values['claim']), claim)
        self.assertEqual(hexlify(src1.values['pubkey_hash']), pubkey_hash)
        # now we test that it will round trip
        src2 = OutputScript(src1.source)
        self.assertEqual(src2.template.name, 'claim_name+pay_pubkey_hash')
        self.assertEqual(src2.values['claim_name'], name)
        self.assertEqual(hexlify(src2.values['claim']), claim)
        self.assertEqual(hexlify(src2.values['pubkey_hash']), pubkey_hash)
        return hexlify(src1.source)

    def test_pay_claim_name_pubkey_hash_1(self):
        self.assertEqual(
            self.pay_claim_name_pubkey_hash(
                # name
                b'cats',
                # claim
                b'080110011a7808011230080410011a084d616361726f6e6922002a003214416c6c20726967687473'
                b'2072657365727665642e38004a0052005a001a42080110011a30add80aaf02559ba09853636a0658'
                b'c42b727cb5bb4ba8acedb4b7fe656065a47a31878dbf9912135ddb9e13806cc1479d220a696d6167'
                b'652f6a7065672a5c080110031a404180cc0fa4d3839ee29cca866baed25fafb43fca1eb3b608ee88'
                b'9d351d3573d042c7b83e2e643db0d8e062a04e6e9ae6b90540a2f95fe28638d0f18af4361a1c2214'
                b'f73de93f4299fb32c32f949e02198a8e91101abd',
                # pub key
                b'be16e4b0f9bd8f6d47d02b3a887049c36d3b84cb'
            ),
            b'b504636174734cdc080110011a7808011230080410011a084d616361726f6e6922002a003214416c6c207'
            b'269676874732072657365727665642e38004a0052005a001a42080110011a30add80aaf02559ba0985363'
            b'6a0658c42b727cb5bb4ba8acedb4b7fe656065a47a31878dbf9912135ddb9e13806cc1479d220a696d616'
            b'7652f6a7065672a5c080110031a404180cc0fa4d3839ee29cca866baed25fafb43fca1eb3b608ee889d35'
            b'1d3573d042c7b83e2e643db0d8e062a04e6e9ae6b90540a2f95fe28638d0f18af4361a1c2214f73de93f4'
            b'299fb32c32f949e02198a8e91101abd6d7576a914be16e4b0f9bd8f6d47d02b3a887049c36d3b84cb88ac'
        )
