from collections import namedtuple


class Certificate(namedtuple('Certificate', ('txid', 'nout', 'claim_id', 'name', 'private_key'))):
    pass
