import os
import datetime
import hmac
import hashlib
import base58
from OpenSSL.crypto import FILETYPE_PEM
from ssl import create_default_context, SSLContext
from cryptography.hazmat.backends import default_backend
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.x509.name import NameOID, NameAttribute
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from twisted.internet import ssl
import logging
from lbrynet.extras.daemon import conf

log = logging.getLogger(__name__)


def sha(x: bytes) -> str:
    h = hashlib.sha256(x).digest()
    return base58.b58encode(h).decode()


def generate_key(x: bytes = None) -> str:
    if not x:
        return sha(os.urandom(256))
    else:
        return sha(x)


class APIKey:
    def __init__(self, secret: str, name: str):
        self.secret = secret
        self.name = name

    @classmethod
    def create(cls, seed=None, name=None):
        secret = generate_key(seed)
        return APIKey(secret, name)

    def _raw_key(self) -> str:
        return base58.b58decode(self.secret)

    def get_hmac(self, message) -> str:
        decoded_key = self._raw_key()
        signature = hmac.new(decoded_key, message.encode(), hashlib.sha256)
        return base58.b58encode(signature.digest())

    def compare_hmac(self, message, token) -> bool:
        decoded_token = base58.b58decode(token)
        target = base58.b58decode(self.get_hmac(message))

        try:
            if len(decoded_token) != len(target):
                return False
            return hmac.compare_digest(decoded_token, target)
        except:
            return False


class Keyring:
    encoding = serialization.Encoding.PEM
    filetype = FILETYPE_PEM

    def __init__(self, api_key: APIKey, public_certificate: str, private_certificate: ssl.PrivateCertificate = None):
        self.api_key: APIKey = api_key
        self.public_certificate: str = public_certificate
        self.private_certificate: (ssl.PrivateCertificate or None) = private_certificate
        self.ssl_context: SSLContext = create_default_context(cadata=self.public_certificate)

    @classmethod
    def load_from_disk(cls):
        api_key_path = os.path.join(conf.settings['data_dir'], 'auth_token')
        api_ssl_cert_path = os.path.join(conf.settings['data_dir'], 'api_ssl_cert.pem')
        if not os.path.isfile(api_key_path) or not os.path.isfile(api_ssl_cert_path):
            return
        with open(api_key_path, 'rb') as f:
            api_key = APIKey(f.read().decode(), "api")
        with open(api_ssl_cert_path, 'rb') as f:
            public_cert = f.read().decode()
        return cls(api_key, public_cert)

    @classmethod
    def generate_and_save(cls):
        dns = conf.settings['api_host']
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
            backend=default_backend()
        )
        subject = issuer = x509.Name([
            NameAttribute(NameOID.COUNTRY_NAME, "US"),
            NameAttribute(NameOID.ORGANIZATION_NAME, "LBRY"),
            NameAttribute(NameOID.COMMON_NAME, "LBRY API"),
        ])
        alternative_name = x509.SubjectAlternativeName([x509.DNSName(dns)])
        certificate = x509.CertificateBuilder(
            subject_name=subject,
            issuer_name=issuer,
            public_key=private_key.public_key(),
            serial_number=x509.random_serial_number(),
            not_valid_before=datetime.datetime.utcnow(),
            not_valid_after=datetime.datetime.utcnow() + datetime.timedelta(days=365),
            extensions=[x509.Extension(oid=alternative_name.oid, critical=False, value=alternative_name)]
        ).sign(private_key, hashes.SHA256(), default_backend())
        public_certificate = certificate.public_bytes(cls.encoding).decode()
        private_certificate = ssl.PrivateCertificate.load(
            public_certificate,
            ssl.KeyPair.load(
                private_key.private_bytes(
                    encoding=cls.encoding,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption()
                ).decode(),
                cls.filetype
            ),
            cls.filetype
        )

        auth_token = APIKey.create(seed=None, name="api")

        with open(os.path.join(conf.settings['data_dir'], 'auth_token'), 'wb') as f:
            f.write(auth_token.secret.encode())

        with open(os.path.join(conf.settings['data_dir'], 'api_ssl_cert.pem'), 'wb') as f:
            f.write(public_certificate.encode())

        return cls(auth_token, public_certificate, private_certificate)
