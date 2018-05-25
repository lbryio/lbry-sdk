# Copyright (C) 2014 Thomas Voegtlin
# Copyright (C) 2018 LBRY Inc.

import os
import io
import hmac
import math
import hashlib
import unicodedata
import string
from binascii import hexlify

import ecdsa
import pbkdf2

from torba.hash import hmac_sha512

# The hash of the mnemonic seed must begin with this
SEED_PREFIX = b'01'       # Standard wallet
SEED_PREFIX_2FA = b'101'  # Two-factor authentication
SEED_PREFIX_SW = b'100'   # Segwit wallet

# http://www.asahi-net.or.jp/~ax2s-kmtn/ref/unicode/e_asia.html
CJK_INTERVALS = [
    (0x4E00, 0x9FFF, 'CJK Unified Ideographs'),
    (0x3400, 0x4DBF, 'CJK Unified Ideographs Extension A'),
    (0x20000, 0x2A6DF, 'CJK Unified Ideographs Extension B'),
    (0x2A700, 0x2B73F, 'CJK Unified Ideographs Extension C'),
    (0x2B740, 0x2B81F, 'CJK Unified Ideographs Extension D'),
    (0xF900, 0xFAFF, 'CJK Compatibility Ideographs'),
    (0x2F800, 0x2FA1D, 'CJK Compatibility Ideographs Supplement'),
    (0x3190, 0x319F, 'Kanbun'),
    (0x2E80, 0x2EFF, 'CJK Radicals Supplement'),
    (0x2F00, 0x2FDF, 'CJK Radicals'),
    (0x31C0, 0x31EF, 'CJK Strokes'),
    (0x2FF0, 0x2FFF, 'Ideographic Description Characters'),
    (0xE0100, 0xE01EF, 'Variation Selectors Supplement'),
    (0x3100, 0x312F, 'Bopomofo'),
    (0x31A0, 0x31BF, 'Bopomofo Extended'),
    (0xFF00, 0xFFEF, 'Halfwidth and Fullwidth Forms'),
    (0x3040, 0x309F, 'Hiragana'),
    (0x30A0, 0x30FF, 'Katakana'),
    (0x31F0, 0x31FF, 'Katakana Phonetic Extensions'),
    (0x1B000, 0x1B0FF, 'Kana Supplement'),
    (0xAC00, 0xD7AF, 'Hangul Syllables'),
    (0x1100, 0x11FF, 'Hangul Jamo'),
    (0xA960, 0xA97F, 'Hangul Jamo Extended A'),
    (0xD7B0, 0xD7FF, 'Hangul Jamo Extended B'),
    (0x3130, 0x318F, 'Hangul Compatibility Jamo'),
    (0xA4D0, 0xA4FF, 'Lisu'),
    (0x16F00, 0x16F9F, 'Miao'),
    (0xA000, 0xA48F, 'Yi Syllables'),
    (0xA490, 0xA4CF, 'Yi Radicals'),
]


def is_cjk(c):
    n = ord(c)
    for start, end, name in CJK_INTERVALS:
        if start <= n <= end:
            return True
    return False


def normalize_text(seed):
    seed = unicodedata.normalize('NFKD', seed)
    seed = seed.lower()
    # remove accents
    seed = u''.join([c for c in seed if not unicodedata.combining(c)])
    # normalize whitespaces
    seed = u' '.join(seed.split())
    # remove whitespaces between CJK
    seed = u''.join([
        seed[i] for i in range(len(seed))
        if not (seed[i] in string.whitespace and is_cjk(seed[i-1]) and is_cjk(seed[i+1]))
    ])
    return seed


def load_words(filename):
    path = os.path.join(os.path.dirname(__file__), 'words', filename)
    with io.open(path, 'r', encoding='utf-8') as f:
        s = f.read().strip()
    s = unicodedata.normalize('NFKD', s)
    lines = s.split('\n')
    words = []
    for line in lines:
        line = line.split('#')[0]
        line = line.strip(' \r')
        assert ' ' not in line
        if line:
            words.append(line)
    return words


file_names = {
    'en': 'english.txt',
    'es': 'spanish.txt',
    'ja': 'japanese.txt',
    'pt': 'portuguese.txt',
    'zh': 'chinese_simplified.txt'
}


class Mnemonic(object):
    # Seed derivation no longer follows BIP39
    # Mnemonic phrase uses a hash based checksum, instead of a words-dependent checksum

    def __init__(self, lang='en'):
        filename = file_names.get(lang, 'english.txt')
        self.words = load_words(filename)

    @classmethod
    def mnemonic_to_seed(self, mnemonic, passphrase=u''):
        PBKDF2_ROUNDS = 2048
        mnemonic = normalize_text(mnemonic)
        passphrase = normalize_text(passphrase)
        return pbkdf2.PBKDF2(mnemonic, passphrase, iterations=PBKDF2_ROUNDS, macmodule=hmac, digestmodule=hashlib.sha512).read(64)

    def mnemonic_encode(self, i):
        n = len(self.words)
        words = []
        while i:
            x = i%n
            i = i//n
            words.append(self.words[x])
        return ' '.join(words)

    def mnemonic_decode(self, seed):
        n = len(self.words)
        words = seed.split()
        i = 0
        while words:
            w = words.pop()
            k = self.words.index(w)
            i = i*n + k
        return i

    def make_seed(self, prefix=SEED_PREFIX, num_bits=132):
        # increase num_bits in order to obtain a uniform distribution for the last word
        bpw = math.log(len(self.words), 2)
        # rounding
        n = int(math.ceil(num_bits/bpw) * bpw)
        entropy = 1
        while entropy < pow(2, n - bpw):
            # try again if seed would not contain enough words
            entropy = ecdsa.util.randrange(pow(2, n))
        nonce = 0
        while True:
            nonce += 1
            i = entropy + nonce
            seed = self.mnemonic_encode(i)
            if i != self.mnemonic_decode(seed):
                raise Exception('Cannot extract same entropy from mnemonic!')
            if is_new_seed(seed, prefix):
                break
        return seed


def is_new_seed(seed, prefix):
    seed = normalize_text(seed)
    seed_hash = hexlify(hmac_sha512(b"seed version", seed.encode('utf8')))
    return seed_hash.startswith(prefix)
