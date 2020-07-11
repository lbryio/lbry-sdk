import logging
from typing import Tuple, List, Optional

from sqlalchemy import func
from sqlalchemy.future import select

from ..utils import query
from ..query_context import context
from ..tables import TXO, PubkeyAddress, AccountAddress


log = logging.getLogger(__name__)


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
    count = select_addresses([func.count().label('total')], **constraints)
    return count[0]['total'] or 0


def get_all_addresses(self):
    return context().execute(select(PubkeyAddress.c.address))


def add_keys(account, chain, pubkeys):
    c = context()
    c.execute(
        c.insert_or_ignore(PubkeyAddress)
            .values([{'address': k.address} for k in pubkeys])
    )
    c.execute(
        c.insert_or_ignore(AccountAddress)
            .values([{
            'account': account.id,
            'address': k.address,
            'chain': chain,
            'pubkey': k.pubkey_bytes,
            'chain_code': k.chain_code,
            'n': k.n,
            'depth': k.depth
        } for k in pubkeys])
    )
