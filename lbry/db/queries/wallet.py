from sqlalchemy import exists
from sqlalchemy.future import select

from ..query_context import context
from ..tables import Wallet


def has_wallet(wallet_id: str) -> bool:
    sql = select(exists(select(Wallet.c.wallet_id).where(Wallet.c.wallet_id == wallet_id)))
    return context().execute(sql).fetchone()[0]


def get_wallet(wallet_id: str):
    return context().fetchone(
        select(Wallet.c.data).where(Wallet.c.wallet_id == wallet_id)
    )


def add_wallet(wallet_id: str, data: str):
    c = context()
    c.execute(
        c.insert_or_replace(Wallet, ["data"])
        .values(wallet_id=wallet_id, data=data)
    )
