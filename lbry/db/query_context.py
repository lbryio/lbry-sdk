import os
import time
import traceback
import functools
from io import BytesIO
import multiprocessing as mp
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from contextvars import ContextVar

from sqlalchemy import create_engine, inspect, bindparam, func, exists, event as sqlalchemy_event
from sqlalchemy.future import select
from sqlalchemy.engine import Engine
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

from .utils import pg_insert
from .tables import (
    Block, BlockFilter, BlockGroupFilter,
    TX, TXFilter, TXO, TXI, Claim, Tag, Support
)
from .constants import TXO_TYPES, STREAM_TYPES


_context: ContextVar['QueryContext'] = ContextVar('_context')


@dataclass
class QueryContext:
    engine: Engine
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
    current_timer_name: Optional[str] = None
    current_timer_time: float = 0
    current_progress: Optional['ProgressContext'] = None

    copy_managers: Dict[str, CopyManager] = field(default_factory=dict)
    _variable_limit: Optional[int] = None

    @property
    def is_postgres(self):
        return self.engine.dialect.name == 'postgresql'

    @property
    def is_sqlite(self):
        return self.engine.dialect.name == 'sqlite'

    @property
    def variable_limit(self):
        if self._variable_limit is not None:
            return self._variable_limit
        if self.is_sqlite:
            for result in self.fetchall('PRAGMA COMPILE_OPTIONS;'):
                for _, value in result.items():
                    if value.startswith('MAX_VARIABLE_NUMBER'):
                        self._variable_limit = int(value.split('=')[1])
                        return self._variable_limit
            self._variable_limit = 999  # todo: default for 3.32.0 is 32766, but we are still hitting 999 somehow
        else:
            self._variable_limit = 32766
        return self._variable_limit

    def raise_unsupported_dialect(self):
        raise RuntimeError(f'Unsupported database dialect: {self.engine.dialect.name}.')

    @classmethod
    def get_resolve_censor(cls) -> Censor:
        return Censor(Censor.RESOLVE)

    @classmethod
    def get_search_censor(cls) -> Censor:
        return Censor(Censor.SEARCH)

    def pg_copy(self, table, rows):
        with self.engine.begin() as c:
            copy_manager = self.copy_managers.get(table.name)
            if copy_manager is None:
                self.copy_managers[table.name] = copy_manager = CopyManager(
                    c.connection, table.name, rows[0].keys()
                )
            copy_manager.conn = c.connection
            copy_manager.copy(map(dict.values, rows), BytesIO)
            copy_manager.conn = None

    def connect_without_transaction(self):
        return self.engine.connect().execution_options(isolation_level="AUTOCOMMIT")

    def connect_streaming(self):
        return self.engine.connect().execution_options(stream_results=True)

    def execute_notx(self, sql, *args):
        with self.connect_without_transaction() as c:
            return c.execute(sql, *args)

    def execute(self, sql, *args):
        with self.engine.begin() as c:
            return c.execute(sql, *args)

    def fetchone(self, sql, *args):
        with self.engine.begin() as c:
            row = c.execute(sql, *args).fetchone()
            return dict(row._mapping) if row else row

    def fetchall(self, sql, *args):
        with self.engine.begin() as c:
            rows = c.execute(sql, *args).fetchall()
            return [dict(row._mapping) for row in rows]

    def fetchtotal(self, condition) -> int:
        sql = select(func.count('*').label('total')).where(condition)
        return self.fetchone(sql)['total']

    def fetchmax(self, column, default: int) -> int:
        sql = select(func.coalesce(func.max(column), default).label('max_result'))
        return self.fetchone(sql)['max_result']

    def has_records(self, table) -> bool:
        sql = select(exists([1], from_obj=table).label('result'))
        return bool(self.fetchone(sql)['result'])

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

    @property
    def elapsed(self):
        return time.perf_counter() - self.current_timer_time

    def __enter__(self) -> 'QueryContext':
        self.current_timer_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.current_timer_name = None
        self.current_timer_time = 0
        self.current_progress = None


def context(with_timer: str = None) -> 'QueryContext':
    if isinstance(with_timer, str):
        return _context.get().with_timer(with_timer)
    return _context.get()


def set_postgres_settings(connection, _):
    cursor = connection.cursor()
    cursor.execute('SET work_mem="500MB";')
    cursor.execute('COMMIT;')
    cursor.close()


def set_sqlite_settings(connection, _):
    connection.isolation_level = None
    cursor = connection.cursor()
    cursor.execute('PRAGMA journal_mode=WAL;')
    cursor.close()


def do_sqlite_begin(connection):
    # see: https://bit.ly/3j4vvXm
    connection.exec_driver_sql("BEGIN")


def initialize(
        ledger: Ledger, message_queue: mp.Queue, stop_event: mp.Event,
        track_metrics=False, block_and_filter=None):
    url = ledger.conf.db_url_or_default
    engine = create_engine(url)
    if engine.name == "postgresql":
        sqlalchemy_event.listen(engine, "connect", set_postgres_settings)
    elif engine.name == "sqlite":
        sqlalchemy_event.listen(engine, "connect", set_sqlite_settings)
        sqlalchemy_event.listen(engine, "begin", do_sqlite_begin)
    if block_and_filter is not None:
        blocked_streams, blocked_channels, filtered_streams, filtered_channels = block_and_filter
    else:
        blocked_streams = blocked_channels = filtered_streams = filtered_channels = {}
    _context.set(
        QueryContext(
            pid=os.getpid(), engine=engine,
            ledger=ledger, message_queue=message_queue, stop_event=stop_event,
            stack=[], metrics={}, is_tracking_metrics=track_metrics,
            blocked_streams=blocked_streams, blocked_channels=blocked_channels,
            filtered_streams=filtered_streams, filtered_channels=filtered_channels,
        )
    )


def uninitialize():
    ctx = _context.get(None)
    if ctx is not None:
        ctx.engine.dispose()
        _context.set(None)


class Event:
    _events: List['Event'] = []
    __slots__ = 'id', 'name', 'units'

    def __init__(self, name: str, units: Tuple[str]):
        self.id = None
        self.name = name
        self.units = units

    @classmethod
    def get_by_id(cls, event_id) -> 'Event':
        return cls._events[event_id]

    @classmethod
    def get_by_name(cls, name) -> 'Event':
        for event in cls._events:
            if event.name == name:
                return event

    @classmethod
    def add(cls, name: str, *units: str) -> 'Event':
        assert cls.get_by_name(name) is None, f"Event {name} already exists."
        assert name.count('.') == 3, f"Event {name} does not follow pattern of: [module].sync.[phase].[task]"
        event = cls(name, units)
        cls._events.append(event)
        event.id = cls._events.index(event)
        return event


def event_emitter(name: str, *units: str, throttle=1):
    event = Event.add(name, *units)

    def wrapper(f):
        @functools.wraps(f)
        def with_progress(*args, **kwargs):
            with progress(event, throttle=throttle) as p:
                try:
                    return f(*args, **kwargs, p=p)
                except BreakProgress:
                    raise
                except:
                    traceback.print_exc()
                    raise
        return with_progress

    return wrapper


class ProgressPublisher(EventQueuePublisher):

    def message_to_event(self, message):
        total, extra = None, None
        if len(message) == 3:
            event_id, progress_id, done = message
        elif len(message) == 5:
            event_id, progress_id, done, total, extra = message
        else:
            raise TypeError("progress message must be tuple of 3 or 5 values.")
        event = Event.get_by_id(event_id)
        d = {
            "event": event.name,
            "data": {"id": progress_id, "done": done}
        }
        if total is not None:
            d['data']['total'] = total
            d['data']['units'] = event.units
        if isinstance(extra, dict):
            d['data'].update(extra)
        return d


class BreakProgress(Exception):
    """Break out of progress when total is 0."""


class Progress:

    def __init__(self, message_queue: mp.Queue, event: Event, throttle=1):
        self.message_queue = message_queue
        self.event = event
        self.progress_id = 0
        self.throttle = throttle
        self.last_done = (0,)*len(event.units)
        self.last_done_queued = (0,)*len(event.units)
        self.totals = (0,)*len(event.units)

    def __enter__(self) -> 'Progress':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.last_done != self.last_done_queued:
            self.message_queue.put((self.event.id, self.progress_id, self.last_done))
            self.last_done_queued = self.last_done
        if exc_type == BreakProgress:
            return True
        if self.last_done != self.totals:  # or exc_type is not None:
            # TODO: add exception info into closing message if there is any
            self.message_queue.put((
                self.event.id, self.progress_id, (-1,)*len(self.event.units)
            ))

    def start(self, *totals: int, progress_id=0, label=None, extra=None):
        assert len(totals) == len(self.event.units), \
            f"Totals {totals} do not match up with units {self.event.units}."
        if not any(totals):
            raise BreakProgress
        self.totals = totals
        self.progress_id = progress_id
        extra = {} if extra is None else extra.copy()
        if label is not None:
            extra['label'] = label
        self.step(*((0,)*len(totals)), force=True, extra=extra)

    def step(self, *done: int, force=False, extra=None):
        if done == ():
            assert len(self.totals) == 1, "Incrementing step() only works with one unit progress."
            done = (self.last_done[0]+1,)
        assert len(done) == len(self.totals), \
            f"Done elements {done} don't match total elements {self.totals}."
        self.last_done = done
        send_condition = force or extra is not None or (
            # throttle rate of events being generated (only throttles first unit value)
            (self.throttle == 1 or done[0] % self.throttle == 0) and
            # deduplicate finish event by not sending a step where done == total
            any(i < j for i, j in zip(done, self.totals)) and
            # deduplicate same event
            done != self.last_done_queued
        )
        if send_condition:
            if extra is not None:
                self.message_queue.put_nowait(
                    (self.event.id, self.progress_id, done, self.totals, extra)
                )
            else:
                self.message_queue.put_nowait(
                    (self.event.id, self.progress_id, done)
                )
            self.last_done_queued = done

    def add(self, *done: int, force=False, extra=None):
        assert len(done) == len(self.last_done), \
            f"Done elements {done} don't match total elements {self.last_done}."
        self.step(
            *(i+j for i, j in zip(self.last_done, done)),
            force=force, extra=extra
        )

    def iter(self, items: List):
        self.start(len(items))
        for item in items:
            yield item
            self.step()


class ProgressContext(Progress):

    def __init__(self, ctx: QueryContext, event: Event, throttle=1):
        super().__init__(ctx.message_queue, event, throttle)
        self.ctx = ctx

    def __enter__(self) -> 'ProgressContext':
        self.ctx.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return any((
            self.ctx.__exit__(exc_type, exc_val, exc_tb),
            super().__exit__(exc_type, exc_val, exc_tb)
        ))


def progress(e: Event, throttle=1) -> ProgressContext:
    ctx = context(e.name)
    ctx.current_progress = ProgressContext(ctx, e, throttle=throttle)
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
        self.tx_filters = []
        self.block_filters = []
        self.group_filters = []

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
            #'block_hash': block_hash,
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
            'reposted_claim_hash': None,
            'public_key': None,
            'public_key_hash': None
        }
        if txo.is_claim:
            if txo.can_decode_claim:
                claim = txo.claim
                row['txo_type'] = TXO_TYPES.get(claim.claim_type, TXO_TYPES['stream'])
                if claim.is_channel:
                    row['public_key'] = claim.channel.public_key_bytes
                    row['public_key_hash'] = self.ledger.address_to_hash160(
                        self.ledger.public_key_to_address(claim.channel.public_key_bytes)
                    )
                elif claim.is_repost:
                    row['reposted_claim_hash'] = claim.repost.reference.claim_hash
            else:
                row['txo_type'] = TXO_TYPES['stream']
        elif txo.is_support:
            row['txo_type'] = TXO_TYPES['support']
        elif txo.purchase is not None:
            row['txo_type'] = TXO_TYPES['purchase']
            row['claim_id'] = txo.purchased_claim_id
            row['claim_hash'] = txo.purchased_claim_hash
        if txo.script.is_claim_involved:
            signable = txo.can_decode_signable
            if signable and signable.is_signed:
                row['channel_hash'] = signable.signing_channel_hash
                row['signature'] = txo.get_encoded_signature()
                row['signature_digest'] = txo.get_signature_digest(self.ledger)
            row['claim_id'] = txo.claim_id
            row['claim_hash'] = txo.claim_hash
            try:
                row['claim_name'] = txo.claim_name.replace('\x00', '')
            except UnicodeDecodeError:
                pass
        return row

    def claim_to_rows(
        self, txo: Output, claims_in_channel_amount: int, staked_support_amount: int, staked_support_count: int,
        reposted_count: int, signature: bytes = None, signature_digest: bytes = None, channel_public_key: bytes = None,
    ) -> Tuple[dict, List]:

        tx = txo.tx_ref
        d = {
            'claim_type': None,
            'address': txo.get_address(self.ledger),
            'txo_hash': txo.hash,
            'amount': txo.amount,
            'height': tx.height,
            'timestamp': tx.timestamp,
            # support
            'staked_amount': txo.amount + claims_in_channel_amount + staked_support_amount,
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
            'reposted_count': reposted_count,
            # signed claims
            'channel_hash': None,
            'is_signature_valid': None,
        }

        claim = txo.can_decode_claim
        if not claim:
            return d, []

        if claim.is_stream:
            d['claim_type'] = TXO_TYPES['stream']
            d['media_type'] = claim.stream.source.media_type
            d['stream_type'] = STREAM_TYPES[guess_stream_type(d['media_type'])]
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
            d['is_signature_valid'] = (
                all((signature, signature_digest, channel_public_key)) and
                Output.is_signature_valid(
                    signature, signature_digest, channel_public_key
                )
            )

        tags = []
        if claim.message.tags:
            claim_hash = txo.claim_hash
            tags = [
                {'claim_hash': claim_hash, 'tag': tag}
                for tag in clean_tags(claim.message.tags)
            ]

        return d, tags

    def support_to_row(
        self, txo: Output, channel_public_key: bytes = None,
        signature: bytes = None, signature_digest: bytes = None
    ):
        tx = txo.tx_ref
        d = {
            'txo_hash': txo.ref.hash,
            'claim_hash': txo.claim_hash,
            'address': txo.get_address(self.ledger),
            'amount': txo.amount,
            'height': tx.height,
            'timestamp': tx.timestamp,
            'emoji': None,
            'channel_hash': None,
            'is_signature_valid': None,
        }
        support = txo.can_decode_support
        if support:
            d['emoji'] = support.emoji
            if support.is_signed:
                d['channel_hash'] = support.signing_channel_hash
                d['is_signature_valid'] = (
                    all((signature, signature_digest, channel_public_key)) and
                    Output.is_signature_valid(
                        signature, signature_digest, channel_public_key
                    )
                )
        return d

    def add_block(self, block: Block):
        self.blocks.append(self.block_to_row(block))
        for tx in block.txs:
            self.add_transaction(block.block_hash, tx)
        return self

    def add_block_filter(self, height: int, address_filter: bytes):
        self.block_filters.append({
            'height': height,
            'address_filter': address_filter
        })

    def add_group_filter(self, height: int, factor: int, address_filter: bytes):
        self.group_filters.append({
            'height': height,
            'factor': factor,
            'address_filter': address_filter
        })

    def add_transaction(self, block_hash: bytes, tx: Transaction):
        self.txs.append(self.tx_to_row(block_hash, tx))
        for txi in tx.inputs:
            if txi.coinbase is None:
                self.txis.append(self.txi_to_row(tx, txi))
        for txo in tx.outputs:
            self.txos.append(self.txo_to_row(tx, txo))
        return self

    def add_transaction_filter(self, tx_hash: bytes, height: int, address_filter: bytes):
        self.tx_filters.append({
            'tx_hash': tx_hash,
            'height': height,
            'address_filter': address_filter
        })

    def add_support(self, txo: Output, **extra):
        self.supports.append(self.support_to_row(txo, **extra))

    def add_claim(
        self, txo: Output, short_url: str,
        creation_height: int, activation_height: int, expiration_height: int,
        takeover_height: int = None, **extra
    ):
        try:
            claim_name = txo.claim_name.replace('\x00', '')
            normalized_name = txo.normalized_name
        except UnicodeDecodeError:
            claim_name = normalized_name = ''
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
        self.claims.append(d)
        self.tags.extend(tags)
        return self

    def update_claim(self, txo: Output, **extra):
        d, tags = self.claim_to_rows(txo, **extra)
        d['pk'] = txo.claim_hash
        self.update_claims.append(d)
        self.delete_tags.append({'pk': txo.claim_hash})
        self.tags.extend(tags)
        return self

    def get_queries(self):
        return (
            (Block.insert(), self.blocks),
            (BlockFilter.insert(), self.block_filters),
            (BlockGroupFilter.insert(), self.group_filters),
            (TX.insert(), self.txs),
            (TXFilter.insert(), self.tx_filters),
            (TXO.insert(), self.txos),
            (TXI.insert(), self.txis),
            (Claim.insert(), self.claims),
            (Tag.delete().where(Tag.c.claim_hash == bindparam('pk')), self.delete_tags),
            (Claim.update().where(Claim.c.claim_hash == bindparam('pk')), self.update_claims),
            (Tag.insert(), self.tags),
            (Support.insert(), self.supports),
        )

    def flush(self, return_row_count_for_table) -> int:
        done = 0
        for sql, rows in self.get_queries():
            if not rows:
                continue
            if self.ctx.is_postgres and isinstance(sql, Insert):
                self.ctx.pg_copy(sql.table, rows)
            else:
                self.ctx.execute(sql, rows)
            if sql.table == return_row_count_for_table:
                done += len(rows)
            rows.clear()
        return done
