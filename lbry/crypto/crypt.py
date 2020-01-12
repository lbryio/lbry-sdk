import os
import base64
import typing
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from cryptography.hazmat.primitives.ciphers.algorithms import AES
from cryptography.hazmat.primitives.padding import PKCS7
from cryptography.hazmat.backends import default_backend

from lbry.error import InvalidPasswordError
from lbry.crypto.hash import double_sha256


def aes_encrypt(secret: str, value: str, init_vector: bytes = None) -> str:
    if init_vector is not None:
        assert len(init_vector) == 16
    else:
        init_vector = os.urandom(16)
    key = double_sha256(secret.encode())
    encryptor = Cipher(AES(key), modes.CBC(init_vector), default_backend()).encryptor()
    padder = PKCS7(AES.block_size).padder()
    padded_data = padder.update(value.encode()) + padder.finalize()
    encrypted_data = encryptor.update(padded_data) + encryptor.finalize()
    return base64.b64encode(init_vector + encrypted_data).decode()


def aes_decrypt(secret: str, value: str) -> typing.Tuple[str, bytes]:
    try:
        data = base64.b64decode(value.encode())
        key = double_sha256(secret.encode())
        init_vector, data = data[:16], data[16:]
        decryptor = Cipher(AES(key), modes.CBC(init_vector), default_backend()).decryptor()
        unpadder = PKCS7(AES.block_size).unpadder()
        result = unpadder.update(decryptor.update(data)) + unpadder.finalize()
        return result.decode(), init_vector
    except UnicodeDecodeError:
        raise InvalidPasswordError()
    except ValueError as e:
        if e.args[0] == 'Invalid padding bytes.':
            raise InvalidPasswordError()
        raise


def better_aes_encrypt(secret: str, value: bytes) -> bytes:
    init_vector = os.urandom(16)
    key = scrypt(secret.encode(), salt=init_vector)
    encryptor = Cipher(AES(key), modes.CBC(init_vector), default_backend()).encryptor()
    padder = PKCS7(AES.block_size).padder()
    padded_data = padder.update(value) + padder.finalize()
    encrypted_data = encryptor.update(padded_data) + encryptor.finalize()
    return base64.b64encode(b's:8192:16:1:' + init_vector + encrypted_data)


def better_aes_decrypt(secret: str, value: bytes) -> bytes:
    try:
        data = base64.b64decode(value)
        _, scryp_n, scrypt_r, scrypt_p, data = data.split(b':', maxsplit=4)
        init_vector, data = data[:16], data[16:]
        key = scrypt(secret.encode(), init_vector, int(scryp_n), int(scrypt_r), int(scrypt_p))
        decryptor = Cipher(AES(key), modes.CBC(init_vector), default_backend()).decryptor()
        unpadder = PKCS7(AES.block_size).unpadder()
        return unpadder.update(decryptor.update(data)) + unpadder.finalize()
    except ValueError as e:
        if e.args[0] == 'Invalid padding bytes.':
            raise InvalidPasswordError()
        raise


def scrypt(passphrase, salt, scrypt_n=1<<13, scrypt_r=16, scrypt_p=1):
    kdf = Scrypt(salt, length=32, n=scrypt_n, r=scrypt_r, p=scrypt_p, backend=default_backend())
    return kdf.derive(passphrase)
