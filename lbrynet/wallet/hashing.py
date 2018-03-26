import hashlib
import hmac


def sha256(x):
    return hashlib.sha256(x).digest()


def sha512(x):
    return hashlib.sha512(x).digest()


def ripemd160(x):
    h = hashlib.new('ripemd160')
    h.update(x)
    return h.digest()


def Hash(x):
    if type(x) is unicode:
        x = x.encode('utf-8')
    return sha256(sha256(x))


def PoWHash(x):
    if type(x) is unicode:
        x = x.encode('utf-8')
    r = sha512(Hash(x))
    r1 = ripemd160(r[:len(r) / 2])
    r2 = ripemd160(r[len(r) / 2:])
    r3 = Hash(r1 + r2)
    return r3


def hash_encode(x):
    return x[::-1].encode('hex')


def hash_decode(x):
    return x.decode('hex')[::-1]


def hmac_sha_512(x, y):
    return hmac.new(x, y, hashlib.sha512).digest()


def hash_160(public_key):
    md = hashlib.new('ripemd160')
    md.update(sha256(public_key))
    return md.digest()
