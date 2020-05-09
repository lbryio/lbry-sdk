import hashlib
import asyncio
import unicodedata
from binascii import hexlify
from secrets import randbits

from lbry.crypto.hash import hmac_sha512
from . import words


def get_languages():
    return words.languages


def normalize(mnemonic: str) -> str:
    return ' '.join(unicodedata.normalize('NFKD', mnemonic).lower().split())


def is_valid(language, mnemonic):
    local_words = getattr(words, language)
    for word in normalize(mnemonic).split():
        if word not in local_words:
            return False
    return bool(mnemonic)


def sync_generate(language: str) -> str:
    local_words = getattr(words, language)
    entropy = randbits(132)
    nonce = 0
    while True:
        nonce += 1
        i = entropy + nonce
        w = []
        while i:
            w.append(local_words[i % 2048])
            i //= 2048
        seed = ' '.join(w)
        if hexlify(hmac_sha512(b"Seed version", seed.encode())).startswith(b"01"):
            break
    return seed


def sync_to_seed(mnemonic: str) -> bytes:
    return hashlib.pbkdf2_hmac('sha512', normalize(mnemonic).encode(), b'lbryum', 2048)


async def generate(language: str) -> str:
    return await asyncio.get_running_loop().run_in_executor(
        None, sync_generate, language
    )


async def to_seed(mnemonic: str) -> bytes:
    return await asyncio.get_running_loop().run_in_executor(
        None, sync_to_seed, mnemonic
    )
