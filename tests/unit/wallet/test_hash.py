from unittest import TestCase, mock
from lbry.crypto.crypt import aes_decrypt, aes_encrypt, better_aes_decrypt, better_aes_encrypt
from lbry.error import InvalidPasswordError


class TestAESEncryptDecrypt(TestCase):
    message = 'The Times 03/Jan/2009 Chancellor on brink of second bailout for banks'
    expected = 'ZmZmZmZmZmZmZmZmZmZmZjlrKptoKD+MFwDxcg3XtCD9qz8UWhEhq/TVJT5+Mtp2a8sE' \
               'CaO6WQj7fYsWGu2Hvbc0qYqxdN0HeTsiO+cZRo3eJISgr3F+rXFYi5oSBlD2'
    password = 'bubblegum'

    @mock.patch('os.urandom', side_effect=lambda i: b'd'*i)
    def test_encrypt_iv_f(self, _):
        self.assertEqual(
            aes_encrypt(self.password, self.message),
           'ZGRkZGRkZGRkZGRkZGRkZKBP/4pR+47hLHbHyvDJm9aRKDuoBdTG8SrFvHqfagK6Co1VrHUOd'
           'oF+6PGSxru3+VR63ybkXLNM75s/qVw+dnKVAkI8OfoVnJvGRSc49e38'
        )

    @mock.patch('os.urandom', side_effect=lambda i: b'f'*i)
    def test_encrypt_iv_d(self, _):
        self.assertEqual(
            aes_encrypt(self.password, self.message),
           'ZmZmZmZmZmZmZmZmZmZmZjlrKptoKD+MFwDxcg3XtCD9qz8UWhEhq/TVJT5+Mtp2a8sE'
           'CaO6WQj7fYsWGu2Hvbc0qYqxdN0HeTsiO+cZRo3eJISgr3F+rXFYi5oSBlD2'
        )
        self.assertTupleEqual(
            aes_decrypt(self.password, self.expected),
            (self.message, b'f' * 16)
        )

    def test_encrypt_decrypt(self):
        self.assertEqual(
            aes_decrypt('bubblegum', aes_encrypt('bubblegum', self.message))[0],
            self.message
        )

    def test_decrypt_error(self):
        with self.assertRaises(InvalidPasswordError):
            aes_decrypt('notbubblegum', aes_encrypt('bubblegum', self.message))

    def test_edge_case_invalid_password_valid_padding_invalid_unicode(self):
        with self.assertRaises(InvalidPasswordError):
            aes_decrypt('notbubblegum', 'gy3/mNq3FWB/xAXirOQnlAqQLuvhLGXZaeGBUIg1w6yY4PDLDT7BU83XOfBsJoluWU5zEU4+upOFH35HDqyV8EMQhcKSufN9WkT1izEbFtweBUTK8nTSkV7NBppE1Jaz')

    def test_better_encrypt_decrypt(self):
        self.assertEqual(
            b'valuable value',
            better_aes_decrypt(
                'super secret',
                better_aes_encrypt('super secret', b'valuable value')))

    def test_better_decrypt_error(self):
        with self.assertRaises(InvalidPasswordError):
            better_aes_decrypt(
                'super secret but wrong',
                better_aes_encrypt('super secret', b'valuable value')
            )
