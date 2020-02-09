from binascii import hexlify


def claim_id(claim_hash):
    return hexlify(claim_hash[::-1]).decode()


class BaseError(Exception):
    pass
