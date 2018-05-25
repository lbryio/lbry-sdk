from unittest import TestCase
from torba.hash import aes_decrypt, aes_encrypt

try:
    from unittest import mock
except ImportError:
    import mock


class TestAESEncryptDecrypt(TestCase):

    @mock.patch('os.urandom', side_effect=lambda i: b'f'*i)
    def test_encrypt(self, _):
        self.assertEqual(aes_encrypt(
            b'bubblegum', b'The Times 03/Jan/2009 Chancellor on brink of second bailout for banks'),
            b'OWsqm2goP4wXAPFyDde0IP2rPxRaESGr9NUlPn4y2nZrywQJo7pZCPt9ixYa7Ye9tzSpirF03Qd5OyI75xlGjd'
            b'4khKCvcX6tcViLmhIGUPY='
        )

    def test_decrypt(self):
        self.assertEqual(aes_decrypt(
            b'bubblegum', b'WeW99mQgRExAEzPjJOAC/MdTJaHgz3hT+kazFbvVQqF/KFva48ulVMOewU7JWD0ufWJIxtAIQ'
            b'bGtlbvbq5w74bsCCJLrtNTHBhenkms8XccJXTr/UF/ZYTF1Prz8b0AQ'),
            b'The Times 03/Jan/2009 Chancellor on brink of second bailout for banks'
        )
