import hashlib
import struct
from binascii import unhexlify

import msgpack
from torba.server.hash import hash_to_hex_str

from torba.server.block_processor import BlockProcessor
from lbrynet.schema.uri import parse_lbry_uri
from lbrynet.schema.decode import smart_decode

from lbrynet.extras.wallet.server.model import NameClaim, ClaimInfo, ClaimUpdate, ClaimSupport


class LBRYBlockProcessor(BlockProcessor):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.env.coin.NET == "regtest":
            self.prefetcher.polling_delay = 0.5

        self.should_validate_signatures = self.env.boolean('VALIDATE_CLAIM_SIGNATURES', False)
        self.logger.info("LbryumX Block Processor - Validating signatures: {}".format(self.should_validate_signatures))

    def advance_blocks(self, blocks):
        # save height, advance blocks as usual, then hook our claim tx processing
        height = self.height + 1
        super().advance_blocks(blocks)
        pending_undo = []
        for index, block in enumerate(blocks):
            undo = self.advance_claim_txs(block.transactions, height + index)
            pending_undo.append((height+index, undo,))
        self.db.write_undo(pending_undo)

    def advance_claim_txs(self, txs, height):
        # TODO: generate claim undo info!
        undo_info = []
        add_undo = undo_info.append
        update_inputs = set()
        for tx, txid in txs:
            update_inputs.clear()
            if tx.has_claims:
                for index, output in enumerate(tx.outputs):
                    claim = output.claim
                    if isinstance(claim, NameClaim):
                        add_undo(self.advance_claim_name_transaction(output, height, txid, index))
                    elif isinstance(claim, ClaimUpdate):
                        update_input = self.db.get_update_input(claim, tx.inputs)
                        if update_input:
                            update_inputs.add(update_input)
                            add_undo(self.advance_update_claim(output, height, txid, index))
                        else:
                            info = (hash_to_hex_str(txid), hash_to_hex_str(claim.claim_id),)
                            self.logger.error("REJECTED: {} updating {}".format(*info))
                    elif isinstance(claim, ClaimSupport):
                        self.advance_support(claim, txid, index, height, output.value)
            for txin in tx.inputs:
                if txin not in update_inputs:
                    abandoned_claim_id = self.db.abandon_spent(txin.prev_hash, txin.prev_idx)
                    if abandoned_claim_id:
                        add_undo((abandoned_claim_id, self.db.get_claim_info(abandoned_claim_id)))
        return undo_info

    def advance_update_claim(self, output, height, txid, nout):
        claim_id = output.claim.claim_id
        claim_info = self.claim_info_from_output(output, txid, nout, height)
        old_claim_info = self.db.get_claim_info(claim_id)
        self.db.put_claim_id_for_outpoint(old_claim_info.txid, old_claim_info.nout, None)
        if old_claim_info.cert_id:
            self.db.remove_claim_from_certificate_claims(old_claim_info.cert_id, claim_id)
        if claim_info.cert_id:
            self.db.put_claim_id_signed_by_cert_id(claim_info.cert_id, claim_id)
        self.db.put_claim_info(claim_id, claim_info)
        self.db.put_claim_id_for_outpoint(txid, nout, claim_id)
        return claim_id, old_claim_info

    def advance_claim_name_transaction(self, output, height, txid, nout):
        claim_id = claim_id_hash(txid, nout)
        claim_info = self.claim_info_from_output(output, txid, nout, height)
        if claim_info.cert_id:
            self.db.put_claim_id_signed_by_cert_id(claim_info.cert_id, claim_id)
        self.db.put_claim_info(claim_id, claim_info)
        self.db.put_claim_id_for_outpoint(txid, nout, claim_id)
        return claim_id, None

    def backup_from_undo_info(self, claim_id, undo_claim_info):
        """
        Undo information holds a claim state **before** a transaction changes it
        There are 4 possibilities when processing it, of which only 3 are valid ones:
         1. the claim is known and the undo info has info, it was an update
         2. the claim is known and the undo info doesn't hold any info, it was claimed
         3. the claim in unknown and the undo info has info, it was abandoned
         4. the claim is unknown and the undo info does't hold info, error!
        """

        undo_claim_info = ClaimInfo(*undo_claim_info) if undo_claim_info else None
        current_claim_info = self.db.get_claim_info(claim_id)
        if current_claim_info and undo_claim_info:
            # update, remove current claim
            self.db.remove_claim_id_for_outpoint(current_claim_info.txid, current_claim_info.nout)
            if current_claim_info.cert_id:
                self.db.remove_claim_from_certificate_claims(current_claim_info.cert_id, claim_id)
        elif current_claim_info and not undo_claim_info:
            # claim, abandon it
            self.db.abandon_spent(current_claim_info.txid, current_claim_info.nout)
        elif not current_claim_info and undo_claim_info:
            # abandon, reclaim it (happens below)
            pass
        else:
            # should never happen, unless the database got into an inconsistent state
            raise Exception("Unexpected situation occurred on backup, this means the database is inconsistent. "
                            "Please report. Resetting the data folder (reindex) solves it for now.")
        if undo_claim_info:
            self.db.put_claim_info(claim_id, undo_claim_info)
            if undo_claim_info.cert_id:
                cert_id = self._checksig(undo_claim_info.name, undo_claim_info.value, undo_claim_info.address)
                self.db.put_claim_id_signed_by_cert_id(cert_id, claim_id)
            self.db.put_claim_id_for_outpoint(undo_claim_info.txid, undo_claim_info.nout, claim_id)

    def backup_txs(self, txs):
        self.logger.info("Reorg at height {} with {} transactions.".format(self.height, len(txs)))
        undo_info = msgpack.loads(self.db.claim_undo_db.get(struct.pack(">I", self.height)), use_list=False)
        for claim_id, undo_claim_info in reversed(undo_info):
            self.backup_from_undo_info(claim_id, undo_claim_info)
        return super().backup_txs(txs)

    def backup_blocks(self, raw_blocks):
        self.db.batched_flush_claims()
        super().backup_blocks(raw_blocks=raw_blocks)
        self.db.batched_flush_claims()

    async def flush(self, flush_utxos):
        self.db.batched_flush_claims()
        return await super().flush(flush_utxos)

    def advance_support(self, claim_support, txid, nout, height, amount):
        # TODO: check for more controller claim rules, like takeover or ordering
        pass

    def claim_info_from_output(self, output, txid, nout, height):
        amount = output.value
        address = self.coin.address_from_script(output.pk_script)
        name, value, cert_id = output.claim.name, output.claim.value, None
        assert txid and address
        cert_id = self._checksig(name, value, address)
        return ClaimInfo(name, value, txid, nout, amount, address, height, cert_id)

    def _checksig(self, name, value, address):
        try:
            parse_lbry_uri(name.decode())  # skip invalid names
            claim_dict = smart_decode(value)
            cert_id = unhexlify(claim_dict.certificate_id)[::-1]
            if not self.should_validate_signatures:
                return cert_id
            if cert_id:
                cert_claim = self.db.get_claim_info(cert_id)
                if cert_claim:
                    certificate = smart_decode(cert_claim.value)
                    claim_dict.validate_signature(address, certificate)
                    return cert_id
        except Exception as e:
            pass

def claim_id_hash(txid, n):
    # TODO: This should be in lbryschema
    packed = txid + struct.pack('>I', n)
    md = hashlib.new('ripemd160')
    md.update(hashlib.sha256(packed).digest())
    return md.digest()
