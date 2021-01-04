from math import log10
from typing import Dict, List, Tuple, Set, Optional

from sqlalchemy import between, func, or_
from sqlalchemy.future import select

from lbry.blockchain.block import PyBIP158, get_address_filter

from ..query_context import context
from ..tables import BlockFilter, TXFilter, TX


def has_filters():
    return context().has_records(BlockFilter)


def get_sub_filter_range(granularity: int, height: int):
    end = height
    if granularity >= 3:
        end = height + 10**(granularity-1) * 9
    elif granularity == 2:
        end = height + 99
    return granularity - 1, height, end


def has_filter_range(factor: int, start: int, end: int):
    if factor >= 1:
        filters = context().fetchtotal(
            (BlockFilter.c.factor == factor) &
            between(BlockFilter.c.height, start, end)
        )
        expected = 10 if factor >= 2 else 100
        return filters == expected
    elif factor == 0:
        tx_filters_count = context().fetchtotal(TXFilter.c.height == start)
        return tx_filters_count > 0


def get_filters(start_height, end_height=None, granularity=0):
    assert granularity >= 0, "filter granularity must be 0 or positive number"
    if granularity == 0:
        query = (
            select(TXFilter.c.height, TXFilter.c.address_filter, TXFilter.c.tx_hash)
            .select_from(TXFilter)
            .where(between(TXFilter.c.height, start_height, end_height))
            .order_by(TXFilter.c.height)
        )
    else:
        factor = granularity if granularity <= 4 else log10(granularity)
        if end_height is None:
            height_condition = (BlockFilter.c.height == start_height)
        elif end_height == -1:
            height_condition = (BlockFilter.c.height >= start_height)
        else:
            height_condition = between(BlockFilter.c.height, start_height, end_height)
        query = (
            select(BlockFilter.c.height, BlockFilter.c.address_filter)
            .select_from(BlockFilter)
            .where(height_condition & (BlockFilter.c.factor == factor))
            .order_by(BlockFilter.c.height)
        )
    return context().fetchall(query)


def get_minimal_required_filter_ranges(height) -> Dict[int, Tuple[int, int]]:
    minimal = {}
    if height >= 10_000:
        minimal[4] = (0, ((height // 10_000)-1) * 10_000)
    if height >= 1_000:
        start = height - height % 10_000
        minimal[3] = (start, start+(((height-start) // 1_000)-1) * 1_000)
    if height >= 100:
        start = height - height % 1_000
        minimal[2] = (start, start+(((height-start) // 100)-1) * 100)
    start = height - height % 100
    if start < height:
        minimal[1] = (start, height)
    return minimal


def get_maximum_known_filters() -> Dict[str, Optional[int]]:
    query = select(
        select(func.max(BlockFilter.c.height))
            .where(BlockFilter.c.factor == 1)
            .scalar_subquery().label('1'),
        select(func.max(BlockFilter.c.height))
            .where(BlockFilter.c.factor == 2)
            .scalar_subquery().label('2'),
        select(func.max(BlockFilter.c.height))
            .where(BlockFilter.c.factor == 3)
            .scalar_subquery().label('3'),
        select(func.max(BlockFilter.c.height))
            .where(BlockFilter.c.factor == 4)
            .scalar_subquery().label('4'),
    )
    return context().fetchone(query)


def get_missing_required_filters(height) -> Set[Tuple[int, int, int]]:
    known_filters = get_maximum_known_filters()
    missing_filters = set()
    for granularity, (start, end) in get_minimal_required_filter_ranges(height).items():
        known_height = known_filters.get(str(granularity))
        if known_height is not None and known_height > start:
            if granularity == 1:
                adjusted_height = known_height + 1
            else:
                adjusted_height = known_height + 10**granularity
            if adjusted_height <= end:
                missing_filters.add((granularity, adjusted_height, end))
        else:
            missing_filters.add((granularity, start, end))
    return missing_filters


def get_filter_matchers(height) -> List[Tuple[int, int, PyBIP158]]:
    conditions = []
    for granularity, (start, end) in get_minimal_required_filter_ranges(height).items():
        conditions.append(
            (BlockFilter.c.factor == granularity) &
            between(BlockFilter.c.height, start, end)
        )
    query = (
        select(BlockFilter.c.factor, BlockFilter.c.height, BlockFilter.c.address_filter)
        .select_from(BlockFilter)
        .where(or_(*conditions))
        .order_by(BlockFilter.c.height.desc())
    )
    return [(
        bf["factor"], bf["height"],
        get_address_filter(bf["address_filter"]),
        get_sub_filter_range(bf["factor"], bf["height"])
    ) for bf in context().fetchall(query)]


def get_filter_matchers_at_granularity(granularity) -> List[Tuple[int, PyBIP158, Tuple]]:
    query = (
        select(BlockFilter.c.height, BlockFilter.c.address_filter)
        .where(BlockFilter.c.factor == granularity)
        .order_by(BlockFilter.c.height.desc())
    )
    return [(
        bf["height"],
        get_address_filter(bf["address_filter"]),
        get_sub_filter_range(granularity, bf["height"])
    ) for bf in context().fetchall(query)]


def get_tx_matchers_for_missing_txs() -> List[Tuple[int, PyBIP158]]:
    query = (
        select(TXFilter.c.tx_hash, TXFilter.c.address_filter)
        .where(TXFilter.c.tx_hash.notin_(select(TX.c.tx_hash)))
    )
    return [
        (bf["tx_hash"], get_address_filter(bf["address_filter"]))
        for bf in context().fetchall(query)
    ]


def insert_block_filter(height: int, factor: int, address_filter: bytes):
    loader = context().get_bulk_loader()
    loader.add_block_filter(height, factor, address_filter)
    loader.flush(return_row_count_for_table=None)


def insert_tx_filter(tx_hash: bytes, height: int, address_filter: bytes):
    loader = context().get_bulk_loader()
    loader.add_transaction_filter(tx_hash, height, address_filter)
    loader.flush(return_row_count_for_table=None)
