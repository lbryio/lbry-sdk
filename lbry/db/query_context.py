import os
import time
import multiprocessing as mp
from enum import Enum
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from contextvars import ContextVar

from sqlalchemy import create_engine, inspect, bindparam, case
from sqlalchemy.engine import Engine, Connection

from lbry.event import EventQueuePublisher
from lbry.blockchain.ledger import Ledger
from lbry.blockchain.transaction import Transaction, Output, Input
from lbry.schema.tags import clean_tags
from lbry.schema.result import Censor
from lbry.schema.mime_types import guess_stream_type

from .utils import pg_insert, chunk
from .tables import Block, TX, TXO, TXI, Claim, Tag, Takeover, Support
from .constants import TXO_TYPES, STREAM_TYPES


_context: ContextVar['QueryContext'] = ContextVar('_context')


@dataclass
class QueryContext:
    engine: Engine
    connection: Connection
    ledger: Ledger
    message_queue: mp.Queue
    stop_event: mp.Event
    stack: List[List]
    metrics: Dict
    is_tracking_metrics: bool
    blocked_streams: Dict
    blocked_channels: Dict
    filtered_streams: Dict
    filtered_channels: Dict
    pid: int

    # QueryContext __enter__/__exit__ state
    print_timers: List
    current_timer_name: Optional[str] = None
    current_timer_time: float = 0
    current_progress: Optional['ProgressContext'] = None

    @property
    def is_postgres(self):
        return self.connection.dialect.name == 'postgresql'

    @property
    def is_sqlite(self):
        return self.connection.dialect.name == 'sqlite'

    def raise_unsupported_dialect(self):
        raise RuntimeError(f'Unsupported database dialect: {self.connection.dialect.name}.')

    def get_resolve_censor(self) -> Censor:
        return Censor(self.blocked_streams, self.blocked_channels)

    def get_search_censor(self) -> Censor:
        return Censor(self.filtered_streams, self.filtered_channels)

    def execute(self, sql, *args):
        return self.connection.execute(sql, *args)

    def fetchone(self, sql, *args):
        row = self.connection.execute(sql, *args).fetchone()
        return dict(row._mapping) if row else row

    def fetchall(self, sql, *args):
        rows = self.connection.execute(sql, *args).fetchall()
        return [dict(row._mapping) for row in rows]

    def insert_or_ignore(self, table):
        if self.is_sqlite:
            return table.insert().prefix_with("OR IGNORE")
        elif self.is_postgres:
            return pg_insert(table).on_conflict_do_nothing()
        else:
            self.raise_unsupported_dialect()

    def insert_or_replace(self, table, replace):
        if self.is_sqlite:
            return table.insert().prefix_with("OR REPLACE")
        elif self.is_postgres:
            insert = pg_insert(table)
            return insert.on_conflict_do_update(
                table.primary_key, set_={col: getattr(insert.excluded, col) for col in replace}
            )
        else:
            self.raise_unsupported_dialect()

    def has_table(self, table):
        return inspect(self.engine).has_table(table)

    def get_bulk_loader(self) -> 'BulkLoader':
        return BulkLoader(self)

    def reset_metrics(self):
        self.stack = []
        self.metrics = {}

    def with_timer(self, timer_name: str) -> 'QueryContext':
        self.current_timer_name = timer_name
        return self

    def __enter__(self) -> 'QueryContext':
        self.current_timer_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.current_timer_name and self.current_timer_name in self.print_timers:
            elapsed = time.perf_counter() - self.current_timer_time
            print(f"{self.print_timers} in {elapsed:.6f}s", flush=True)
        self.current_timer_name = None
        self.current_timer_time = 0
        self.current_progress = None


def context(with_timer: str = None) -> 'QueryContext':
    if isinstance(with_timer, str):
        return _context.get().with_timer(with_timer)
    return _context.get()


def initialize(
        ledger: Ledger, message_queue: mp.Queue, stop_event: mp.Event,
        track_metrics=False, block_and_filter=None, print_timers=None):
    url = ledger.conf.db_url_or_default
    engine = create_engine(url)
    connection = engine.connect()
    if block_and_filter is not None:
        blocked_streams, blocked_channels, filtered_streams, filtered_channels = block_and_filter
    else:
        blocked_streams = blocked_channels = filtered_streams = filtered_channels = {}
    _context.set(
        QueryContext(
            pid=os.getpid(),
            engine=engine, connection=connection,
            ledger=ledger, message_queue=message_queue, stop_event=stop_event,
            stack=[], metrics={}, is_tracking_metrics=track_metrics,
            blocked_streams=blocked_streams, blocked_channels=blocked_channels,
            filtered_streams=filtered_streams, filtered_channels=filtered_channels,
            print_timers=print_timers or []
        )
    )


def uninitialize():
    ctx = _context.get(None)
    if ctx is not None:
        if ctx.connection:
            ctx.connection.close()
        _context.set(None)


class ProgressUnit(Enum):
    NONE = "", None
    TASKS = "tasks", None
    BLOCKS = "blocks", Block
    TXS = "txs", TX
    TAKEOVERS = "takeovers", Takeover
    TXIS = "txis", TXI
    CLAIMS = "claims", Claim
    SUPPORTS = "supports", Support

    def __new__(cls, value, table):
        next_id = len(cls.__members__) + 1
        obj = object.__new__(cls)
        obj._value_ = next_id
        obj.label = value
        obj.table = table
        return obj


class Event(Enum):
    # full node specific sync events
    BLOCK_READ = "blockchain.sync.block.read", ProgressUnit.BLOCKS
    BLOCK_SAVE = "blockchain.sync.block.save", ProgressUnit.TXS
    BLOCK_DONE = "blockchain.sync.block.done", ProgressUnit.TASKS
    CLAIM_TRIE = "blockchain.sync.claim.trie", ProgressUnit.TAKEOVERS
    CLAIM_META = "blockchain.sync.claim.update", ProgressUnit.CLAIMS
    CLAIM_CALC = "blockchain.sync.claim.totals", ProgressUnit.CLAIMS
    CLAIM_SIGN = "blockchain.sync.claim.signatures", ProgressUnit.CLAIMS
    SUPPORT_META = "blockchain.sync.support.update", ProgressUnit.SUPPORTS
    SUPPORT_SIGN = "blockchain.sync.support.signatures", ProgressUnit.SUPPORTS
    TRENDING_CALC = "blockchain.sync.trending", ProgressUnit.BLOCKS
    TAKEOVER_INSERT = "blockchain.sync.takeover.insert", ProgressUnit.TAKEOVERS

    # full node + light client sync events
    INPUT_UPDATE = "db.sync.input", ProgressUnit.TXIS
    CLAIM_DELETE = "db.sync.claim.delete", ProgressUnit.CLAIMS
    CLAIM_INSERT = "db.sync.claim.insert", ProgressUnit.CLAIMS
    CLAIM_UPDATE = "db.sync.claim.update", ProgressUnit.CLAIMS
    SUPPORT_DELETE = "db.sync.support.delete", ProgressUnit.SUPPORTS
    SUPPORT_INSERT = "db.sync.support.insert", ProgressUnit.SUPPORTS

    def __new__(cls, value, unit: ProgressUnit):
        next_id = len(cls.__members__) + 1
        obj = object.__new__(cls)
        obj._value_ = next_id
        obj.label = value
        obj.unit = unit
        return obj


class ProgressPublisher(EventQueuePublisher):

    def message_to_event(self, message):
        event = Event(message[0])  # pylint: disable=no-value-for-parameter
        d = {
            "event": event.label,
            "data": {
                "pid": message[1],
                "step": message[2],
                "total": message[3],
                "unit": event.unit.label
            }
        }
        if len(message) > 4 and isinstance(message[4], dict):
            d['data'].update(message[4])
        return d


class BreakProgress(Exception):
    """Break out of progress when total is 0."""


class ProgressContext:

    def __init__(self, ctx: QueryContext, event: Event, step_size=1):
        self.ctx = ctx
        self.event = event
        self.extra = None
        self.step_size = step_size
        self.last_step = -1
        self.total = 0

    def __enter__(self) -> 'ProgressContext':
        self.ctx.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type == BreakProgress:
            return True
        self.ctx.message_queue.put(self.get_event_args(self.total))
        return self.ctx.__exit__(exc_type, exc_val, exc_tb)

    def start(self, total, extra=None):
        if not total:
            raise BreakProgress
        self.total = total
        if extra is not None:
            self.extra = extra
        self.step(0)

    def step(self, done):
        send_condition = (
            # enforce step rate
            (self.step_size == 1 or done % self.step_size == 0) and
            # deduplicate finish event by not sending a step where done == total
            done < self.total and
            # deduplicate same step
            done != self.last_step
        )
        if send_condition:
            self.ctx.message_queue.put_nowait(self.get_event_args(done))
            self.last_step = done

    def get_event_args(self, done):
        if self.extra is not None:
            return self.event.value, self.ctx.pid, done, self.total, self.extra
        return self.event.value, self.ctx.pid, done, self.total


def progress(e: Event, step_size=1) -> ProgressContext:
    ctx = context(e.label)
    ctx.current_progress = ProgressContext(ctx, e, step_size=step_size)
    return ctx.current_progress


class BulkLoader:

    def __init__(self, ctx: QueryContext):
        self.ctx = ctx
        self.ledger = ctx.ledger
        self.blocks = []
        self.txs = []
        self.txos = []
        self.txis = []
        self.supports = []
        self.claims = []
        self.tags = []
        self.update_claims = []
        self.delete_tags = []

    @staticmethod
    def block_to_row(block: Block) -> dict:
        return {
            'block_hash': block.block_hash,
            'previous_hash': block.prev_block_hash,
            'file_number': block.file_number,
            'height': 0 if block.is_first_block else block.height,
            'timestamp': block.timestamp,
        }

    @staticmethod
    def tx_to_row(block_hash: bytes, tx: Transaction) -> dict:
        row = {
            'tx_hash': tx.hash,
            'block_hash': block_hash,
            'raw': tx.raw,
            'height': tx.height,
            'position': tx.position,
            'is_verified': tx.is_verified,
            'timestamp': tx.timestamp,
            'day': tx.day,
            'purchased_claim_hash': None,
        }
        txos = tx.outputs
        if len(txos) >= 2 and txos[1].can_decode_purchase_data:
            txos[0].purchase = txos[1]
            row['purchased_claim_hash'] = txos[1].purchase_data.claim_hash
        return row

    @staticmethod
    def txi_to_row(tx: Transaction, txi: Input) -> dict:
        return {
            'tx_hash': tx.hash,
            'txo_hash': txi.txo_ref.hash,
            'position': txi.position,
        }

    def txo_to_row(self, tx: Transaction, txo: Output) -> dict:
        row = {
            'tx_hash': tx.hash,
            'txo_hash': txo.hash,
            'address': txo.get_address(self.ledger) if txo.has_address else None,
            'position': txo.position,
            'amount': txo.amount,
            'height': tx.height,
            'script_offset': txo.script.offset,
            'script_length': txo.script.length,
            'txo_type': 0,
            'claim_id': None,
            'claim_hash': None,
            'claim_name': None,
            'channel_hash': None,
            'public_key': None,
            'public_key_hash': None
        }
        if txo.is_claim:
            if txo.can_decode_claim:
                claim = txo.claim
                row['txo_type'] = TXO_TYPES.get(claim.claim_type, TXO_TYPES['stream'])
                if claim.is_signed:
                    row['channel_hash'] = claim.signing_channel_hash
                if claim.is_channel:
                    row['public_key'] = claim.channel.public_key_bytes
                    row['public_key_hash'] = self.ledger.address_to_hash160(
                        self.ledger.public_key_to_address(claim.channel.public_key_bytes)
                    )
            else:
                row['txo_type'] = TXO_TYPES['stream']
        elif txo.is_support:
            row['txo_type'] = TXO_TYPES['support']
            if txo.can_decode_support:
                claim = txo.support
                if claim.is_signed:
                    row['channel_hash'] = claim.signing_channel_hash
        elif txo.purchase is not None:
            row['txo_type'] = TXO_TYPES['purchase']
            row['claim_id'] = txo.purchased_claim_id
            row['claim_hash'] = txo.purchased_claim_hash
        if txo.script.is_claim_involved:
            row['claim_id'] = txo.claim_id
            row['claim_hash'] = txo.claim_hash
            try:
                claim_name = txo.claim_name
                if '\x00' in claim_name:
                    # log.error(f"Name for claim {txo.claim_id} contains a NULL (\\x00) character, skipping.")
                    pass
                else:
                    row['claim_name'] = claim_name
            except UnicodeDecodeError:
                # log.error(f"Name for claim {txo.claim_id} contains invalid unicode, skipping.")
                pass
        return row

    def claim_to_rows(self, txo: Output) -> Tuple[dict, List]:
        try:
            assert txo.claim_name
            assert txo.normalized_name
        except Exception:
            #self.logger.exception(f"Could not decode claim name for {tx.id}:{txo.position}.")
            return {}, []
        tx = txo.tx_ref.tx
        claim_hash = txo.claim_hash
        claim_record = {
            'claim_hash': claim_hash,
            'claim_id': txo.claim_id,
            'claim_name': txo.claim_name,
            'normalized': txo.normalized_name,
            'address': txo.get_address(self.ledger),
            'txo_hash': txo.ref.hash,
            'amount': txo.amount,
            'timestamp': tx.timestamp,
            'release_time': None,
            'height': tx.height,
            'title': None,
            'author': None,
            'description': None,
            'claim_type': None,
            # streams
            'stream_type': None,
            'media_type': None,
            'fee_amount': 0,
            'fee_currency': None,
            'duration': None,
            # reposts
            'reposted_claim_hash': None,
            # signed claims
            'channel_hash': None,
            'signature': None,
            'signature_digest': None,
            'is_signature_valid': None,
        }

        try:
            claim = txo.claim
        except Exception:
            #self.logger.exception(f"Could not parse claim protobuf for {tx.id}:{txo.position}.")
            return claim_record, []

        if claim.is_stream:
            claim_record['claim_type'] = TXO_TYPES['stream']
            claim_record['stream_type'] = STREAM_TYPES[guess_stream_type(claim_record['media_type'])]
            claim_record['media_type'] = claim.stream.source.media_type
            claim_record['title'] = claim.stream.title
            claim_record['description'] = claim.stream.description
            claim_record['author'] = claim.stream.author
            if claim.stream.video and claim.stream.video.duration:
                claim_record['duration'] = claim.stream.video.duration
            if claim.stream.audio and claim.stream.audio.duration:
                claim_record['duration'] = claim.stream.audio.duration
            if claim.stream.release_time:
                claim_record['release_time'] = claim.stream.release_time
            if claim.stream.has_fee:
                fee = claim.stream.fee
                if isinstance(fee.currency, str):
                    claim_record['fee_currency'] = fee.currency.lower()
                if isinstance(fee.amount, Decimal):
                    claim_record['fee_amount'] = int(fee.amount*1000)
        elif claim.is_repost:
            claim_record['claim_type'] = TXO_TYPES['repost']
            claim_record['reposted_claim_hash'] = claim.repost.reference.claim_hash
        elif claim.is_channel:
            claim_record['claim_type'] = TXO_TYPES['channel']
        if claim.is_signed:
            claim_record['channel_hash'] = claim.signing_channel_hash
            claim_record['signature'] = txo.get_encoded_signature()
            claim_record['signature_digest'] = txo.get_signature_digest(None)

        tags = [
            {'claim_hash': claim_hash, 'tag': tag} for tag in clean_tags(claim.message.tags)
        ]

        return claim_record, tags

    def add_block(self, block: Block, add_claims_supports: set = None):
        self.blocks.append(self.block_to_row(block))
        for tx in block.txs:
            self.add_transaction(block.block_hash, tx, add_claims_supports)
        return self

    def add_transaction(self, block_hash: bytes, tx: Transaction, add_claims_supports: set = None):
        self.txs.append(self.tx_to_row(block_hash, tx))
        for txi in tx.inputs:
            if txi.coinbase is None:
                self.txis.append(self.txi_to_row(tx, txi))
        for txo in tx.outputs:
            self.txos.append(self.txo_to_row(tx, txo))
            if add_claims_supports:
                if txo.is_support and txo.hash in add_claims_supports:
                    self.add_support(txo)
                elif txo.is_claim and txo.hash in add_claims_supports:
                    self.add_claim(txo)
        return self

    def add_support(self, txo: Output):
        tx = txo.tx_ref.tx
        claim_hash = txo.claim_hash
        support_record = {
            'txo_hash': txo.ref.hash,
            'claim_hash': claim_hash,
            'address': txo.get_address(self.ledger),
            'amount': txo.amount,
            'height': tx.height,
            'emoji': None,
            'channel_hash': None,
            'signature': None,
            'signature_digest': None,
        }
        self.supports.append(support_record)
        support = txo.can_decode_support
        if support:
            support_record['emoji'] = support.emoji
            if support.is_signed:
                support_record['channel_hash'] = support.signing_channel_hash
                support_record['signature'] = txo.get_encoded_signature()
                support_record['signature_digest'] = txo.get_signature_digest(None)

    def add_claim(self, txo: Output):
        claim, tags = self.claim_to_rows(txo)
        if claim:
            tx = txo.tx_ref.tx
            if txo.script.is_claim_name:
                claim['creation_height'] = tx.height
                claim['creation_timestamp'] = tx.timestamp
            self.claims.append(claim)
            self.tags.extend(tags)
        return self

    def update_claim(self, txo: Output):
        claim, tags = self.claim_to_rows(txo)
        if claim:
            claim['claim_hash_'] = claim.pop('claim_hash')
            self.update_claims.append(claim)
            self.delete_tags.append({'claim_hash_': claim['claim_hash_']})
            self.tags.extend(tags)
        return self

    def save(self, batch_size=10000):
        queries = (
            (Block.insert(), self.blocks),
            (TX.insert(), self.txs),
            (TXO.insert(), self.txos),
            (TXI.insert(), self.txis),
            (Claim.insert(), self.claims),
            (Tag.delete().where(Tag.c.claim_hash == bindparam('claim_hash_')), self.delete_tags),
            (Claim.update().where(Claim.c.claim_hash == bindparam('claim_hash_')), self.update_claims),
            (Tag.insert(), self.tags),
            (Support.insert(), self.supports),
        )

        p = self.ctx.current_progress
        done = row_scale = 0
        if p:
            unit_table = p.event.unit.table
            progress_total, row_total = 0, sum(len(q[1]) for q in queries)
            for sql, rows in queries:
                if sql.table == unit_table:
                    progress_total += len(rows)
            if not progress_total:
                assert row_total == 0, "Rows used for progress are empty but other rows present."
                return
            row_scale = row_total / progress_total
            p.start(progress_total)

        execute = self.ctx.connection.execute
        for sql, rows in queries:
            for chunk_rows in chunk(rows, batch_size):
                execute(sql, chunk_rows)
                if p:
                    done += int(len(chunk_rows)/row_scale)
                    p.step(done)
