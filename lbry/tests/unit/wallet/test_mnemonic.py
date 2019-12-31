import unittest
from binascii import hexlify

from lbry.wallet.client.mnemonic import Mnemonic


class TestMnemonic(unittest.TestCase):

    def test_mnemonic_to_seed(self):
        seed = Mnemonic.mnemonic_to_seed(mnemonic='foobar', passphrase='torba')
        self.assertEqual(
            hexlify(seed),
            b'475a419db4e991cab14f08bde2d357e52b3e7241f72c6d8a2f92782367feeee9f403dc6a37c26a3f02ab9'
            b'dec7f5063161eb139cea00da64cd77fba2f07c49ddc'
        )

    def test_make_seed_decode_encode(self):
        iters = 10
        m = Mnemonic('en')
        for _ in range(iters):
            seed = m.make_seed()
            i = m.mnemonic_decode(seed)
            self.assertEqual(m.mnemonic_encode(i), seed)
