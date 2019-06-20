from lbrynet.dht import constants


class Distance:
    """Calculate the XOR result between two string variables.

    Frequently we re-use one of the points so as an optimization
    we pre-calculate the value of that point.
    """

    def __init__(self, key: bytes):
        if len(key) != constants.hash_length:
            raise ValueError(f"invalid key length: {len(key)}")
        self.key = key
        self.val_key_one = int.from_bytes(key, 'big')

    def __call__(self, key_two: bytes) -> int:
        if len(key_two) != constants.hash_length:
            raise ValueError(f"invalid length of key to compare: {len(key_two)}")
        val_key_two = int.from_bytes(key_two, 'big')
        return self.val_key_one ^ val_key_two

    def is_closer(self, a: bytes, b: bytes) -> bool:
        """Returns true is `a` is closer to `key` than `b` is"""
        return self(a) < self(b)
