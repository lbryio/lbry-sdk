import os
import time
import functools
from io import BytesIO
import multiprocessing as mp
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from contextvars import ContextVar

from sqlalchemy import create_engine, inspect, bindparam, func, exists, case
from sqlalchemy.future import select
from sqlalchemy.engine import Engine, Connection
from sqlalchemy.sql import Insert
try:
    from pgcopy import CopyManager
except ImportError:
    CopyManager = None

from lbry.event import EventQueuePublisher
from lbry.blockchain.ledger import Ledger
from lbry.blockchain.transaction import Transaction, Output, Input
from lbry.schema.tags import clean_tags
from lbry.schema.result import Censor
from lbry.schema.mime_types import guess_stream_type

from .utils import pg_insert, chunk
from .tables import Block, TX, TXO, TXI, Claim, Tag, Support
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

    copy_managers: Dict[str, CopyManager] = field(default_factory=dict)

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

    def pg_copy(self, table, rows):
        connection = self.connection.connection
        copy_manager = self.copy_managers.get(table.name)
        if copy_manager is None:
            self.copy_managers[table.name] = copy_manager = CopyManager(
                self.connection.connection, table.name, rows[0].keys()
            )
        copy_manager.copy(map(dict.values, rows), BytesIO)
        connection.commit()

    def execute(self, sql, *args):
        return self.connection.execute(sql, *args)

    def fetchone(self, sql, *args):
        row = self.connection.execute(sql, *args).fetchone()
        return dict(row._mapping) if row else row

    def fetchall(self, sql, *args):
        rows = self.connection.execute(sql, *args).fetchall()
        return [dict(row._mapping) for row in rows]

    def fetchtotal(self, condition):
        sql = select(func.count('*').label('total')).where(condition)
        return self.fetchone(sql)['total']

    def fetchmax(self, column):
        sql = select(func.max(column).label('max_result'))
        return self.fetchone(sql)['max_result']

    def has_records(self, table):
        sql = select(exists([1], from_obj=table).label('result'))
        return self.fetchone(sql)['result']

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
        if ctx.engine:
            ctx.engine.dispose()
        _context.set(None)


class Event:
    _events: List['Event'] = []
    __slots__ = 'id', 'name', 'unit', 'step_size'

    def __init__(self, name: str, unit: str, step_size: int):
        self.name = name
        self.unit = unit
        self.step_size = step_size

    @classmethod
    def get_by_id(cls, event_id) -> 'Event':
        return cls._events[event_id]

    @classmethod
    def get_by_name(cls, name) -> 'Event':
        for event in cls._events:
            if event.name == name:
                return event

    @classmethod
    def add(cls, name: str, unit: str, step_size: int) -> 'Event':
        assert cls.get_by_name(name) is None, f"Event {name} already exists."
        event = cls(name, unit, step_size)
        cls._events.append(event)
        event.id = cls._events.index(event)
        return event


def event_emitter(name: str, unit: str, step_size=1):
    event = Event.add(name, unit, step_size)

    def wrapper(f):
        @functools.wraps(f)
        def with_progress(*args, **kwargs):
            with progress(event, step_size=step_size) as p:
                return f(*args, **kwargs, p=p)
        return with_progress

    return wrapper


class ProgressPublisher(EventQueuePublisher):

    def message_to_event(self, message):
        event = Event.get_by_id(message[0])
        d = {
            "event": event.name,
            "data": {
                "pid": message[1],
                "step": message[2],
                "total": message[3],
                "unit": event.unit
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
        self.ctx.message_queue.put(self.get_event_args(self.total))
        self.ctx.__exit__(exc_type, exc_val, exc_tb)
        if exc_type == BreakProgress:
            return True

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
            return self.event.id, self.ctx.pid, done, self.total, self.extra
        return self.event.id, self.ctx.pid, done, self.total


def progress(e: Event, step_size=1) -> ProgressContext:
    ctx = context(e.name)
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
            'height': tx.height,
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
            'signature': None,
            'signature_digest': None,
            'public_key': None,
            'public_key_hash': None
        }
        if txo.is_claim:
            if txo.can_decode_claim:
                claim = txo.claim
                row['txo_type'] = TXO_TYPES.get(claim.claim_type, TXO_TYPES['stream'])
                if claim.is_signed:
                    row['channel_hash'] = claim.signing_channel_hash
                    row['signature'] = txo.get_encoded_signature()
                    row['signature_digest'] = txo.get_signature_digest(self.ledger)
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
                row['claim_name'] = txo.claim_name.replace('\x00', '')
            except UnicodeDecodeError:
                pass
        return row

    def claim_to_rows(
            self, txo: Output, timestamp: int, staked_support_amount: int, staked_support_count: int,
            signature: bytes = None, signature_digest: bytes = None, channel_public_key: bytes = None,
            ) -> Tuple[dict, List]:

        d = {
            'claim_type': None,
            'address': txo.get_address(self.ledger),
            'txo_hash': txo.hash,
            'amount': txo.amount,
            'height': txo.tx_ref.height,
            'timestamp': timestamp,
            # support
            'staked_amount': txo.amount + staked_support_amount,
            'staked_support_amount': staked_support_amount,
            'staked_support_count': staked_support_count,
            # basic metadata
            'title': None,
            'description': None,
            'author': None,
            # streams
            'stream_type': None,
            'media_type': None,
            'duration': None,
            'release_time': None,
            'fee_amount': 0,
            'fee_currency': None,
            # reposts
            'reposted_claim_hash': None,
            # signed claims
            'channel_hash': None,
            'is_signature_valid': None,
        }

        claim = txo.can_decode_claim
        if not claim:
            return d, []

        if claim.is_stream:
            d['claim_type'] = TXO_TYPES['stream']
            d['stream_type'] = STREAM_TYPES[guess_stream_type(d['media_type'])]
            d['media_type'] = claim.stream.source.media_type
            d['title'] = claim.stream.title.replace('\x00', '')
            d['description'] = claim.stream.description.replace('\x00', '')
            d['author'] = claim.stream.author.replace('\x00', '')
            if claim.stream.video and claim.stream.video.duration:
                d['duration'] = claim.stream.video.duration
            if claim.stream.audio and claim.stream.audio.duration:
                d['duration'] = claim.stream.audio.duration
            if claim.stream.release_time:
                d['release_time'] = claim.stream.release_time
            if claim.stream.has_fee:
                fee = claim.stream.fee
                if isinstance(fee.amount, Decimal):
                    d['fee_amount'] = int(fee.amount*1000)
                if isinstance(fee.currency, str):
                    d['fee_currency'] = fee.currency.lower()
        elif claim.is_repost:
            d['claim_type'] = TXO_TYPES['repost']
            d['reposted_claim_hash'] = claim.repost.reference.claim_hash
        elif claim.is_channel:
            d['claim_type'] = TXO_TYPES['channel']
        if claim.is_signed:
            d['channel_hash'] = claim.signing_channel_hash
            d['is_signature_valid'] = Output.is_signature_valid(
                signature, signature_digest, channel_public_key
            )

        tags = []
        if claim.message.tags:
            claim_hash = txo.claim_hash
            tags = [
                {'claim_hash': claim_hash, 'tag': tag}
                for tag in clean_tags(claim.message.tags)
            ]

        return d, tags

    def support_to_row(self, txo):
        tx = txo.tx_ref.tx
        d = {
            'txo_hash': txo.ref.hash,
            'claim_hash': txo.claim_hash,
            'address': txo.get_address(self.ledger),
            'amount': txo.amount,
            'height': tx.height,
            'emoji': None,
            'channel_hash': None,
            'signature': None,
            'signature_digest': None,
        }
        support = txo.can_decode_support
        if support:
            d['emoji'] = support.emoji
            if support.is_signed:
                d['channel_hash'] = support.signing_channel_hash
                d['signature'] = txo.get_encoded_signature()
                d['signature_digest'] = txo.get_signature_digest(None)
        return d

    def add_block(self, block: Block):
        self.blocks.append(self.block_to_row(block))
        for tx in block.txs:
            self.add_transaction(block.block_hash, tx)
        return self

    def add_transaction(self, block_hash: bytes, tx: Transaction):
        self.txs.append(self.tx_to_row(block_hash, tx))
        for txi in tx.inputs:
            if txi.coinbase is None:
                self.txis.append(self.txi_to_row(tx, txi))
        for txo in tx.outputs:
            self.txos.append(self.txo_to_row(tx, txo))
        return self

    def add_support(self, txo: Output):
        self.supports.append(self.support_to_row(txo))

    def add_claim(
            self, txo: Output, short_url: str,
            creation_height: int, activation_height: int, expiration_height: int,
            takeover_height: int = None, channel_url: str = None, **extra):
        try:
            claim_name = txo.claim_name.replace('\x00', '')
            normalized_name = txo.normalized_name
        except UnicodeDecodeError:
            return self
        d, tags = self.claim_to_rows(txo, **extra)
        d['claim_hash'] = txo.claim_hash
        d['claim_id'] = txo.claim_id
        d['claim_name'] = claim_name
        d['normalized'] = normalized_name
        d['short_url'] = short_url
        d['creation_height'] = creation_height
        d['activation_height'] = activation_height
        d['expiration_height'] = expiration_height
        d['takeover_height'] = takeover_height
        d['is_controlling'] = takeover_height is not None
        if d['is_signature_valid']:
            d['canonical_url'] = channel_url + '/' + short_url
        else:
            d['canonical_url'] = None
        self.claims.append(d)
        self.tags.extend(tags)
        return self

    def update_claim(self, txo: Output, channel_url: Optional[str], **extra):
        d, tags = self.claim_to_rows(txo, **extra)
        d['pk'] = txo.claim_hash
        d['channel_url'] = channel_url
        d['set_canonical_url'] = d['is_signature_valid']
        self.update_claims.append(d)
        self.delete_tags.append({'pk': txo.claim_hash})
        self.tags.extend(tags)
        return self

    def get_queries(self):
        return (
            (Block.insert(), self.blocks),
            (TX.insert(), self.txs),
            (TXO.insert(), self.txos),
            (TXI.insert(), self.txis),
            (Claim.insert(), self.claims),
            (Tag.delete().where(Tag.c.claim_hash == bindparam('pk')), self.delete_tags),
            (Claim.update().where(Claim.c.claim_hash == bindparam('pk')).values(
                canonical_url=case([
                    (bindparam('set_canonical_url'), bindparam('channel_url') + '/' + Claim.c.short_url)
                ], else_=None)
            ), self.update_claims),
            (Tag.insert(), self.tags),
            (Support.insert(), self.supports),
        )

    def save(self, unit_table, batch_size=10000):
        queries = self.get_queries()

        p = self.ctx.current_progress
        done = row_scale = 0
        if p:
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
            if not rows:
                continue
            if self.ctx.is_postgres and isinstance(sql, Insert):
                self.ctx.pg_copy(sql.table, rows)
                if p:
                    done += int(len(rows) / row_scale)
                    p.step(done)
            else:
                for chunk_rows in chunk(rows, batch_size):
                    try:
                        execute(sql, chunk_rows)
                    except Exception:
                        for row in chunk_rows:
                            try:
                                execute(sql, [row])
                            except Exception:
                                p.ctx.message_queue.put_nowait(
                                    (Event.COMPLETE.value, os.getpid(), 1, 1)
                                )
                                with open('badrow', 'a') as badrow:
                                    badrow.write(repr(sql))
                                    badrow.write('\n')
                                    badrow.write(repr(row))
                                    badrow.write('\n')
                                print(sql)
                                print(row)
                        raise
                    if p:
                        done += int(len(chunk_rows)/row_scale)
                        p.step(done)

    def flush(self, done_counter_table) -> int:
        execute = self.ctx.connection.execute
        done = 0
        for sql, rows in self.get_queries():
            if not rows:
                continue
            if self.ctx.is_postgres and isinstance(sql, Insert):
                self.ctx.pg_copy(sql.table, rows)
            else:
                execute(sql, rows)
            if sql.table == done_counter_table:
                done += len(rows)
            rows.clear()
        return done
