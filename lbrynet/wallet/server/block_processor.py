import time

from torba.server.block_processor import BlockProcessor

from lbrynet.schema.claim import Claim
from lbrynet.wallet.server.db import SQLDB


class Timer:

    def __init__(self, name):
        self.name = name
        self.total = 0
        self.count = 0
        self.sub_timers = {}
        self._last_start = None

    def add_timer(self, name):
        if name not in self.sub_timers:
            self.sub_timers[name] = Timer(name)
        return self.sub_timers[name]

    def run(self, func, *args, forward_timer=False, timer_name=None, **kwargs):
        t = self.add_timer(timer_name or func.__name__)
        t.start()
        try:
            if forward_timer:
                return func(*args, **kwargs, timer=t)
            else:
                return func(*args, **kwargs)
        finally:
            t.stop()

    def start(self):
        self._last_start = time.time()
        return self

    def stop(self):
        self.total += (time.time() - self._last_start)
        self.count += 1
        self._last_start = None
        return self

    def show(self, depth=0, height=None):
        if depth == 0:
            print('='*100)
            if height is not None:
                print(f'STATISTICS AT HEIGHT {height}')
                print('='*100)
        else:
            print(
                f"{'  '*depth} {self.total/60:4.2f}mins {self.name}"
                # f"{self.total/self.count:.5f}sec/call, "
            )
        for sub_timer in self.sub_timers.values():
            sub_timer.show(depth+1)
        if depth == 0:
            print('='*100)


class LBRYBlockProcessor(BlockProcessor):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.env.coin.NET == "regtest":
            self.prefetcher.polling_delay = 0.5
        self.should_validate_signatures = self.env.boolean('VALIDATE_CLAIM_SIGNATURES', False)
        self.logger.info(f"LbryumX Block Processor - Validating signatures: {self.should_validate_signatures}")
        self.sql: SQLDB = self.db.sql
        self.timer = Timer('BlockProcessor')

    def advance_blocks(self, blocks):
        self.sql.begin()
        try:
            self.timer.run(super().advance_blocks, blocks)
        except:
            self.logger.exception(f'Error while advancing transaction in new block.')
            raise
        finally:
            self.sql.commit()

    def advance_txs(self, height, txs):
        timer = self.timer.sub_timers['advance_blocks']
        undo = timer.run(super().advance_txs, height, txs, timer_name='super().advance_txs')
        timer.run(self.sql.advance_txs, height, txs, forward_timer=True)
        if height % 10000 == 0:
            self.timer.show(height=height)
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
