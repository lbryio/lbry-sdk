import logging
from typing import Tuple

from sqlalchemy import case, desc, text
from sqlalchemy.future import select

from lbry.db.tables import TX, TXO, Support, pg_add_support_constraints_and_indexes
from lbry.db.query_context import ProgressContext, event_emitter
from lbry.db.queries import row_to_txo
from lbry.db.constants import TXO_TYPES
from lbry.db.queries.txio import (
    MINIMIUM_TXO_COLUMNS,
    where_unspent_txos, where_abandoned_supports,
    count_unspent_txos,
)

from .claims import make_label


log = logging.getLogger(__name__)


@event_emitter("blockchain.sync.supports.insert", "supports")
def supports_insert(
    blocks: Tuple[int, int],
    missing_in_supports_table: bool,
    flush_size: int,
    p: ProgressContext
):
    p.start(
        count_unspent_txos(
            TXO_TYPES['support'], blocks,
            missing_in_supports_table=missing_in_supports_table,
        ), progress_id=blocks[0], label=make_label("add supprt", blocks)
    )
    channel_txo = TXO.alias('channel_txo')
    select_supports = select(
        *MINIMIUM_TXO_COLUMNS, TXO.c.claim_hash,
        TXO.c.signature, TXO.c.signature_digest,
        case([(
            TXO.c.channel_hash.isnot(None),
            select(channel_txo.c.public_key).select_from(channel_txo).where(
                (channel_txo.c.txo_type == TXO_TYPES['channel']) &
                (channel_txo.c.claim_hash == TXO.c.channel_hash) &
                (channel_txo.c.height <= TXO.c.height)
            ).order_by(desc(channel_txo.c.height)).limit(1).scalar_subquery()
        )]).label('channel_public_key'),
    ).select_from(
        TXO.join(TX)
    ).where(
        where_unspent_txos(
            TXO_TYPES['support'], blocks,
            missing_in_supports_table=missing_in_supports_table,
        )
    )
    with p.ctx.connect_streaming() as c:
        loader = p.ctx.get_bulk_loader()
        for row in c.execute(select_supports):
            txo = row_to_txo(row)
            loader.add_support(
                txo,
                signature=row.signature,
                signature_digest=row.signature_digest,
                channel_public_key=row.channel_public_key
            )
            if len(loader.supports) >= flush_size:
                p.add(loader.flush(Support))
        p.add(loader.flush(Support))


@event_emitter("blockchain.sync.supports.delete", "supports")
def supports_delete(supports, p: ProgressContext):
    p.start(supports, label="del supprt")
    deleted = p.ctx.execute(Support.delete().where(where_abandoned_supports()))
    p.step(deleted.rowcount)


@event_emitter("blockchain.sync.supports.indexes", "steps")
def supports_constraints_and_indexes(p: ProgressContext):
    p.start(1 + len(pg_add_support_constraints_and_indexes))
    if p.ctx.is_postgres:
        p.ctx.execute_notx(text("VACUUM ANALYZE support;"))
    p.step()
    for constraint in pg_add_support_constraints_and_indexes:
        if p.ctx.is_postgres:
            p.ctx.execute(text(constraint))
        p.step()


@event_emitter("blockchain.sync.supports.vacuum", "steps")
def supports_vacuum(p: ProgressContext):
    p.start(1)
    if p.ctx.is_postgres:
        p.ctx.execute_notx(text("VACUUM support;"))
    p.step()
