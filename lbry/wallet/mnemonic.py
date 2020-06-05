import hashlib
import asyncio
import unicodedata
from binascii import hexlify
from secrets import randbits

from lbry.crypto.hash import hmac_sha512
from . import words


def get_languages():
    return words.languages


def normalize(phrase: str) -> str:
    return ' '.join(unicodedata.normalize('NFKD', phrase).lower().split())


def is_phrase_valid(language, phrase):
    local_words = getattr(words, language)
    for word in normalize(phrase).split():
        if word not in local_words:
            return False
    return bool(phrase)


def sync_generate_phrase(language: str) -> str:
    local_words = getattr(words, language)
    entropy = randbits(132)
    nonce = 0
    while True:
        nonce += 1
        i = entropy + nonce
        word_buffer = []
        while i:
            word_buffer.append(local_words[i % 2048])
            i //= 2048
        seed = ' '.join(word_buffer)
        if hexlify(hmac_sha512(b"Seed version", seed.encode())).startswith(b"01"):
            break
    return seed


def sync_derive_key_from_phrase(phrase: str) -> bytes:
    return hashlib.pbkdf2_hmac('sha512', normalize(phrase).encode(), b'lbryum', 2048)


async def generate_phrase(language: str) -> str:
    return await asyncio.get_running_loop().run_in_executor(
        None, sync_generate_phrase, language
    )


async def derive_key_from_phrase(phrase: str) -> bytes:
    return await asyncio.get_running_loop().run_in_executor(
        None, sync_derive_key_from_phrase, phrase
    )
