import seccure
import hashlib


def get_lbry_hash_obj():
    return hashlib.sha384()


def get_pub_key(pass_phrase):
    return str(seccure.passphrase_to_pubkey(pass_phrase, curve="brainpoolp384r1"))


def sign_with_pass_phrase(m, pass_phrase):
    return seccure.sign(m, pass_phrase, curve="brainpoolp384r1")


def verify_signature(m, signature, pub_key):
    return seccure.verify(m, signature, pub_key, curve="brainpoolp384r1")
