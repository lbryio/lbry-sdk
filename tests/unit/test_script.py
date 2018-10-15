import unittest
from binascii import hexlify, unhexlify

from torba.bcd_data_stream import BCDataStream
from torba.basescript import Template, ParseError, tokenize, push_data
from torba.basescript import PUSH_SINGLE, PUSH_INTEGER, PUSH_MANY, OP_HASH160, OP_EQUAL
from torba.basescript import BaseInputScript, BaseOutputScript


def parse(opcodes, source):
    template = Template('test', opcodes)
    s = BCDataStream()
    for t in source:
        if isinstance(t, bytes):
            s.write_many(push_data(t))
        elif isinstance(t, int):
            s.write_uint8(t)
        else:
            raise ValueError()
    s.reset()
    return template.parse(tokenize(s))


class TestScriptTemplates(unittest.TestCase):

    def test_push_data(self):
        self.assertEqual(parse(
                (PUSH_SINGLE('script_hash'),),
                (b'abcdef',)
            ), {
                'script_hash': b'abcdef'
            }
        )
        self.assertEqual(parse(
                (PUSH_SINGLE('first'), PUSH_INTEGER('rating')),
                (b'Satoshi', (1000).to_bytes(2, 'little'))
            ), {
                'first': b'Satoshi',
                'rating': 1000,
            }
        )
        self.assertEqual(parse(
                (OP_HASH160, PUSH_SINGLE('script_hash'), OP_EQUAL),
                (OP_HASH160, b'abcdef', OP_EQUAL)
            ), {
                'script_hash': b'abcdef'
            }
        )

    def test_push_data_many(self):
        self.assertEqual(parse(
                (PUSH_MANY('names'),),
                (b'amit',)
            ), {
                'names': [b'amit']
            }
        )
        self.assertEqual(parse(
                (PUSH_MANY('names'),),
                (b'jeremy', b'amit', b'victor')
            ), {
                'names': [b'jeremy', b'amit', b'victor']
            }
        )
        self.assertEqual(parse(
                (OP_HASH160, PUSH_MANY('names'), OP_EQUAL),
                (OP_HASH160, b'grin', b'jack', OP_EQUAL)
            ), {
                'names': [b'grin', b'jack']
            }
        )

    def test_push_data_mixed(self):
        self.assertEqual(parse(
                (PUSH_SINGLE('CEO'), PUSH_MANY('Devs'), PUSH_SINGLE('CTO'), PUSH_SINGLE('State')),
                (b'jeremy', b'lex', b'amit', b'victor', b'jack', b'grin', b'NH')
            ), {
                'CEO': b'jeremy',
                'CTO': b'grin',
                'Devs': [b'lex', b'amit', b'victor', b'jack'],
                'State': b'NH'
            }
        )

    def test_push_data_many_separated(self):
        self.assertEqual(parse(
                (PUSH_MANY('Chiefs'), OP_HASH160, PUSH_MANY('Devs')),
                (b'jeremy', b'grin', OP_HASH160, b'lex', b'jack')
            ), {
                'Chiefs': [b'jeremy', b'grin'],
                'Devs': [b'lex', b'jack']
            }
        )

    def test_push_data_many_not_separated(self):
        with self.assertRaisesRegex(ParseError, 'consecutive PUSH_MANY'):
            parse((PUSH_MANY('Chiefs'), PUSH_MANY('Devs')), (b'jeremy', b'grin', b'lex', b'jack'))


class TestRedeemPubKeyHash(unittest.TestCase):

    def redeem_pubkey_hash(self, sig, pubkey):
        # this checks that factory function correctly sets up the script
        src1 = BaseInputScript.redeem_pubkey_hash(unhexlify(sig), unhexlify(pubkey))
        self.assertEqual(src1.template.name, 'pubkey_hash')
        self.assertEqual(hexlify(src1.values['signature']), sig)
        self.assertEqual(hexlify(src1.values['pubkey']), pubkey)
        # now we test that it will round trip
        src2 = BaseInputScript(src1.source)
        self.assertEqual(src2.template.name, 'pubkey_hash')
        self.assertEqual(hexlify(src2.values['signature']), sig)
        self.assertEqual(hexlify(src2.values['pubkey']), pubkey)
        return hexlify(src1.source)

    def test_redeem_pubkey_hash_1(self):
        self.assertEqual(
            self.redeem_pubkey_hash(
                b'30450221009dc93f25184a8d483745cd3eceff49727a317c9bfd8be8d3d04517e9cdaf8dd502200e'
                b'02dc5939cad9562d2b1f303f185957581c4851c98d497af281118825e18a8301',
                b'025415a06514230521bff3aaface31f6db9d9bbc39bf1ca60a189e78731cfd4e1b'
            ),
            b'4830450221009dc93f25184a8d483745cd3eceff49727a317c9bfd8be8d3d04517e9cdaf8dd502200e02d'
            b'c5939cad9562d2b1f303f185957581c4851c98d497af281118825e18a830121025415a06514230521bff3'
            b'aaface31f6db9d9bbc39bf1ca60a189e78731cfd4e1b'
        )


class TestRedeemScriptHash(unittest.TestCase):

    def redeem_script_hash(self, sigs, pubkeys):
        # this checks that factory function correctly sets up the script
        src1 = BaseInputScript.redeem_script_hash(
            [unhexlify(sig) for sig in sigs],
            [unhexlify(pubkey) for pubkey in pubkeys]
        )
        subscript1 = src1.values['script']
        self.assertEqual(src1.template.name, 'script_hash')
        self.assertEqual([hexlify(v) for v in src1.values['signatures']], sigs)
        self.assertEqual([hexlify(p) for p in subscript1.values['pubkeys']], pubkeys)
        self.assertEqual(subscript1.values['signatures_count'], len(sigs))
        self.assertEqual(subscript1.values['pubkeys_count'], len(pubkeys))
        # now we test that it will round trip
        src2 = BaseInputScript(src1.source)
        subscript2 = src2.values['script']
        self.assertEqual(src2.template.name, 'script_hash')
        self.assertEqual([hexlify(v) for v in src2.values['signatures']], sigs)
        self.assertEqual([hexlify(p) for p in subscript2.values['pubkeys']], pubkeys)
        self.assertEqual(subscript2.values['signatures_count'], len(sigs))
        self.assertEqual(subscript2.values['pubkeys_count'], len(pubkeys))
        return hexlify(src1.source)

    def test_redeem_script_hash_1(self):
        self.assertEqual(
            self.redeem_script_hash([
                b'3045022100fec82ed82687874f2a29cbdc8334e114af645c45298e85bb1efe69fcf15c617a0220575'
                b'e40399f9ada388d8e522899f4ec3b7256896dd9b02742f6567d960b613f0401',
                b'3044022024890462f731bd1a42a4716797bad94761fc4112e359117e591c07b8520ea33b02201ac68'
                b'9e35c4648e6beff1d42490207ba14027a638a62663b2ee40153299141eb01',
                b'30450221009910823e0142967a73c2d16c1560054d71c0625a385904ba2f1f53e0bc1daa8d02205cd'
                b'70a89c6cf031a8b07d1d5eb0d65d108c4d49c2d403f84fb03ad3dc318777a01'
            ], [
                b'0372ba1fd35e5f1b1437cba0c4ebfc4025b7349366f9f9c7c8c4b03a47bd3f68a4',
                b'03061d250182b2db1ba144167fd8b0ef3fe0fc3a2fa046958f835ffaf0dfdb7692',
                b'02463bfbc1eaec74b5c21c09239ae18dbf6fc07833917df10d0b43e322810cee0c',
                b'02fa6a6455c26fb516cfa85ea8de81dd623a893ffd579ee2a00deb6cdf3633d6bb',
                b'0382910eae483ce4213d79d107bfc78f3d77e2a31ea597be45256171ad0abeaa89'
            ]),
            b'00483045022100fec82ed82687874f2a29cbdc8334e114af645c45298e85bb1efe69fcf15c617a0220575e'
            b'40399f9ada388d8e522899f4ec3b7256896dd9b02742f6567d960b613f0401473044022024890462f731bd'
            b'1a42a4716797bad94761fc4112e359117e591c07b8520ea33b02201ac689e35c4648e6beff1d42490207ba'
            b'14027a638a62663b2ee40153299141eb014830450221009910823e0142967a73c2d16c1560054d71c0625a'
            b'385904ba2f1f53e0bc1daa8d02205cd70a89c6cf031a8b07d1d5eb0d65d108c4d49c2d403f84fb03ad3dc3'
            b'18777a014cad53210372ba1fd35e5f1b1437cba0c4ebfc4025b7349366f9f9c7c8c4b03a47bd3f68a42103'
            b'061d250182b2db1ba144167fd8b0ef3fe0fc3a2fa046958f835ffaf0dfdb76922102463bfbc1eaec74b5c2'
            b'1c09239ae18dbf6fc07833917df10d0b43e322810cee0c2102fa6a6455c26fb516cfa85ea8de81dd623a89'
            b'3ffd579ee2a00deb6cdf3633d6bb210382910eae483ce4213d79d107bfc78f3d77e2a31ea597be45256171'
            b'ad0abeaa8955ae'
        )


class TestPayPubKeyHash(unittest.TestCase):

    def pay_pubkey_hash(self, pubkey_hash):
        # this checks that factory function correctly sets up the script
        src1 = BaseOutputScript.pay_pubkey_hash(unhexlify(pubkey_hash))
        self.assertEqual(src1.template.name, 'pay_pubkey_hash')
        self.assertEqual(hexlify(src1.values['pubkey_hash']), pubkey_hash)
        # now we test that it will round trip
        src2 = BaseOutputScript(src1.source)
        self.assertEqual(src2.template.name, 'pay_pubkey_hash')
        self.assertEqual(hexlify(src2.values['pubkey_hash']), pubkey_hash)
        return hexlify(src1.source)

    def test_pay_pubkey_hash_1(self):
        self.assertEqual(
            self.pay_pubkey_hash(b'64d74d12acc93ba1ad495e8d2d0523252d664f4d'),
            b'76a91464d74d12acc93ba1ad495e8d2d0523252d664f4d88ac'
        )


class TestPayScriptHash(unittest.TestCase):

    def pay_script_hash(self, script_hash):
        # this checks that factory function correctly sets up the script
        src1 = BaseOutputScript.pay_script_hash(unhexlify(script_hash))
        self.assertEqual(src1.template.name, 'pay_script_hash')
        self.assertEqual(hexlify(src1.values['script_hash']), script_hash)
        # now we test that it will round trip
        src2 = BaseOutputScript(src1.source)
        self.assertEqual(src2.template.name, 'pay_script_hash')
        self.assertEqual(hexlify(src2.values['script_hash']), script_hash)
        return hexlify(src1.source)

    def test_pay_pubkey_hash_1(self):
        self.assertEqual(
            self.pay_script_hash(b'63d65a2ee8c44426d06050cfd71c0f0ff3fc41ac'),
            b'a91463d65a2ee8c44426d06050cfd71c0f0ff3fc41ac87'
        )
