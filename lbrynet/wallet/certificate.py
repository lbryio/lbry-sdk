from collections import namedtuple


class Certificate(namedtuple('Certificate', ('txhash', 'nout', 'claim_id', 'name', 'private_key'))):
    pass
