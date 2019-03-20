from collections import namedtuple
import msgpack
# Classes representing data and their serializers, if any.


class ClaimInfo(namedtuple("NameClaim", "name value txid nout amount address height cert_id")):
    '''Claim information as its stored on database'''

    @classmethod
    def from_serialized(cls, serialized):
        return cls(*msgpack.loads(serialized))

    @property
    def serialized(self):
        return msgpack.dumps(self)
