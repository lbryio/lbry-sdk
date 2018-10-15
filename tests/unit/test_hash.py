from unittest import TestCase, mock
from torba.hash import aes_decrypt, aes_encrypt


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

    def test_encrypt_decrypt(self):
        self.assertEqual(
            aes_decrypt('bubblegum', aes_encrypt('bubblegum', self.message)),
            self.message
        )
