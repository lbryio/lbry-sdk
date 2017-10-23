class Distance(object):
    """Calculate the XOR result between two string variables.

    Frequently we re-use one of the points so as an optimization
    we pre-calculate the long value of that point.
    """

    def __init__(self, key):
        self.key = key
        self.val_key_one = long(key.encode('hex'), 16)

    def __call__(self, key_two):
        val_key_two = long(key_two.encode('hex'), 16)
        return self.val_key_one ^ val_key_two

    def is_closer(self, a, b):
        """Returns true is `a` is closer to `key` than `b` is"""
        return self(a) < self(b)

    def to_contact(self, contact):
        """A convenience function for calculating the distance to a contact"""
        return self(contact.id)
