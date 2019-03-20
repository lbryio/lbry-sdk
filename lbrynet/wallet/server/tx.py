from torba.server.tx import Deserializer
from lbrynet.wallet.server.opcodes import decode_claim_script
from lbrynet.wallet.server.model import TxClaimOutput, LBRYTx


class LBRYDeserializer(Deserializer):

    def _read_output(self):
        value = self._read_le_int64()
        script = self._read_varbytes()  # pk_script
        claim = decode_claim_script(script)
        claim = claim[0] if claim else None
        return TxClaimOutput(value, script, claim)

    def read_tx(self):
        return LBRYTx(
            self._read_le_int32(),  # version
            self._read_inputs(),    # inputs
            self._read_outputs(),   # outputs
            self._read_le_uint32()  # locktime
        )
