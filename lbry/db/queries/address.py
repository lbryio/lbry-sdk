import logging
from typing import Tuple, List, Set, Iterator, Optional

from sqlalchemy import func
from sqlalchemy.future import select

from lbry.crypto.hash import hash160
from lbry.crypto.bip32 import PubKey

from ..utils import query
from ..query_context import context
from ..tables import TXO, PubkeyAddress, AccountAddress
from .filters import (
    get_filter_matchers, get_filter_matchers_at_granularity, has_filter_range,
    get_tx_matchers_for_missing_txs,
)


log = logging.getLogger(__name__)


class DatabaseAddressIterator:

    def __init__(self, account_id, chain):
        self.account_id = account_id
        self.chain = chain
        self.n = -1

    @staticmethod
    def get_sql(account_id, chain):
        return (
            select(
                AccountAddress.c.pubkey,
                AccountAddress.c.n
            ).where(
                (AccountAddress.c.account == account_id) &
                (AccountAddress.c.chain == chain)
            ).order_by(AccountAddress.c.n)
        )

    @staticmethod
    def get_address_hash_bytes(account_id, chain):
        return [
            bytearray(hash160(row['pubkey'])) for row in context().fetchall(
                DatabaseAddressIterator.get_sql(account_id, chain)
            )
        ]

    def __iter__(self) -> Iterator[Tuple[bytes, int, bool]]:
        with context().connect_streaming() as c:
            sql = self.get_sql(self.account_id, self.chain)
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
        for address_hash, n, is_new in addresses:  # pylint: disable=unused-variable
            gap += 1
            address_bytes = bytearray(address_hash)
            for matcher, filter_range in matchers:
                if matcher.Match(address_bytes):
                    gap = 0
                    if filter_range not in need and filter_range not in have:
                        if has_filter_range(*filter_range):
                            have.add(filter_range)
                        else:
                            need.add(filter_range)
            if gap >= allowed_gap:
                break
    return need


def get_missing_sub_filters_for_addresses(granularity, address_manager):
    need = set()
    filters = get_filter_matchers_at_granularity(granularity)
    addresses = DatabaseAddressIterator.get_address_hash_bytes(*address_manager)
    for matcher, filter_range in filters:
        if matcher.MatchAny(addresses) and not has_filter_range(*filter_range):
            need.add(filter_range)
    return need


def get_missing_tx_for_addresses(address_manager):
    need = set()
    for tx_hash, matcher in get_tx_matchers_for_missing_txs():
        for address_hash, _, _ in DatabaseAddressIterator(*address_manager):
            address_bytes = bytearray(address_hash)
            if matcher.Match(address_bytes):
                need.add(tx_hash)
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
