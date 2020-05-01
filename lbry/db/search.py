import time
import struct
import apsw
import logging
from operator import itemgetter
from typing import Tuple, List, Dict, Union, Type, Optional
from binascii import unhexlify
from decimal import Decimal
from contextvars import ContextVar
from functools import wraps
from itertools import chain
from dataclasses import dataclass

from lbry.wallet.database import query, interpolate
from lbry.error import ResolveCensoredError
from lbry.schema.url import URL, normalize_name
from lbry.schema.tags import clean_tags
from lbry.schema.result import Outputs, Censor
from lbry.blockchain.ledger import Ledger, RegTestLedger

from .constants import CLAIM_TYPES, STREAM_TYPES
from .full_text_search import FTS_ORDER_BY


class SQLiteOperationalError(apsw.Error):
    def __init__(self, metrics):
        super().__init__('sqlite query errored')
        self.metrics = metrics


class SQLiteInterruptedError(apsw.InterruptError):
    def __init__(self, metrics):
        super().__init__('sqlite query interrupted')
        self.metrics = metrics




@dataclass
class ReaderState:
    db: apsw.Connection
    stack: List[List]
    metrics: Dict
    is_tracking_metrics: bool
    ledger: Type[Ledger]
    query_timeout: float
    log: logging.Logger
    blocked_streams: Dict
    blocked_channels: Dict
    filtered_streams: Dict
    filtered_channels: Dict

    def close(self):
        self.db.close()

    def reset_metrics(self):
        self.stack = []
        self.metrics = {}

    def set_query_timeout(self):
        stop_at = time.perf_counter() + self.query_timeout

        def interruptor():
            if time.perf_counter() >= stop_at:
                self.db.interrupt()
            return

        self.db.setprogresshandler(interruptor, 100)

    def get_resolve_censor(self) -> Censor:
        return Censor(self.blocked_streams, self.blocked_channels)

    def get_search_censor(self) -> Censor:
        return Censor(self.filtered_streams, self.filtered_channels)


ctx: ContextVar[Optional[ReaderState]] = ContextVar('ctx')


def row_factory(cursor, row):
    return {
        k[0]: (set(row[i].split(',')) if k[0] == 'tags' else row[i])
        for i, k in enumerate(cursor.getdescription())
    }


def initializer(log, _path, _ledger_name, query_timeout, _measure=False, block_and_filter=None):
    db = apsw.Connection(_path, flags=apsw.SQLITE_OPEN_READONLY | apsw.SQLITE_OPEN_URI)
    db.setrowtrace(row_factory)
    if block_and_filter:
        blocked_streams, blocked_channels, filtered_streams, filtered_channels = block_and_filter
    else:
        blocked_streams = blocked_channels = filtered_streams = filtered_channels = {}
    ctx.set(
        ReaderState(
            db=db, stack=[], metrics={}, is_tracking_metrics=_measure,
            ledger=Ledger if _ledger_name == 'mainnet' else RegTestLedger,
            query_timeout=query_timeout, log=log,
            blocked_streams=blocked_streams, blocked_channels=blocked_channels,
            filtered_streams=filtered_streams, filtered_channels=filtered_channels,
        )
    )


def cleanup():
    ctx.get().close()
    ctx.set(None)


def measure(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        state = ctx.get()
        if not state.is_tracking_metrics:
            return func(*args, **kwargs)
        metric = {}
        state.metrics.setdefault(func.__name__, []).append(metric)
        state.stack.append([])
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            elapsed = int((time.perf_counter()-start)*1000)
            metric['total'] = elapsed
            metric['isolated'] = (elapsed-sum(state.stack.pop()))
            if state.stack:
                state.stack[-1].append(elapsed)
    return wrapper


def reports_metrics(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        state = ctx.get()
        if not state.is_tracking_metrics:
            return func(*args, **kwargs)
        state.reset_metrics()
        r = func(*args, **kwargs)
        return r, state.metrics
    return wrapper


