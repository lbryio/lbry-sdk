from binascii import unhexlify, hexlify

from lbry.testcase import AsyncioTestCase
from lbry.wallet.bip32 import PubKey, PrivateKey, from_extended_key_string
from lbry.wallet import Ledger, Database, Headers

from tests.unit.wallet.key_fixtures import expected_ids, expected_privkeys, expected_hardened_privkeys


class BIP32Tests(AsyncioTestCase):

    def test_pubkey_validation(self):
        with self.assertRaisesRegex(TypeError, 'chain code must be raw bytes'):
            PubKey(None, None, 1, None, None, None)
        with self.assertRaisesRegex(ValueError, 'invalid chain code'):
            PubKey(None, None, b'abcd', None, None, None)
        with self.assertRaisesRegex(ValueError, 'invalid child number'):
            PubKey(None, None, b'abcd'*8, -1, None, None)
        with self.assertRaisesRegex(ValueError, 'invalid depth'):
            PubKey(None, None, b'abcd'*8, 0, 256, None)
        with self.assertRaisesRegex(TypeError, 'pubkey must be raw bytes'):
            PubKey(None, None, b'abcd'*8, 0, 255, None)
        with self.assertRaisesRegex(ValueError, 'pubkey must be 33 bytes'):
            PubKey(None, b'abcd', b'abcd'*8, 0, 255, None)
        with self.assertRaisesRegex(ValueError, 'invalid pubkey prefix byte'):
            PubKey(
                None,
                unhexlify('33d1a3dc8155673bc1e2214fa493ccc82d57961b66054af9b6b653ac28eeef3ffe'),
                b'abcd'*8, 0, 255, None
            )
        pubkey = PubKey(  # success
            None,
            unhexlify('03d1a3dc8155673bc1e2214fa493ccc82d57961b66054af9b6b653ac28eeef3ffe'),
            b'abcd'*8, 0, 1, None
        )
        with self.assertRaisesRegex(ValueError, 'invalid BIP32 public key child number'):
            pubkey.child(-1)
        for i in range(20):
            new_key = pubkey.child(i)
            self.assertIsInstance(new_key, PubKey)
            self.assertEqual(hexlify(new_key.identifier()), expected_ids[i])

    async def test_private_key_validation(self):
        with self.assertRaisesRegex(TypeError, 'private key must be raw bytes'):
            PrivateKey(None, None, b'abcd'*8, 0, 255)
        with self.assertRaisesRegex(ValueError, 'private key must be 32 bytes'):
            PrivateKey(None, b'abcd', b'abcd'*8, 0, 255)
        private_key = PrivateKey(
            Ledger({
                'db': Database(':memory:'),
                'headers': Headers(':memory:'),
            }),
            unhexlify('2423f3dc6087d9683f73a684935abc0ccd8bc26370588f56653128c6a6f0bf7c'),
            b'abcd'*8, 0, 1
        )
        ec_point = private_key.ec_point()
        self.assertEqual(
            ec_point[0], 30487144161998778625547553412379759661411261804838752332906558028921886299019
        )
        self.assertEqual(
            ec_point[1], 86198965946979720220333266272536217633917099472454294641561154971209433250106
        )
        self.assertEqual('bUDcmraBp2zCV3QWmVVeQaEgepbs1b2gC9', private_key.address())
        with self.assertRaisesRegex(ValueError, 'invalid BIP32 private key child number'):
            private_key.child(-1)
        self.assertIsInstance(private_key.child(PrivateKey.HARDENED), PrivateKey)

    async def test_private_key_derivation(self):
        private_key = PrivateKey(
            Ledger({
                'db': Database(':memory:'),
                'headers': Headers(':memory:'),
            }),
            unhexlify('2423f3dc6087d9683f73a684935abc0ccd8bc26370588f56653128c6a6f0bf7c'),
            b'abcd'*8, 0, 1
        )
        for i in range(20):
            new_privkey = private_key.child(i)
            self.assertIsInstance(new_privkey, PrivateKey)
            self.assertEqual(hexlify(new_privkey.private_key_bytes), expected_privkeys[i])
        for i in range(PrivateKey.HARDENED + 1, private_key.HARDENED + 20):
            new_privkey = private_key.child(i)
            self.assertIsInstance(new_privkey, PrivateKey)
            self.assertEqual(hexlify(new_privkey.private_key_bytes), expected_hardened_privkeys[i - 1 - PrivateKey.HARDENED])

    async def test_from_extended_keys(self):
        ledger = Ledger({
            'db': Database(':memory:'),
            'headers': Headers(':memory:'),
        })
        self.assertIsInstance(
            from_extended_key_string(
                ledger,
                'xprv9s21ZrQH143K2dyhK7SevfRG72bYDRNv25yKPWWm6dqApNxm1Zb1m5gGcBWYfbsPjTr2v5joit8Af2Zp5P'
                '6yz3jMbycrLrRMpeAJxR8qDg8',
            ), PrivateKey
        )
        self.assertIsInstance(
            from_extended_key_string(
                ledger,
                'xpub661MyMwAqRbcF84AR8yfHoMzf4S2ct6mPJtvBtvNeyN9hBHuZ6uGJszkTSn5fQUCdz3XU17eBzFeAUwV6f'
                'iW44g14WF52fYC5J483wqQ5ZP',
            ), PubKey
        )
