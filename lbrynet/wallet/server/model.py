from collections import namedtuple
import msgpack
from torba.server.util import cachedproperty
# Classes representing data and their serializers, if any.


class ClaimInfo(namedtuple("NameClaim", "name value txid nout amount address height cert_id")):
    '''Claim information as its stored on database'''

    @classmethod
    def from_serialized(cls, serialized):
        return cls(*msgpack.loads(serialized))

    @property
    def serialized(self):
        return msgpack.dumps(self)


class NameClaim(namedtuple("NameClaim", "name value")):
    pass


class ClaimUpdate(namedtuple("ClaimUpdate", "name claim_id value")):
    pass


class ClaimSupport(namedtuple("ClaimSupport", "name claim_id")):
    pass


class LBRYTx(namedtuple("Tx", "version inputs outputs locktime")):
    '''Transaction that can contain claim, update or support in its outputs.'''

    @cachedproperty
    def is_coinbase(self):
        return self.inputs[0].is_coinbase

    @cachedproperty
    def has_claims(self):
        for output in self.outputs:
            if output.claim:
                return True
        return False


class TxClaimOutput(namedtuple("TxClaimOutput", "value pk_script claim")):
    pass
