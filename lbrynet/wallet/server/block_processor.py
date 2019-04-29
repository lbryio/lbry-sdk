from torba.server.block_processor import BlockProcessor

from lbrynet.schema.claim import Claim
from lbrynet.wallet.server.db import SQLDB


class LBRYBlockProcessor(BlockProcessor):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.env.coin.NET == "regtest":
            self.prefetcher.polling_delay = 0.5
        self.should_validate_signatures = self.env.boolean('VALIDATE_CLAIM_SIGNATURES', False)
        self.logger.info(f"LbryumX Block Processor - Validating signatures: {self.should_validate_signatures}")
        self.sql: SQLDB = self.db.sql

    def advance_blocks(self, blocks):
        self.sql.begin()
        try:
            super().advance_blocks(blocks)
        except:
            self.logger.exception(f'Error while advancing transaction in new block.')
            raise
        finally:
            self.sql.commit()

    def advance_txs(self, height, txs):
        undo = super().advance_txs(height, txs)
        self.sql.advance_txs(height, txs)
        return undo

    def _checksig(self, value, address):
        try:
            claim_dict = Claim.from_bytes(value)
            cert_id = claim_dict.signing_channel_hash
            if not self.should_validate_signatures:
                return cert_id
            if cert_id:
                cert_claim = self.db.get_claim_info(cert_id)
                if cert_claim:
                    certificate = Claim.from_bytes(cert_claim.value)
                    claim_dict.validate_signature(address, certificate)
                    return cert_id
        except Exception:
            pass
