import logging
from typing import Tuple, List, Set, Iterator, Optional

from sqlalchemy import func
from sqlalchemy.future import select

from lbry.crypto.hash import hash160
from lbry.crypto.bip32 import PubKey

from ..utils import query
from ..query_context import context
from ..tables import TXO, PubkeyAddress, AccountAddress
from .filters import get_filter_matchers, get_filter_matchers_at_granularity, has_sub_filters


log = logging.getLogger(__name__)


class DatabaseAddressIterator:

    def __init__(self, account_id, chain):
        self.account_id = account_id
        self.chain = chain
        self.n = -1

    def __iter__(self) -> Iterator[Tuple[bytes, int, bool]]:
        with context().connect_streaming() as c:
            sql = (
                select(
                    AccountAddress.c.pubkey,
                    AccountAddress.c.n
                ).where(
                    (AccountAddress.c.account == self.account_id) &
                    (AccountAddress.c.chain == self.chain)
                ).order_by(AccountAddress.c.n)
            )
            for row in c.execute(sql):
                self.n = row['n']
                yield hash160(row['pubkey']), self.n, False


class PersistingAddressIterator(DatabaseAddressIterator):

    def __init__(self, account_id, chain, pubkey_bytes, chain_code, depth):
        super().__init__(account_id, chain)
        self.pubkey_bytes = pubkey_bytes
        self.chain_code = chain_code
        self.depth = depth
        self.pubkey_buffer = []

    def flush(self):
        if self.pubkey_buffer:
            add_keys([{
                'account': self.account_id,
                'address': k.address,
                'chain': self.chain,
                'pubkey': k.pubkey_bytes,
                'chain_code': k.chain_code,
                'n': k.n,
                'depth': k.depth
            } for k in self.pubkey_buffer])
            self.pubkey_buffer.clear()

    def __enter__(self) -> 'PersistingAddressIterator':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.flush()

    def __iter__(self) -> Iterator[Tuple[bytes, int, bool]]:
        yield from super().__iter__()
        pubkey = PubKey(context().ledger, self.pubkey_bytes, self.chain_code, 0, self.depth)
        while True:
            self.n += 1
            pubkey_child = pubkey.child(self.n)
            self.pubkey_buffer.append(pubkey_child)
            if len(self.pubkey_buffer) >= 900:
                self.flush()
            yield hash160(pubkey_child.pubkey_bytes), self.n, True


def generate_addresses_using_filters(best_height, allowed_gap, address_manager) -> Set:
    need, have = set(), set()
    matchers = get_filter_matchers(best_height)
    with PersistingAddressIterator(*address_manager) as addresses:
        gap = 0
        for address_hash, n, is_new in addresses:
            gap += 1
            address_bytes = bytearray(address_hash)
            for granularity, height, matcher in matchers:
                if matcher.Match(address_bytes):
                    gap = 0
                    match = (granularity, height)
                    if match not in need and match not in have:
                        if has_sub_filters(granularity, height):
                            have.add(match)
                        else:
                            need.add(match)
            if gap >= allowed_gap:
                break
    return need


def get_missing_sub_filters_for_addresses(granularity, address_manager):
    need = set()
    with DatabaseAddressIterator(*address_manager) as addresses:
        for height, matcher in get_filter_matchers_at_granularity(granularity):
            for address_hash, n, is_new in addresses:
                address_bytes = bytearray(address_hash)
                if matcher.Match(address_bytes) and not has_sub_filters(granularity, height):
                    need.add((height, granularity))
                    break
    return need


def update_address_used_times(addresses):
    context().execute(
        PubkeyAddress.update()
        .values(used_times=(
            select(func.count(TXO.c.address))
            .where((TXO.c.address == PubkeyAddress.c.address)),
        ))
        .where(PubkeyAddress.c.address._in(addresses))
    )


def select_addresses(cols, **constraints):
    return context().fetchall(query(
        [AccountAddress, PubkeyAddress],
        select(*cols).select_from(PubkeyAddress.join(AccountAddress)),
        **constraints
    ))


def get_addresses(cols=None, include_total=False, **constraints) -> Tuple[List[dict], Optional[int]]:
    if cols is None:
        cols = (
            PubkeyAddress.c.address,
            PubkeyAddress.c.used_times,
            AccountAddress.c.account,
            AccountAddress.c.chain,
            AccountAddress.c.pubkey,
            AccountAddress.c.chain_code,
            AccountAddress.c.n,
            AccountAddress.c.depth
        )
    return (
        select_addresses(cols, **constraints),
        get_address_count(**constraints) if include_total else None
    )


def get_address_count(**constraints):
    count = select_addresses([func.count().label("total")], **constraints)
    return count[0]["total"] or 0


def get_all_addresses():
    return [r["address"] for r in context().fetchall(select(PubkeyAddress.c.address))]


def add_keys(pubkeys):
    c = context()
    current_limit = c.variable_limit // len(pubkeys[0])  # (overall limit) // (maximum on a query)
    for start in range(0, len(pubkeys), current_limit - 1):
        batch = pubkeys[start:(start + current_limit - 1)]
        c.execute(c.insert_or_ignore(PubkeyAddress).values([{'address': k['address']} for k in batch]))
        c.execute(c.insert_or_ignore(AccountAddress).values(batch))
