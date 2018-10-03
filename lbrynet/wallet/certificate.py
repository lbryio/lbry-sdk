from collections import namedtuple


class Certificate(namedtuple('Certificate', ('channel', 'private_key'))):
    pass
