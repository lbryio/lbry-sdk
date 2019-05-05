import msgpack
import struct

import time
from torba.server.hash import hash_to_hex_str

from torba.server.db import DB

from lbrynet.wallet.server.model import ClaimInfo


class LBRYDB(DB):

    def __init__(self, *args, **kwargs):
        self.claim_cache = {}
        self.claims_signed_by_cert_cache = {}
        self.outpoint_to_claim_id_cache = {}
        self.canonical_url_cache = {}
        self.claims_db = self.signatures_db = self.outpoint_to_claim_id_db = self.claim_undo_db = None
        self.canonical_url_db = None
        # stores deletes not yet flushed to disk
        self.pending_abandons = {}
        super().__init__(*args, **kwargs)

    def close(self):
        self.batched_flush_claims()
        self.claims_db.close()
        self.signatures_db.close()
        self.outpoint_to_claim_id_db.close()
        self.canonical_url_db.close()
        self.claim_undo_db.close()
        self.utxo_db.close()
        super().close()

    async def _open_dbs(self, for_sync, compacting):
        await super()._open_dbs(for_sync=for_sync, compacting=compacting)
        def log_reason(message, is_for_sync):
            reason = 'sync' if is_for_sync else 'serving'
            self.logger.info('{} for {}'.format(message, reason))

        if self.claims_db:
            if self.claims_db.for_sync == for_sync:
                return
            log_reason('closing claim DBs to re-open', for_sync)
            self.claims_db.close()
            self.signatures_db.close()
            self.outpoint_to_claim_id_db.close()
            self.claim_undo_db.close()
            self.canonical_url_db.close()
        self.claims_db = self.db_class('claims', for_sync)
        self.signatures_db = self.db_class('signatures', for_sync)
        self.outpoint_to_claim_id_db = self.db_class('outpoint_claim_id', for_sync)
        self.claim_undo_db = self.db_class('claim_undo', for_sync)
        self.canonical_url_db = self.db_class('canonical_url_db', for_sync)
        log_reason('opened claim DBs', self.claims_db.for_sync)

    def flush_dbs(self, flush_data, flush_utxos, estimate_txs_remaining):
        # flush claims together with utxos as they are parsed together
        self.batched_flush_claims()
        return super().flush_dbs(flush_data, flush_utxos, estimate_txs_remaining)

    def batched_flush_claims(self):
        with self.claims_db.write_batch() as claims_batch:
            with self.signatures_db.write_batch() as signed_claims_batch:
                with self.outpoint_to_claim_id_db.write_batch() as outpoint_batch:
                    with self.canonical_url_db.write_batch() as canonical_url_batch:
                        self.flush_claims(claims_batch, signed_claims_batch, outpoint_batch, canonical_url_batch)

    def flush_claims(self, batch, signed_claims_batch, outpoint_batch, canonical_url_batch):
        flush_start = time.time()
        write_claim, write_cert = batch.put, signed_claims_batch.put
        write_outpoint = outpoint_batch.put
        write_canonical_url = canonical_url_batch.put
        delete_claim, delete_outpoint = batch.delete, outpoint_batch.delete
        delete_cert = signed_claims_batch.delete
        for claim_id, outpoints in self.pending_abandons.items():
            claim = self.get_claim_info(claim_id)
            if claim.cert_id:
                self.remove_claim_from_certificate_claims(claim.cert_id, claim_id)
            self.remove_certificate(claim_id)
            self.claim_cache[claim_id] = None
            for txid, tx_index in outpoints:
                self.put_claim_id_for_outpoint(txid, tx_index, None)
        for key, claim in self.claim_cache.items():
            if claim:
                write_claim(key, claim)
            else:
                delete_claim(key)
        for cert_id, claims in self.claims_signed_by_cert_cache.items():
            if not claims:
                delete_cert(cert_id)
            else:
                write_cert(cert_id, msgpack.dumps(claims))
        for key, claim_id in self.outpoint_to_claim_id_cache.items():
            if claim_id:
                write_outpoint(key, claim_id)
            else:
                delete_outpoint(key)
        for key, claim_id in self.canonical_url_cache.items():
            if claim_id:
                write_canonical_url(key, claim_id)
        self.logger.info('flushed at height {:,d} with {:,d} claims, {:,d} outpoints '
                         'and {:,d} certificates added while {:,d} were abandoned in {:.1f}s, committing...'
                         .format(self.db_height,
                                 len(self.claim_cache), len(self.outpoint_to_claim_id_cache),
                                 len(self.claims_signed_by_cert_cache), len(self.pending_abandons),
                                 time.time() - flush_start))
        self.claim_cache = {}
        self.claims_signed_by_cert_cache = {}
        self.outpoint_to_claim_id_cache = {}
        self.pending_abandons = {}
        self.canonical_url_cache = {}

    def assert_flushed(self, flush_data):
        super().assert_flushed(flush_data)
        assert not self.claim_cache
        assert not self.claims_signed_by_cert_cache
        assert not self.outpoint_to_claim_id_cache
        assert not self.pending_abandons
        assert not self.canonical_url_cache

    def abandon_spent(self, tx_hash, tx_idx):
        claim_id = self.get_claim_id_from_outpoint(tx_hash, tx_idx)
        if claim_id:
            self.logger.info("[!] Abandon: {}".format(hash_to_hex_str(claim_id)))
            self.pending_abandons.setdefault(claim_id, []).append((tx_hash, tx_idx,))
            return claim_id

    def put_claim_id_for_outpoint(self, tx_hash, tx_idx, claim_id):
        self.logger.info("[+] Adding outpoint: {}:{} for {}.".format(hash_to_hex_str(tx_hash), tx_idx,
                                                                     hash_to_hex_str(claim_id) if claim_id else None))
        self.outpoint_to_claim_id_cache[tx_hash + struct.pack('>I', tx_idx)] = claim_id

    def remove_claim_id_for_outpoint(self, tx_hash, tx_idx):
        self.logger.info("[-] Remove outpoint: {}:{}.".format(hash_to_hex_str(tx_hash), tx_idx))
        self.outpoint_to_claim_id_cache[tx_hash + struct.pack('>I', tx_idx)] = None

    def get_claim_id_from_outpoint(self, tx_hash, tx_idx):
        key = tx_hash + struct.pack('>I', tx_idx)
        return self.outpoint_to_claim_id_cache.get(key) or self.outpoint_to_claim_id_db.get(key)

    def get_signed_claim_ids_by_cert_id(self, cert_id):
        if cert_id in self.claims_signed_by_cert_cache:
            return self.claims_signed_by_cert_cache[cert_id]
        db_claims = self.signatures_db.get(cert_id)
        return msgpack.loads(db_claims, use_list=True) if db_claims else []

    def put_claim_id_signed_by_cert_id(self, cert_id, claim_id):
        msg = "[+] Adding signature: {} - {}".format(hash_to_hex_str(claim_id), hash_to_hex_str(cert_id))
        self.logger.info(msg)
        certs = self.get_signed_claim_ids_by_cert_id(cert_id)
        certs.append(claim_id)
        self.claims_signed_by_cert_cache[cert_id] = certs

    def remove_certificate(self, cert_id):
        msg = "[-] Removing certificate: {}".format(hash_to_hex_str(cert_id))
        self.logger.info(msg)
        self.claims_signed_by_cert_cache[cert_id] = []

    def remove_claim_from_certificate_claims(self, cert_id, claim_id):
        msg = "[-] Removing signature: {} - {}".format(hash_to_hex_str(claim_id), hash_to_hex_str(cert_id))
        self.logger.info(msg)
        certs = self.get_signed_claim_ids_by_cert_id(cert_id)
        if claim_id in certs:
            certs.remove(claim_id)
        self.claims_signed_by_cert_cache[cert_id] = certs

    def get_claim_info(self, claim_id):
        serialized = self.claim_cache.get(claim_id) or self.claims_db.get(claim_id)
        return ClaimInfo.from_serialized(serialized) if serialized else None

    def get_full_claim_id_from_canonical(self, claim_name, short_id):
        uri = "{}#{}".format(claim_name, short_id).encode()
        full_claim_id = self.canonical_url_cache.get(uri) or self.canonical_url_db.get(uri)
        return full_claim_id

    def put_canonical_url(self, claim_id, claim_info):
        self.logger.info("[+] Adding canonical url for: {}".format(hash_to_hex_str(claim_id)))
        claim_name = claim_info.name.decode()
        claim_id = hash_to_hex_str(claim_id)
        separator = '#'
        for i in range(len(claim_id)):
            canonical_url = separator.join([claim_name, claim_id[:i+1]])
            if not (self.canonical_url_cache.get(canonical_url) or self.canonical_url_db.get(canonical_url.encode())):
                self.canonical_url_cache[canonical_url.encode()] = claim_id.encode()
                break

    def put_claim_info(self, claim_id, claim_info):
        self.logger.info("[+] Adding claim info for: {}".format(hash_to_hex_str(claim_id)))
        self.claim_cache[claim_id] = claim_info.serialized

    def get_update_input(self, claim_id, inputs):
        claim_info = self.get_claim_info(claim_id)
        if not claim_info:
            return False
        for input in inputs:
            if (input.txo_ref.tx_ref.hash, input.txo_ref.position) == (claim_info.txid, claim_info.nout):
                return input
        return False

    def write_undo(self, pending_undo):
        with self.claim_undo_db.write_batch() as writer:
            for height, undo_info in pending_undo:
                writer.put(struct.pack(">I", height), msgpack.dumps(undo_info))
